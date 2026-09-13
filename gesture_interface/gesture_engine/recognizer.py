"""
Reconhecimento de gestos — coordenação de mãos (v3, sem cursor).

Gestos de uma mão:
    SWIPE_LEFT / SWIPE_RIGHT        — trocar desktop (Win+Ctrl+←→)
    WINDOW_SWITCHER_OPEN            — abre seletor Win+Tab
    WINDOW_SWITCHER_NAV_RIGHT/LEFT/DOWN — navegar no seletor
    WINDOW_SWITCHER_CONFIRM         — confirmar seleção
    WINDOW_SWITCHER_CANCEL          — cancelar seletor
    MINIMIZE_WINDOW                 — minimizar janela (flip uma mão)

Gestos de duas mãos:
    MINIMIZE_ALL                    — minimizar tudo (flip ambas as mãos)
    ALT_F4                          — fechar app (punho bate na palma aberta)
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable

import numpy as np

from gesture_interface.config import (
    ALT_F4_CONFIRM_FRAMES,
    ALT_F4_PROXIMITY_THRESHOLD,
    BOTH_FLIP_WINDOW,
    GESTURE_GLOBAL_COOLDOWN,
    SWIPE_COOLDOWN,
    SWIPE_MIN_FRAMES,
    SWIPE_MIN_SPEED,
)
from gesture_interface.gesture_engine.gesture_classifier import (
    ClassifiedGesture,
    GestureClassifier,
)
from gesture_interface.gesture_engine.tracker import HandData


class GestureType(Enum):
    NONE = auto()
    # ── Desktop navigation ───────────────────────────────────────────────
    SWIPE_LEFT = auto()                     # Win+Ctrl+← (trocar desktop)
    SWIPE_RIGHT = auto()                    # Win+Ctrl+→
    # ── Window switcher ──────────────────────────────────────────────────
    WINDOW_SWITCHER_OPEN = auto()           # abre Win+Tab
    WINDOW_SWITCHER_NAV_RIGHT = auto()      # seta →
    WINDOW_SWITCHER_NAV_LEFT = auto()       # seta ←
    WINDOW_SWITCHER_NAV_DOWN = auto()       # seta ↓
    WINDOW_SWITCHER_CONFIRM = auto()        # Enter
    WINDOW_SWITCHER_CANCEL = auto()         # Esc
    # ── Window management ────────────────────────────────────────────────
    MINIMIZE_WINDOW = auto()                # minimizar janela ativa
    MINIMIZE_ALL = auto()                   # minimizar tudo (Win+D)
    ALT_F4 = auto()                         # fechar janela ativa


# ClassifiedGesture → GestureType (gestos por mão única; PALM_FLIP tratado à parte)
_CLASSIFIED_TO_TYPE: dict[ClassifiedGesture, GestureType] = {
    ClassifiedGesture.WINDOW_SWITCHER_TRIGGER:   GestureType.WINDOW_SWITCHER_OPEN,
    ClassifiedGesture.WINDOW_SWITCHER_NAV_RIGHT: GestureType.WINDOW_SWITCHER_NAV_RIGHT,
    ClassifiedGesture.WINDOW_SWITCHER_NAV_LEFT:  GestureType.WINDOW_SWITCHER_NAV_LEFT,
    ClassifiedGesture.WINDOW_SWITCHER_NAV_DOWN:  GestureType.WINDOW_SWITCHER_NAV_DOWN,
    ClassifiedGesture.WINDOW_SWITCHER_CONFIRM:   GestureType.WINDOW_SWITCHER_CONFIRM,
    ClassifiedGesture.WINDOW_SWITCHER_CANCEL:    GestureType.WINDOW_SWITCHER_CANCEL,
    # PALM_FLIP não está neste dict — precisa de verificação de duas mãos
}


@dataclass
class GestureEvent:
    """Evento de gesto reconhecido."""
    gesture: GestureType
    hand: str                               # "Left" | "Right" | "Both"
    position: tuple[float, float, float]    # (x, y, z) normalizado
    velocity: tuple[float, float] = (0.0, 0.0)
    confidence: float = 1.0
    timestamp: float = 0.0


_HistoryEntry = tuple[float, float, float, float]  # (x, y, z, time)


class GestureRecognizer:
    """
    Analisa sequências de HandData e emite GestureEvents.

    Responsabilidades:
      - Delegar classificação por mão ao GestureClassifier
      - Detectar swipe de desktop via histórico de posições (estado IDLE)
      - Coordenar gestos de duas mãos: MINIMIZE_ALL e ALT_F4
    """

    def __init__(self, on_gesture: Callable[[GestureEvent], None] | None = None):
        self._on_gesture = on_gesture
        self._history: dict[str, deque[_HistoryEntry]] = {}
        self._last_gesture: dict[str, GestureType] = {}
        self._last_gesture_time: dict[str, float] = {}
        self._cooldown = GESTURE_GLOBAL_COOLDOWN
        self._last_swipe_time: float = 0.0

        # Classificadores por mão
        self._classifiers: dict[str, GestureClassifier] = {}
        self._active_hands: set[str] = set()

        # ── Coordenação de duas mãos ──────────────────────────────────
        # Palm flip: registrar por mão para detectar both-flip
        self._last_flip_time: dict[str, float] = {}
        # Alt+F4: punho bate na palma
        self._alt_f4_count: int = 0
        self._last_alt_f4_time: float = 0.0

    def set_callback(self, cb: Callable[[GestureEvent], None]) -> None:
        self._on_gesture = cb

    @property
    def in_mouse_mode(self) -> bool:
        """Compatibilidade — sempre False neste redesign."""
        return False

    @property
    def confirmed_poses(self) -> dict[str, str]:
        """Estado atual dos classificadores por mão (para a UI)."""
        return {h: clf.state.name for h, clf in self._classifiers.items()}

    # ── Entry point ──────────────────────────────────────────────────────

    def process(self, hands: list[HandData]) -> list[GestureEvent]:
        events: list[GestureEvent] = []
        now = time.perf_counter()
        seen_hands: set[str] = set()

        for hand in hands:
            h_key = hand.handedness
            seen_hands.add(h_key)

            if h_key not in self._classifiers:
                self._classifiers[h_key] = GestureClassifier()
                self._history[h_key] = deque(maxlen=60)

            # Histórico de posições da palma (para swipe de desktop)
            pc = hand.palm_center
            self._history[h_key].append((float(pc[0]), float(pc[1]), float(pc[2]), now))

            # Classificação por mão
            cr = self._classifiers[h_key].process(hand)
            pos3: tuple[float, float, float] = cr.position if any(cr.position) else tuple(hand.palm_center.tolist())  # type: ignore[assignment]

            # ── PALM_FLIP: verificar two-hand antes de emitir ─────────
            if cr.gesture == ClassifiedGesture.PALM_FLIP:
                other_key = "Left" if h_key == "Right" else "Right"
                other_flip_t = self._last_flip_time.get(other_key, 0.0)
                if now - other_flip_t < BOTH_FLIP_WINDOW:
                    # Ambas as mãos viraram → MINIMIZE_ALL
                    self._last_flip_time.pop(other_key, None)
                    self._last_flip_time.pop(h_key, None)
                    self._emit(
                        GestureEvent(GestureType.MINIMIZE_ALL, "Both", pos3, timestamp=now),
                        events, now,
                    )
                else:
                    # Apenas uma mão — registrar e emitir MINIMIZE_WINDOW
                    self._last_flip_time[h_key] = now
                    self._emit(
                        GestureEvent(GestureType.MINIMIZE_WINDOW, h_key, pos3, timestamp=now),
                        events, now,
                    )
                continue

            # ── Outros gestos do classificador ────────────────────────
            gtype = _CLASSIFIED_TO_TYPE.get(cr.gesture)
            if gtype is not None:
                self._emit(GestureEvent(gtype, h_key, pos3, timestamp=now), events, now)
                continue

            # ── Swipe de desktop (apenas em IDLE sem supressão) ───────
            clf = self._classifiers[h_key]
            if not clf.is_gesture_suppressed:
                swipe = self._detect_swipe(h_key, now)
                if swipe:
                    self._emit(swipe, events, now)

        # Reset classificadores de mãos que desapareceram
        for h_key in self._active_hands - seen_hands:
            if h_key in self._classifiers:
                self._classifiers[h_key].reset()
            self._history.pop(h_key, None)
        self._active_hands = seen_hands

        # ── Alt+F4 (punho bate na palma — duas mãos) ─────────────────
        if len(hands) == 2:
            self._check_alt_f4(hands[0], hands[1], events, now)

        return events

    def _emit(self, ev: GestureEvent, events: list, now: float) -> None:
        """Aplica cooldown, adiciona ao buffer e aciona callback."""
        h_key = ev.hand
        if not self._can_emit(h_key, ev.gesture, now):
            return
        events.append(ev)
        self._last_gesture[h_key] = ev.gesture
        self._last_gesture_time[h_key] = now
        if self._on_gesture:
            try:
                self._on_gesture(ev)
            except Exception:
                pass

    # ── Swipe de desktop ─────────────────────────────────────────────────

    def _detect_swipe(self, h_key: str, now: float) -> GestureEvent | None:
        """Detecta swipe horizontal rápido da palma → troca de desktop."""
        if now - self._last_swipe_time < SWIPE_COOLDOWN:
            return None
        hist = self._history.get(h_key)
        if not hist or len(hist) < SWIPE_MIN_FRAMES + 1:
            return None

        recent = list(hist)[-(SWIPE_MIN_FRAMES + 1):]
        x0, y0, _, t0 = recent[0]
        x1, y1, _, t1 = recent[-1]
        dt = t1 - t0
        if dt < 1e-6:
            return None

        dx = x1 - x0
        dy = y1 - y0
        speed = math.sqrt(dx * dx + dy * dy) / dt

        if speed < SWIPE_MIN_SPEED:
            return None
        # Só swipe horizontal (troca de desktop)
        if abs(dx) <= abs(dy):
            return None

        vx, vy = dx / dt, dy / dt
        center = ((x0 + x1) / 2, (y0 + y1) / 2, 0.0)
        self._last_swipe_time = now
        gtype = GestureType.SWIPE_RIGHT if dx > 0 else GestureType.SWIPE_LEFT
        return GestureEvent(gtype, h_key, center, velocity=(vx, vy), timestamp=now)

    # ── Alt+F4 duas mãos ─────────────────────────────────────────────────

    def _check_alt_f4(
        self,
        hand_a: HandData,
        hand_b: HandData,
        events: list,
        now: float,
    ) -> None:
        """Punho de uma mão perto da palma aberta da outra → Alt+F4."""
        if now - self._last_alt_f4_time < 2.0:
            return

        clf_a = self._classifiers.get(hand_a.handedness)
        clf_b = self._classifiers.get(hand_b.handedness)
        if clf_a is None or clf_b is None:
            return

        pose_a = clf_a.current_pose
        pose_b = clf_b.current_pose

        is_strike = (
            (pose_a == "FIST" and pose_b == "OPEN")
            or (pose_a == "OPEN" and pose_b == "FIST")
        )
        dist = float(np.linalg.norm(hand_a.palm_center - hand_b.palm_center))

        if is_strike and dist < ALT_F4_PROXIMITY_THRESHOLD:
            self._alt_f4_count += 1
            if self._alt_f4_count >= ALT_F4_CONFIRM_FRAMES:
                self._alt_f4_count = 0
                self._last_alt_f4_time = now
                center: tuple[float, float, float] = tuple(  # type: ignore[assignment]
                    ((hand_a.palm_center + hand_b.palm_center) / 2).tolist()
                )
                self._emit(
                    GestureEvent(GestureType.ALT_F4, "Both", center, timestamp=now),
                    events, now,
                )
        else:
            self._alt_f4_count = 0  # hard-reset: exige confirmação contínua

    # ── Cooldown ─────────────────────────────────────────────────────────

    def _can_emit(self, h_key: str, g: GestureType, now: float) -> bool:
        # Eventos de navegação: cooldown muito curto (controlado pelo classificador)
        _NAV = {
            GestureType.WINDOW_SWITCHER_NAV_RIGHT,
            GestureType.WINDOW_SWITCHER_NAV_LEFT,
            GestureType.WINDOW_SWITCHER_NAV_DOWN,
        }
        if g in _NAV:
            return True
        last_t = self._last_gesture_time.get(h_key, 0.0)
        last_g = self._last_gesture.get(h_key)
        if g == last_g and (now - last_t) < self._cooldown:
            return False
        return True
