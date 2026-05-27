"""
ElevenLabs TTS engine — wrapper para geração de voz via ElevenLabs API.

Características:
- Retorna MP3 bytes prontos para ffplay.
- Não levanta exceção; em qualquer falha retorna b"" (caller faz fallback).
- Cache LRU em memória para frases repetidas.
- Circuit breaker: após erro 401/429 pausa por tempo configurável.

Uso:
    from VozIa.elevenlabs_tts import gerar_mp3, disponivel
    if disponivel():
        mp3 = gerar_mp3("Olá, Senhor.")
"""
from __future__ import annotations

import re
import time
from collections import OrderedDict
from typing import Optional

try:
    from elevenlabs import ElevenLabs  # type: ignore
    _EL_OK = True
except ImportError:
    _EL_OK = False

import config as _cfg


# ── Cache LRU ─────────────────────────────────────────────────────────────
_CACHE: OrderedDict[str, bytes] = OrderedDict()
_CACHE_MAX = 32


def _cache_get(key: str) -> Optional[bytes]:
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    return None


def _cache_put(key: str, val: bytes) -> None:
    if not val:
        return
    _CACHE[key] = val
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)


# ── Circuit breaker ────────────────────────────────────────────────────────
_DISABLED_UNTIL_TS = 0.0
_DISABLED_REASON = ""
_LAST_SKIP_LOG_TS = 0.0


def _is_temporarily_disabled() -> bool:
    return time.time() < _DISABLED_UNTIL_TS


def _disable_for(seconds: float, reason: str) -> None:
    global _DISABLED_UNTIL_TS, _DISABLED_REASON
    _DISABLED_UNTIL_TS = max(_DISABLED_UNTIL_TS, time.time() + max(0.0, seconds))
    _DISABLED_REASON = reason


def _maybe_log_skip() -> None:
    global _LAST_SKIP_LOG_TS
    now = time.time()
    if now - _LAST_SKIP_LOG_TS < 30.0:
        return
    _LAST_SKIP_LOG_TS = now
    restante = max(0, int(_DISABLED_UNTIL_TS - now))
    print(f"[EL-TTS] temporariamente desativado ({_DISABLED_REASON}) por ~{restante}s.")


def _retry_seconds_from_error(msg: str) -> float:
    m = re.search(r"retry.{0,10}([0-9]+(?:\.[0-9]+)?)\s*s", msg, flags=re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            pass
    return 60.0


# ── API pública ────────────────────────────────────────────────────────────

def _pool():
    """Lazy import do pool (evita ciclo em testes isolados)."""
    try:
        from core.api_key_pool import get_pool
        return get_pool("elevenlabs")
    except Exception:
        return None


def disponivel() -> bool:
    """True se SDK instalado E pelo menos uma chave disponível no pool."""
    if not _EL_OK:
        return False
    p = _pool()
    if p and p.count() > 0:
        return p.has_any()
    # Fallback: legado direto do config
    key = (getattr(_cfg, "ELEVENLABS_API_KEY", "") or "").strip()
    return bool(key)


def gerar_mp3(texto: str, voice_id: Optional[str] = None) -> bytes:
    """
    Gera MP3 a partir de `texto` usando ElevenLabs.
    Retorna bytes MP3 ou b"" em caso de falha.

    Faz rotação automática entre chaves do pool em caso de 401/429.
    Tenta no máximo N tentativas (N = número de chaves no pool).
    """
    if not _EL_OK:
        return b""

    if _is_temporarily_disabled():
        _maybe_log_skip()
        return b""

    texto = (texto or "").strip()
    if not texto:
        return b""

    vid = voice_id or getattr(_cfg, "ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")  # Adam
    model = getattr(_cfg, "ELEVENLABS_MODEL", "eleven_multilingual_v2")

    cache_key = f"{vid}::{texto}"
    hit = _cache_get(cache_key)
    if hit:
        return hit

    pool = _pool()
    max_attempts = (pool.count() if pool and pool.count() > 0 else 1)

    # Se o pool existe mas TODAS as chaves estão esgotadas, reseta agora —
    # elas podem ter renovado a quota desde a última tentativa.
    if pool and pool.count() > 0 and not pool.has_any():
        print("[EL-TTS] pool sem chaves disponíveis — resetando para retestar todas...")
        pool.reset_all()

    last_err_msg = ""

    for attempt in range(max_attempts):
        # Obtém chave: do pool se disponível, senão fallback legado
        if pool and pool.count() > 0:
            api_key = pool.get_active()
        else:
            api_key = (getattr(_cfg, "ELEVENLABS_API_KEY", "") or "").strip()

        if not api_key:
            break

        try:
            client = ElevenLabs(api_key=api_key)
            audio_iter = client.text_to_speech.convert(
                voice_id=vid,
                text=texto,
                model_id=model,
                output_format="mp3_44100_128",
            )
            chunks = [c for c in audio_iter if c]
            mp3 = b"".join(chunks)
            if len(mp3) < 100:
                print("[EL-TTS] resposta vazia ou inválida.")
                return b""
            _cache_put(cache_key, mp3)
            print(f"[EL-TTS] OK — voice={vid} {len(mp3)} bytes MP3 (tentativa {attempt+1}/{max_attempts})")
            return mp3
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            last_err_msg = msg
            msg_low = msg.lower()
            is_401 = "401" in msg_low or "unauthorized" in msg_low or "invalid api" in msg_low
            is_429 = "429" in msg_low or "quota" in msg_low or "rate" in msg_low
            # Atividade suspeita detectada → desabilita ESSA chave pelo resto da sessão
            is_unusual = "detected_unusual_activity" in msg_low or "unusual activity" in msg_low
            if is_unusual and pool and pool.count() > 1:
                pool.mark_failed("unusual_activity", msg=msg)
                print("[EL-TTS] atividade suspeita — chave desabilitada permanentemente nesta sessão.")
                continue
            if pool and pool.count() > 1 and (is_401 or is_429):
                # Marca essa chave como esgotada e tenta a próxima
                reason = "401" if is_401 else "429"
                pool.mark_failed(reason, msg=msg)
                print(f"[EL-TTS] chave esgotada ({reason}) — tentando próxima...")
                continue
            # Sem rotação possível: aciona circuit breaker e desiste
            if is_unusual:
                _disable_for(7200.0, "UNUSUAL_ACTIVITY")  # 2h
            elif is_401:
                _disable_for(3600.0, "UNAUTHORIZED")
            elif is_429:
                _disable_for(_retry_seconds_from_error(msg), "RATE_LIMITED")
            print(f"[EL-TTS] falha: {msg}")
            return b""

    if last_err_msg:
        print(f"[EL-TTS] todas as chaves do pool esgotadas. Último erro: {last_err_msg}")
        # Ativa circuit breaker por 1 hora — não tenta mais até que expire.
        # Assim evita spam de 401 a cada chamada TTS.
        _disable_for(3600.0, "ALL_KEYS_EXHAUSTED")
        print("[EL-TTS] ElevenLabs desabilitado por 1h (todas as chaves esgotadas). Edge TTS ativo.")
    return b""

