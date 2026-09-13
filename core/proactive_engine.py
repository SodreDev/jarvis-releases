"""
Proactive Engine — decide quando o JARVIS deve falar SEM ter sido chamado.

Política conservadora (o usuário disse: "fale alguma coisa de vez enquando" —
ênfase em "de vez em quando"):

Gatilhos possíveis:
    - utterance com intent_target="jarvis_question_implicit" e confidence ≥ 0.6
    - presença muda para "present" depois de >5min "away" (saudação leve)
    - frustração detectada (palavrão repetido, "não tá funcionando")

Inibidores:
    - cooldown global (default 300s)
    - quiet hours (default 22h-9h)
    - presence == "away"
    - game_mode ativo
    - usuário falou "fica quieto" ou "modo silencioso"
    - jarvis está falando agora (tts.started sem tts.ended)

A engine NÃO fala diretamente — ela emite uma sugestão via callback que o
main.py registra (geralmente apontando para `jarvis._fala`).
"""
from __future__ import annotations

import random
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from core import event_bus

import config as _cfg


_LAST_PROACTIVE_TS = 0.0
_SILENCED_UNTIL = 0.0
_TTS_PLAYING = False
_GAME_ACTIVE = False
_ENABLED = False
_SPEAK_CB: Optional[Callable[[str], None]] = None
# Callback que gera uma resposta curta: (pergunta, contexto_str) -> str
_GENERATE_CB: Optional[Callable[[str, str], str]] = None
_LOCK = threading.RLock()

# Probabilidade de responder a uma pergunta implícita (0.0-1.0).
# Garante que não responde TODA pergunta ambiente — só "de vez em quando".
_RESPOND_CHANCE = 0.50

# Probabilidade de comentar espontaneamente uma conversa entre humanos.
# Muito baixa para não interromper — só de vez em quando.
_CONV_REACT_CHANCE = 0.10

# Modo conversa: se o proativo acabou de falar, aceita continuações em <= 45s
# com cooldown muito menor (15s) para não cortar a troca.
_IN_CONVERSATION = False
_CONVO_LAST_TS = 0.0
_CONVO_WINDOW_S = 45.0        # janela pós-fala que considera "conversa ativa"
_CONVO_COOLDOWN_S = 15.0      # cooldown curto dentro da conversa


def set_speak_callback(cb: Callable[[str], None]) -> None:
    global _SPEAK_CB
    _SPEAK_CB = cb


def set_generate_callback(cb: Callable[[str, str], str]) -> None:
    """Registra callback que gera resposta curta: (pergunta, contexto) -> str."""
    global _GENERATE_CB
    _GENERATE_CB = cb


def enable() -> str:
    global _ENABLED, _LAST_PROACTIVE_TS, _SILENCED_UNTIL
    _ENABLED = True
    # Janela inicial de silêncio para não falar logo no boot.
    _LAST_PROACTIVE_TS = time.time()
    _SILENCED_UNTIL = max(_SILENCED_UNTIL, time.time() + 60.0)
    _wire_subscriptions()
    return "Modo proativo ligado, Senhor. Vou intervir só quando fizer sentido."


def disable() -> str:
    global _ENABLED
    _ENABLED = False
    return "Modo proativo desligado, Senhor."


