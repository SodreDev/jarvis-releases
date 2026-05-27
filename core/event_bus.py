"""
Event Bus — pub/sub mínimo, thread-safe, in-memory.

Permite que módulos (ambient listener, presence detector, proactive engine,
wake loop) se comuniquem sem acoplamento direto.

Eventos canônicos esperados:
    presence.changed     → {"state": "present"|"away"|"looking_away"}
    ambient.utterance    → {"text", "speaker_id", "ts", "rms"}
    ambient.intent       → {"target": "jarvis_command"|"conversation_2p"|...,
                            "text", "confidence"}
    wake.activated       → {"text"}
    tts.started          → {"text"}
    tts.ended            → {}
    game_mode.changed    → {"active": bool}

Uso:
    from core.event_bus import publish, subscribe
    subscribe("presence.changed", lambda payload: print(payload))
    publish("presence.changed", {"state": "away"})
"""
from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any, Callable

_LOCK = threading.RLock()
_SUBS: dict[str, list[Callable[[dict], None]]] = defaultdict(list)


def subscribe(topic: str, handler: Callable[[dict], None]) -> Callable[[], None]:
    """Registra `handler` para `topic`. Retorna função de unsubscribe."""
    with _LOCK:
        _SUBS[topic].append(handler)

    def _unsub() -> None:
        with _LOCK:
            try:
                _SUBS[topic].remove(handler)
            except ValueError:
                pass

    return _unsub


def publish(topic: str, payload: dict[str, Any] | None = None) -> None:
    """Publica `payload` em `topic`. Handlers rodam síncronos no thread do
    publisher — handlers pesados devem despachar para thread própria."""
    payload = payload or {}
    with _LOCK:
        handlers = list(_SUBS.get(topic, ()))
    for h in handlers:
        try:
            h(payload)
        except Exception as e:
            # Nunca propaga — logs só, p/ não derrubar o produtor
            print(f"[event_bus] handler de {topic!r} levantou {type(e).__name__}: {e}")


def clear(topic: str | None = None) -> None:
    """Remove todos os handlers de `topic` (ou todos os tópicos se None)."""
    with _LOCK:
        if topic is None:
            _SUBS.clear()
        else:
            _SUBS.pop(topic, None)
