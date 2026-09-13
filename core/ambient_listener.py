"""
Ambient Listener — escuta tudo o que é dito ao mic e roteia.

DESIGN DE BAIXO CPU (importante: o usuário joga nesse PC):
    - NÃO abre stream de áudio próprio.
    - NÃO transcreve nada localmente (sem faster-whisper).
    - Reaproveita 100% as transcrições que o `_wake_word_loop` já produz.
    - Cada texto que chega ao bus em `ambient.utterance` é roteado pelo
      `utterance_router` e os interessados (proactive engine, presence,
      contexto multi-turno) reagem via subscribers.

A integração no main.py é uma única linha: depois de cada `_quick_transcribe`
bem-sucedido, publicar `ambient.utterance` no event bus se o módulo estiver
ligado. O wake loop continua decidindo se chama `_processar_texto`.

Também exporta um buffer rolante de utterances para fornecer contexto à IA
quando ela for falar proativamente.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

from core import event_bus

import config as _cfg


@dataclass
class Utterance:
    text: str
    ts: float
    speaker_id: str = "unknown"
    rms: float = 0.0
    intent_target: str = ""        # preenchido pelo router
    intent_confidence: float = 0.0


_BUFFER: Deque[Utterance] = deque(maxlen=200)
_LOCK = threading.RLock()
_ENABLED = False
_GAME_PAUSED = False               # pausa automática durante game mode


# ── API ────────────────────────────────────────────────────────────────────


def is_enabled() -> bool:
    return _ENABLED and not _GAME_PAUSED


def enable() -> str:
    global _ENABLED
    _ENABLED = True
    return "Modo ambiente ligado, Senhor. Vou acompanhar o que for dito."


def disable() -> str:
    global _ENABLED
    _ENABLED = False
    return "Modo ambiente desligado, Senhor."


def pause_for_game(state: bool) -> None:
    """Chamado pelo game_mode_manager para suspender escuta durante jogos."""
    global _GAME_PAUSED
    _GAME_PAUSED = bool(state)
    if state:
        print("[AmbientListener] Pausado (Game Mode).")
    else:
        print("[AmbientListener] Retomado (Game Mode OFF).")


def feed_utterance(text: str, rms: float = 0.0,
                   speaker_id: str = "unknown") -> Optional[Utterance]:
    """
    Hook chamado pelo wake loop a cada transcrição. Adiciona ao buffer,
    chama o router e publica no event bus.

    Retorna o objeto `Utterance` (já com intent_target preenchido) ou None
    se o módulo está desligado.
    """
    if not is_enabled():
        return None
    text = (text or "").strip()
    if not text:
        return None

    utt = Utterance(text=text, ts=time.time(), speaker_id=speaker_id, rms=rms)
    with _LOCK:
        _BUFFER.append(utt)

    # Roteamento (módulo separado — pode ser desligado/trocado)
    # Áudio do sistema é classificado diretamente, sem passar pelo router.
    if speaker_id == "system":
        utt.intent_target = "ambient_media"
        utt.intent_confidence = 0.95
    else:
        try:
            from core.utterance_router import classify_target
            tgt, conf = classify_target(text)
            utt.intent_target = tgt
            utt.intent_confidence = conf
        except Exception as e:
            print(f"[AmbientListener] router falhou: {e}")
            utt.intent_target = "unknown"
            utt.intent_confidence = 0.0

    # Publica para subscribers (proactive engine, etc.)
    try:
        event_bus.publish("ambient.utterance", {
            "text": utt.text,
            "ts": utt.ts,
            "speaker_id": utt.speaker_id,
            "rms": utt.rms,
            "intent_target": utt.intent_target,
            "intent_confidence": utt.intent_confidence,
        })
    except Exception:
        pass

    # Persistência opcional
    try:
        if getattr(_cfg, "AMBIENT_PERSIST_TO_DISK", False):
            _persist(utt)
    except Exception:
        pass

    return utt


def get_recent(n: int = 20) -> list[Utterance]:
    with _LOCK:
        return list(_BUFFER)[-n:]


def clear_buffer() -> int:
    with _LOCK:
        count = len(_BUFFER)
        _BUFFER.clear()
    return count


def context_text(n: int = 10, max_chars: int = 1200) -> str:
    """Retorna últimas `n` utterances como string (p/ injetar em prompt).

    Sistema de labels:
        [usuário]  — fala captada pelo microfone
        [mídia]    — áudio do sistema (vídeo, música, chamada)
        [?]        — origem desconhecida
    """
    items = get_recent(n)
    out = []
    for u in items:
        if u.speaker_id == "system":
            label = "mídia"
        elif u.speaker_id in ("user", "unknown", ""):
            label = "usuário"
        else:
            label = u.speaker_id
        out.append(f"[{label}] {u.text}")
    s = "\n".join(out)
    if len(s) > max_chars:
        s = s[-max_chars:]
    return s


def _persist(utt: Utterance) -> None:
    import json
    import os
    from config import PATHS
    path = PATHS["historico"]
    rec = {
        "ts": utt.ts,
        "ambient": True,
        "speaker": utt.speaker_id,
        "intent": utt.intent_target,
        "conf": round(utt.intent_confidence, 3),
        "text": utt.text,
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
