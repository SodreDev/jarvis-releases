"""
Canvas 2D engine — gerencia estado do desenho gestual.

O rendering real é feito no frontend (canvas2d.html via JS).
Este módulo processa gestos e envia comandos para o frontend via API bridge.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from gesture_interface.config import CANVAS_DEFAULT_COLOR, CANVAS_DEFAULT_WIDTH, CANVAS_ERASER_RADIUS
from gesture_interface.gesture_engine.recognizer import GestureEvent, GestureType


@dataclass
class DrawCommand:
    """Comando de desenho enviado ao frontend."""
    action: str          # "start_stroke" | "continue_stroke" | "end_stroke" | "erase" | "clear" | "undo"
    x: float = 0.0
    y: float = 0.0
    color: str = ""
    width: float = 0.0
    radius: float = 0.0

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v or k == "action"}


class Canvas2DEngine:
    """
    Handler de gestos para o canvas de desenho 2D.

    Mapeamento de gestos:
        pinch           → iniciar traço
        pinch_hold      → continuar traço (desenhar)
        pinch_release   → finalizar traço
        fist            → borracha (apagar na posição)
        circle          → limpar tudo
        two_fingers     → undo último traço
        open_hand       → mudar cor (cicla entre cores)
    """

    PALETTE = ["#00e6ff", "#ff006e", "#00ff88", "#ffaa00", "#aa00ff", "#ffffff"]

    def __init__(self, on_command: Callable[[DrawCommand], None] | None = None) -> None:
        self._on_command = on_command
        self._current_color: str = CANVAS_DEFAULT_COLOR
        self._current_width: float = CANVAS_DEFAULT_WIDTH
        self._color_index: int = 0
        self._is_drawing: bool = False
        self._strokes: list[list[tuple[float, float]]] = []
        self._current_stroke: list[tuple[float, float]] = []
        self._last_color_change: float = 0.0

    def set_callback(self, cb: Callable[[DrawCommand], None]) -> None:
        self._on_command = cb

    def handle_gesture(self, event: GestureEvent) -> None:
        handler = {
            GestureType.PINCH: self._start_stroke,
            GestureType.PINCH_HOLD: self._continue_stroke,
            GestureType.PINCH_RELEASE: self._end_stroke,
            GestureType.FIST: self._erase,
            GestureType.CIRCLE: self._clear,
            GestureType.TWO_FINGERS: self._undo,
            GestureType.OPEN_HAND: self._cycle_color,
        }.get(event.gesture)

        if handler:
            handler(event)

    # ── drawing ──────────────────────────────────────────────────────────
    def _start_stroke(self, event: GestureEvent) -> None:
        self._is_drawing = True
        self._current_stroke = [(event.position[0], event.position[1])]
        self._emit(DrawCommand(
            action="start_stroke",
            x=event.position[0],
            y=event.position[1],
            color=self._current_color,
            width=self._current_width,
        ))

    def _continue_stroke(self, event: GestureEvent) -> None:
        if not self._is_drawing:
            return
        self._current_stroke.append((event.position[0], event.position[1]))
        self._emit(DrawCommand(
            action="continue_stroke",
            x=event.position[0],
            y=event.position[1],
        ))

    def _end_stroke(self, event: GestureEvent) -> None:
        if self._is_drawing:
            self._strokes.append(list(self._current_stroke))
            self._current_stroke.clear()
            self._is_drawing = False
            self._emit(DrawCommand(action="end_stroke"))

    # ── erase / clear / undo ─────────────────────────────────────────────
    def _erase(self, event: GestureEvent) -> None:
        self._emit(DrawCommand(
            action="erase",
            x=event.position[0],
            y=event.position[1],
            radius=CANVAS_ERASER_RADIUS,
        ))

    def _clear(self, event: GestureEvent) -> None:
        self._strokes.clear()
        self._emit(DrawCommand(action="clear"))

    def _undo(self, event: GestureEvent) -> None:
        if self._strokes:
            self._strokes.pop()
        self._emit(DrawCommand(action="undo"))

    # ── color ────────────────────────────────────────────────────────────
    def _cycle_color(self, event: GestureEvent) -> None:
        now = time.perf_counter()
        if now - self._last_color_change < 1.0:
            return
        self._last_color_change = now
        self._color_index = (self._color_index + 1) % len(self.PALETTE)
        self._current_color = self.PALETTE[self._color_index]

    # ── emit ─────────────────────────────────────────────────────────────
    def _emit(self, cmd: DrawCommand) -> None:
        if self._on_command:
            try:
                self._on_command(cmd)
            except Exception:
                pass

    # ── state ────────────────────────────────────────────────────────────
    @property
    def stroke_count(self) -> int:
        return len(self._strokes)

    @property
    def current_color(self) -> str:
        return self._current_color
