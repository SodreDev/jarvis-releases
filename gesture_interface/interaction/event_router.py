"""
Event router — distribui GestureEvents apenas para os módulos ativos.

Cada módulo consumidor registra um handler. O router verifica o modo
corrente antes de encaminhar o evento.
"""
from __future__ import annotations

import threading
from typing import Callable, Protocol

from gesture_interface.gesture_engine.recognizer import GestureEvent, GestureType
from gesture_interface.interaction.mode_classifier import ModeClassifier


class GestureHandler(Protocol):
    """Protocolo que qualquer módulo consumidor de gestos deve satisfazer."""
    def handle_gesture(self, event: GestureEvent) -> None: ...


class EventRouter:
    """
    Recebe GestureEvents do reconhecedor e os encaminha somente para os módulos
    cujo módulo correspondente esteja ativo no ModeClassifier.
    """

    def __init__(self, classifier: ModeClassifier) -> None:
        self._classifier = classifier
        self._handlers: dict[str, GestureHandler] = {}
        self._global_listeners: list[Callable[[GestureEvent], None]] = []
        self._lock = threading.Lock()

    def register(self, module_name: str, handler: GestureHandler) -> None:
        """
        Registra um handler para um módulo.
        module_name deve ser 'desktop', 'canvas2d' ou 'workspace3d'.
        """
        with self._lock:
            self._handlers[module_name] = handler

    def unregister(self, module_name: str) -> None:
        with self._lock:
            self._handlers.pop(module_name, None)

    def add_global_listener(self, cb: Callable[[GestureEvent], None]) -> None:
        """Listener que recebe TODOS os eventos independente do modo."""
        self._global_listeners.append(cb)

    def route(self, event: GestureEvent) -> None:
        """Encaminha o evento para handlers dos módulos ativos."""
        state = self._classifier.state

        with self._lock:
            handlers_snap = dict(self._handlers)

        for module_name, handler in handlers_snap.items():
            if getattr(state, module_name, False):
                try:
                    handler.handle_gesture(event)
                except Exception:
                    pass

        for cb in self._global_listeners:
            try:
                cb(event)
            except Exception:
                pass

    def route_many(self, events: list[GestureEvent]) -> None:
        """Encaminha uma lista de eventos."""
        for ev in events:
            self.route(ev)
