"""
Mode classifier — gerencia os modos de interação e quais módulos estão ativos.

Modos:
    full        — desktop + canvas2d + workspace3d
    desktop     — somente desktop control
    desktop_2d  — desktop + canvas 2D
    design3d    — somente workspace 3D
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from gesture_interface.config import DEFAULT_MODE, MODES


@dataclass
class ModeState:
    """Estado de um modo: quais módulos estão ativos."""
    desktop: bool = False
    canvas2d: bool = False
    workspace3d: bool = False


class ModeClassifier:
    """
    Gerencia o modo ativo de interação e notifica subscribers quando ele muda.
    Thread-safe.
    """

    def __init__(self) -> None:
        self._current: str = DEFAULT_MODE
        self._lock = threading.Lock()
        self._listeners: list[Callable[[str, ModeState], None]] = []

    @property
    def current_mode(self) -> str:
        with self._lock:
            return self._current

    @property
    def state(self) -> ModeState:
        with self._lock:
            cfg = MODES.get(self._current, MODES[DEFAULT_MODE])
            return ModeState(**cfg)

    def available_modes(self) -> list[str]:
        return list(MODES.keys())

    def on_change(self, callback: Callable[[str, ModeState], None]) -> None:
        self._listeners.append(callback)

    def set_mode(self, mode_name: str) -> ModeState:
        """
        Troca para o modo especificado. Emite eventos para listeners.
        Levanta ValueError se o modo não existir.
        """
        if mode_name not in MODES:
            raise ValueError(f"Modo desconhecido: {mode_name!r}. Válidos: {list(MODES)}")

        with self._lock:
            self._current = mode_name
            cfg = MODES[mode_name]
            st = ModeState(**cfg)

        for cb in self._listeners:
            try:
                cb(mode_name, st)
            except Exception:
                pass

        return st

    def is_module_active(self, module: str) -> bool:
        """Verifica se um módulo específico está ativo no modo corrente."""
        st = self.state
        return getattr(st, module, False)