def silence_for(seconds: float) -> str:
    global _SILENCED_UNTIL
    _SILENCED_UNTIL = time.time() + max(0.0, seconds)
    mins = int(seconds // 60) or 1
    return f"Entendido, Senhor. Ficarei em silêncio por {mins} minuto(s)."


def is_quiet_hours() -> bool:
    qh = getattr(_cfg, "AMBIENT_QUIET_HOURS", (22, 9))
    try:
        ini, fim = int(qh[0]), int(qh[1])
    except Exception:
        return False
    h = datetime.now().hour
    if ini == fim:
        return False
    if ini < fim:
        return ini <= h < fim
    # cruza meia-noite (22→9)
    return h >= ini or h < fim


def _can_speak() -> bool:
    if not _ENABLED:
        return False
    now = time.time()
    if now < _SILENCED_UNTIL:
        return False
    if _GAME_ACTIVE:
        return False
    if _TTS_PLAYING:
        return False
    if is_quiet_hours():
        return False
    # Dentro da janela de conversa ativa: cooldown curto
    if _IN_CONVERSATION and (now - _CONVO_LAST_TS) < _CONVO_WINDOW_S:
        return (now - _LAST_PROACTIVE_TS) >= _CONVO_COOLDOWN_S
    # Fora de conversa: cooldown normal
    cd = float(getattr(_cfg, "AMBIENT_PROACTIVE_COOLDOWN_S", 300))
    return (now - _LAST_PROACTIVE_TS) >= cd


def _maybe_speak(text: str) -> bool:
    global _LAST_PROACTIVE_TS
    if not _can_speak():
        return False
    if not _SPEAK_CB:
        return False
    try:
        _SPEAK_CB(text)
        _LAST_PROACTIVE_TS = time.time()
        return True
    except Exception as e:
        print(f"[Proactive] speak callback falhou: {e}")
        return False


# ── Subscribers do event bus ───────────────────────────────────────────────


_LAST_MEDIA_REACT_TS = 0.0   # cooldown separado para reações a mídia
_MEDIA_REACT_COOLDOWN_S = 90.0  # mínimo entre reações a áudio do sistema


def _on_utterance(payload: dict) -> None:
    if not _ENABLED:
        return
    target = payload.get("intent_target", "")
    conf = float(payload.get("intent_confidence", 0.0))
    text = payload.get("text", "")
    speaker = payload.get("speaker_id", "")

    # ── Reação a áudio do sistema (mídia) ──────────────────────────────────
    if target == "ambient_media":
        _maybe_react_to_media(text)
        return

    if target == "jarvis_question_implicit" and conf >= 0.60:
        now = time.time()
        em_conversa = _IN_CONVERSATION and (now - _CONVO_LAST_TS) < _CONVO_WINDOW_S
        # Fora de conversa: sorteia 50%. Dentro de conversa ativa: sempre responde.
        if not em_conversa and random.random() > _RESPOND_CHANCE:
            return
        if not _can_speak():
            return
        if _GENERATE_CB:
            threading.Thread(
                target=_responder_async,
                args=(text,),
                daemon=True,
                name="proactive-gen",
            ).start()
        else:
            _maybe_speak("Posso ajudar com isso, Senhor.")

    elif target == "conversation_2p" and conf >= 0.55:
        # Ocasionalmente JARVIS comenta a conversa ao redor — bem raramente.
        if random.random() < _CONV_REACT_CHANCE and _can_speak() and _GENERATE_CB:
            threading.Thread(
                target=_responder_async,
                args=(f"[conversa ao redor] {text}",),
                daemon=True,
                name="proactive-conv",
            ).start()


def _maybe_react_to_media(texto: str) -> None:
    """Reage espontaneamente ao conteúdo do áudio do sistema (vídeos, músicas)."""
    global _LAST_MEDIA_REACT_TS
    if not _GENERATE_CB or not _SPEAK_CB:
        return
    if not _can_speak():
        return
    react_chance = float(getattr(_cfg, "SYSTEM_AUDIO_REACT_CHANCE", 0.12))
    if random.random() > react_chance:
        return
    now = time.time()
    if (now - _LAST_MEDIA_REACT_TS) < _MEDIA_REACT_COOLDOWN_S:
        return
    _LAST_MEDIA_REACT_TS = now
    threading.Thread(
        target=_reagir_midia_async,
        args=(texto,),
        daemon=True,
        name="proactive-media",
    ).start()


def _responder_async(pergunta: str) -> None:
    """Gera e fala resposta curta em thread separada."""
    global _LAST_PROACTIVE_TS, _IN_CONVERSATION, _CONVO_LAST_TS
    try:
        from core.ambient_listener import context_text
        ctx = context_text(n=8, max_chars=600)
    except Exception:
        ctx = ""
    try:
        resposta = _GENERATE_CB(pergunta, ctx)  # type: ignore[misc]
        if resposta:
            now = time.time()
            _LAST_PROACTIVE_TS = now
            _IN_CONVERSATION = True
            _CONVO_LAST_TS = now
            if _SPEAK_CB:
                _SPEAK_CB(resposta)
    except Exception as e:
        print(f"[Proactive] Geração falhou: {e}")


def _reagir_midia_async(conteudo: str) -> None:
    """Reage ao áudio do sistema (vídeos, músicas) com comentário breve."""
    global _LAST_PROACTIVE_TS, _IN_CONVERSATION, _CONVO_LAST_TS
    if not _GENERATE_CB or not _SPEAK_CB:
        return
    try:
        from core.ambient_listener import context_text
        ctx = context_text(n=6, max_chars=500)
    except Exception:
        ctx = ""
    prompt_midia = f"[áudio do sistema] {conteudo}"
    try:
        resposta = _GENERATE_CB(prompt_midia, ctx)  # type: ignore[misc]
        if resposta:
            now = time.time()
            _LAST_PROACTIVE_TS = now
            _IN_CONVERSATION = True
            _CONVO_LAST_TS = now
            if _SPEAK_CB:
                _SPEAK_CB(resposta)
    except Exception as e:
        print(f"[Proactive] Reação a mídia falhou: {e}")


def _on_presence(payload: dict) -> None:
    if not _ENABLED:
        return
    novo = payload.get("state")
    antigo = payload.get("previous")
    if antigo == "away" and novo == "present":
        # Saudação leve quando o usuário volta — respeita cooldown
        _maybe_speak("Bom te ver de volta, Senhor.")


def _on_tts_started(_payload: dict) -> None:
    global _TTS_PLAYING
    _TTS_PLAYING = True


def _on_tts_ended(_payload: dict) -> None:
    global _TTS_PLAYING
    _TTS_PLAYING = False


def _on_game_mode(payload: dict) -> None:
    global _GAME_ACTIVE
    _GAME_ACTIVE = bool(payload.get("active", False))


_WIRED = False


def _wire_subscriptions() -> None:
    global _WIRED
    with _LOCK:
        if _WIRED:
            return
        event_bus.subscribe("ambient.utterance",  _on_utterance)
        event_bus.subscribe("presence.changed",   _on_presence)
        event_bus.subscribe("tts.started",        _on_tts_started)
        event_bus.subscribe("tts.ended",          _on_tts_ended)
        event_bus.subscribe("game_mode.changed",  _on_game_mode)
        _WIRED = True
