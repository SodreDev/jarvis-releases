"""
Gemini TTS engine — wrapper opt-in para o modelo `gemini-*-tts`.

Características:
- Stateless: cada chamada gera um novo cliente (a `google-genai` é leve).
- Retorna **WAV bytes** (16-bit PCM, mono, 24 kHz) prontos para ffplay.
- Não levanta exceção; em qualquer falha retorna `b""` (caller faz fallback).
- Cache opcional em memória (LRU pequeno) para falas repetidas como
  "Sim, Senhor." ou "Pronto, Senhor."

Uso:
    from VozIa.gemini_tts import gerar_wav, disponivel
    if disponivel():
        wav = gerar_wav("Olá, Senhor.")
"""
from __future__ import annotations

import io
import re
import struct
import time
import wave
from collections import OrderedDict
from typing import Optional

try:
    from google import genai          # type: ignore
    from google.genai import types    # type: ignore
    _GENAI_OK = True
except Exception:
    _GENAI_OK = False

import config as _cfg


# ── Cache LRU minúsculo para frases repetidas ─────────────────────────────
_CACHE: OrderedDict[str, bytes] = OrderedDict()
_CACHE_MAX = 32

# ── Circuit breaker para evitar spam de 403/429 ───────────────────────────
_DISABLED_UNTIL_TS = 0.0
_DISABLED_REASON = ""
_LAST_SKIP_LOG_TS = 0.0


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
    print(f"[GEMINI-TTS] temporariamente desativado ({_DISABLED_REASON}) por ~{restante}s.")


def _retry_seconds_from_error(msg: str) -> float:
    # Exemplos comuns: "Please retry in 4.990334827s." ou retryDelay='4s'
    m = re.search(r"retry in\s+([0-9]+(?:\.[0-9]+)?)s", msg, flags=re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return 5.0
    m = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?([0-9]+)s", msg, flags=re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return 5.0
    return 5.0


# ── API pública ────────────────────────────────────────────────────────────


def disponivel() -> bool:
    """True se o módulo `google-genai` está instalado E há chave configurada."""
    if not _GENAI_OK:
        return False
    key = (getattr(_cfg, "GEMINI_TTS_API_KEY", "") or "").strip()
    return bool(key)


def _pcm_to_wav(pcm: bytes, rate: int = 24000, channels: int = 1, sampwidth: int = 2) -> bytes:
    """Empacota PCM bruto em container WAV."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def gerar_wav(texto: str, voz: Optional[str] = None) -> bytes:
    """
    Gera áudio a partir de `texto` usando Gemini TTS.

    Retorna WAV bytes (24 kHz, mono, 16-bit PCM) ou `b""` em caso de falha.
    Em caso de falha, o caller deve cair para Edge TTS (ou Kokoro).
    """
    if not disponivel():
        return b""

    if _is_temporarily_disabled():
        _maybe_log_skip()
        return b""

    texto = (texto or "").strip()
    if not texto:
        return b""

    cache_key = f"{voz or ''}::{texto}"
    hit = _cache_get(cache_key)
    if hit:
        return hit

    voz_nome = voz or getattr(_cfg, "GEMINI_TTS_VOICE", "Charon")
    modelo   = getattr(_cfg, "GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
    api_key  = (getattr(_cfg, "GEMINI_TTS_API_KEY", "") or "").strip()

    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=modelo,
            contents=texto,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voz_nome,
                        )
                    )
                ),
            ),
        )
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        msg_low = msg.lower()

        # 403: projeto/chave sem permissão para TTS -> pausa longa.
        if "permission_denied" in msg_low or "403" in msg_low:
            _disable_for(3600.0, "PERMISSION_DENIED")
        # 429/quota: usa retry delay quando disponível.
        elif "resource_exhausted" in msg_low or "quota" in msg_low or "429" in msg_low:
            _disable_for(_retry_seconds_from_error(msg), "RESOURCE_EXHAUSTED")

        print(f"[GEMINI-TTS] falha na requisição: {msg}")
        return b""

    # Extrai PCM bruto da resposta
    try:
        pcm = resp.candidates[0].content.parts[0].inline_data.data
        if not isinstance(pcm, (bytes, bytearray)) or len(pcm) < 100:
            print("[GEMINI-TTS] resposta vazia ou inválida.")
            return b""
    except Exception as e:
        print(f"[GEMINI-TTS] parse falhou: {e}")
        return b""

    wav = _pcm_to_wav(bytes(pcm), rate=24000, channels=1, sampwidth=2)
    _cache_put(cache_key, wav)
    print(f"[GEMINI-TTS] OK — voz={voz_nome} {len(wav)} bytes WAV")
    return wav
