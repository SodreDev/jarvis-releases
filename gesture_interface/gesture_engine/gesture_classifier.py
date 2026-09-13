"""
Classificador de gestos — máquina de estados por mão (v3, sem cursor).

Gestos detectados:
    WINDOW_SWITCHER_TRIGGER  — punho → mão aberta → abre Win+Tab
    WINDOW_SWITCHER_NAV_*    — swipe de mão no seletor (←→↓)
    WINDOW_SWITCHER_CONFIRM  — fechar punho no seletor → Enter
    WINDOW_SWITCHER_CANCEL   — timeout do seletor
    PALM_FLIP                — virar palma para longe e retornar → minimizar janela

Swipe de desktop (Win+Ctrl+←→) é detectado no GestureRecognizer
via histórico de posições da palma quando a mão está em estado IDLE.
"""
from __future__ import annotations

import time
from collections import deque
from enum import Enum, auto

import numpy as np

from gesture_interface.config import (
    FIST_CONFIRM_FRAMES,
    HOLD_JITTER_TOLERANCE,
    OPEN_CONFIRM_FRAMES,
    PALM_CONFIRM_FRAMES,
    PALM_FLIP_TIMEOUT,
    SWIPE_NAV_COOLDOWN,
    SWIPE_NAV_FRAMES,
    SWIPE_NAV_MIN_SPEED,
    WINSW_TIMEOUT,
)
from gesture_interface.gesture_engine.tracker import HandData


class _State(Enum):
    """Estado principal da máquina de estados."""
    IDLE = auto()
    WINDOW_SWITCHER = auto()   # Win+Tab aberto — navegando com mão


class ClassifiedGesture(Enum):
    """Gestos emitidos pelo classificador."""
    NONE = auto()
    WINDOW_SWITCHER_TRIGGER = auto()    # punho→aberta → abre seletor
    WINDOW_SWITCHER_NAV_RIGHT = auto()  # swipe direita no seletor
    WINDOW_SWITCHER_NAV_LEFT = auto()   # swipe esquerda no seletor
    WINDOW_SWITCHER_NAV_DOWN = auto()   # swipe baixo no seletor
    WINDOW_SWITCHER_CONFIRM = auto()    # punho no seletor → confirma
    WINDOW_SWITCHER_CANCEL = auto()     # timeout → cancel
    PALM_FLIP = auto()                  # virar palma → minimizar janela


class ClassifierResult:
    """Resultado de um frame de classificação."""
    __slots__ = ("gesture", "position", "hand")

    def __init__(
        self,
        gesture: ClassifiedGesture = ClassifiedGesture.NONE,
        position: tuple[float, float, float] = (0.0, 0.0, 0.0),
        hand: str = "Right",
    ):
        self.gesture = gesture
        self.position = position
        self.hand = hand


class GestureClassifier:
    """
    Máquina de estados por mão para reconhecimento de gestos discretos.

    Estados:
        IDLE             → Monitorando gestos (flip, trigger do switcher)
        WINDOW_SWITCHER  → Win+Tab aberto, navegando com movimentos de mão
    """

    def __init__(self) -> None:
        self._state: _State = _State.IDLE

        # ── Detecção de fist→open (trigger do seletor) ────────────────
        self._fist_count: int = 0       # frames consecutivos de punho
        self._open_count: int = 0       # frames consecutivos de mão aberta
        self._had_fist: bool = False    # punho confirmado — aguardando aberta
        self._fist_jitter: int = 0      # frames sem pose clara após had_fist

        # ── Window switcher ───────────────────────────────────────────
        self._switcher_start: float = 0.0
        self._nav_history: deque[tuple[float, float, float]] = deque(maxlen=30)
        self._last_nav_time: float = 0.0
        self._nav_fist_count: int = 0   # frames de punho para confirmar no switcher

        # ── Palm flip (minimizar) ─────────────────────────────────────
        self._palm_normal_count: int = 0
        self._palm_back_count: int = 0
        self._palm_flip_active: bool = False
        self._flip_start: float = 0.0
        self._flip_return_count: int = 0

        # ── Cooldowns ─────────────────────────────────────────────────
        self._winsw_cooldown_until: float = 0.0

        # ── Pose instantânea para coordenação dois-mãos ───────────────
        self._current_pose: str = "OTHER"

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def state(self) -> _State:
        return self._state

    @property
    def in_window_switcher(self) -> bool:
        return self._state == _State.WINDOW_SWITCHER

    @property
    def in_mouse_mode(self) -> bool:
        """Compatibilidade com código legado — sempre False neste redesign."""
        return False

    @property
    def is_gesture_suppressed(self) -> bool:
        """True quando esta mão está ocupada — swipe de desktop deve ser suprimido."""
        return (
            self._state != _State.IDLE
            or self._had_fist
            or self._palm_back_count > 0
            or self._palm_flip_active
        )

    @property
    def current_pose(self) -> str:
        """Pose instantânea: 'FIST' | 'OPEN' | 'OTHER'."""
        return self._current_pose

    @property
    def palm_is_flipped(self) -> bool:
        """True enquanto o dorso está virado (flip em andamento, não completo)."""
        return self._palm_flip_active

    # ── Entry point ─────────────────────────────────────────────────────

    def process(self, hand: HandData) -> ClassifierResult:
        """Processa um frame e retorna o gesto classificado."""
        now = time.perf_counter()
        pos3: tuple[float, float, float] = tuple(hand.palm_center.tolist())  # type: ignore[assignment]
        h_key = hand.handedness

        is_fist = self._is_fist(hand)
        is_open = self._is_open_hand(hand)

        if is_fist:
            self._current_pose = "FIST"
        elif is_open:
            self._current_pose = "OPEN"
        else:
            self._current_pose = "OTHER"

        if self._state == _State.IDLE:
            return self._process_idle(hand, now, pos3, h_key, is_fist, is_open)
        elif self._state == _State.WINDOW_SWITCHER:
            return self._process_window_switcher(hand, now, pos3, h_key, is_fist)

        return ClassifierResult(hand=h_key)

    # ── IDLE ────────────────────────────────────────────────────────────

    def _process_idle(
        self,
        hand: HandData,
        now: float,
        pos3: tuple,
        h_key: str,
        is_fist: bool,
        is_open: bool,
    ) -> ClassifierResult:
        # 1. Palm flip — prioridade máxima
        if self._check_palm_flip(hand, now):
            self._had_fist = False
            self._fist_count = 0
            self._open_count = 0
            self._fist_jitter = 0
            return ClassifierResult(ClassifiedGesture.PALM_FLIP, pos3, hand=h_key)

        # 2. Detecção fist→open para trigger do seletor de janelas
        if is_fist:
            self._fist_count += 1
            self._fist_jitter = 0
            self._open_count = 0
            if self._fist_count >= FIST_CONFIRM_FRAMES:
                self._had_fist = True

        elif self._had_fist:
            if is_open:
                self._open_count += 1
                if self._open_count >= OPEN_CONFIRM_FRAMES:
                    if now > self._winsw_cooldown_until:
                        self._had_fist = False
                        self._fist_count = 0
                        self._open_count = 0
                        self._fist_jitter = 0
                        self._state = _State.WINDOW_SWITCHER
                        self._switcher_start = now
                        self._nav_history.clear()
                        self._nav_fist_count = 0
                        return ClassifierResult(
                            ClassifiedGesture.WINDOW_SWITCHER_TRIGGER, pos3, hand=h_key
                        )
            else:
                self._open_count = 0
                self._fist_jitter += 1
                self._fist_count = max(0, self._fist_count - 2)
                if self._fist_jitter > HOLD_JITTER_TOLERANCE * 4:
                    self._had_fist = False
                    self._fist_count = 0
                    self._fist_jitter = 0
        else:
            if not is_fist:
                self._fist_count = max(0, self._fist_count - 1)
            self._open_count = 0
            self._fist_jitter = 0

        return ClassifierResult(hand=h_key)

    # ── WINDOW_SWITCHER ─────────────────────────────────────────────────

    def _process_window_switcher(
        self,
        hand: HandData,
        now: float,
        pos3: tuple,
        h_key: str,
        is_fist: bool,
    ) -> ClassifierResult:
        # Timeout → cancelar
        if now - self._switcher_start > WINSW_TIMEOUT:
            self._state = _State.IDLE
            self._winsw_cooldown_until = now + 1.0
            self._nav_fist_count = 0
            return ClassifierResult(ClassifiedGesture.WINDOW_SWITCHER_CANCEL, pos3, hand=h_key)

        # Punho fechado → confirmar seleção
        if is_fist:
            self._nav_fist_count += 1
            if self._nav_fist_count >= FIST_CONFIRM_FRAMES:
                self._state = _State.IDLE
                self._had_fist = False
                self._fist_count = 0
                self._open_count = 0
                self._winsw_cooldown_until = now + 1.0
                self._nav_fist_count = 0
                return ClassifierResult(
                    ClassifiedGesture.WINDOW_SWITCHER_CONFIRM, pos3, hand=h_key
                )
            # Acumulando frames de punho — não registrar nav para evitar confusão
            return ClassifierResult(hand=h_key)
        else:
            self._nav_fist_count = 0

        # Navegação: posição da palma para swipe
        pc = hand.palm_center
        self._nav_history.append((float(pc[0]), float(pc[1]), now))
        nav = self._detect_nav_swipe(now)
        if nav is not None:
            return ClassifierResult(nav, pos3, hand=h_key)

        return ClassifierResult(hand=h_key)

    def _detect_nav_swipe(self, now: float) -> ClassifiedGesture | None:
        """Detecta swipe de navegação no seletor."""
        if now - self._last_nav_time < SWIPE_NAV_COOLDOWN:
            return None
        if len(self._nav_history) < SWIPE_NAV_FRAMES + 1:
            return None

        recent = list(self._nav_history)[-(SWIPE_NAV_FRAMES + 1):]
        x0, y0, t0 = recent[0]
        x1, y1, t1 = recent[-1]
        dt = t1 - t0
        if dt < 1e-6:
            return None

        dx = x1 - x0
        dy = y1 - y0
        speed = (dx * dx + dy * dy) ** 0.5 / dt

        if speed < SWIPE_NAV_MIN_SPEED:
            return None

        self._last_nav_time = now
        self._nav_history.clear()

        if abs(dx) >= abs(dy):
            return (
                ClassifiedGesture.WINDOW_SWITCHER_NAV_RIGHT
                if dx > 0
                else ClassifiedGesture.WINDOW_SWITCHER_NAV_LEFT
            )
        elif dy > 0:
            return ClassifiedGesture.WINDOW_SWITCHER_NAV_DOWN
        return None  # swipe para cima ignorado

    # ── Palm flip ───────────────────────────────────────────────────────

    def _check_palm_flip(self, hand: HandData, now: float) -> bool:
        """Detecta: palma→câmera → dorso→câmera → palma→câmera. Retorna True quando completo."""
        is_palm = self._is_palm_facing_camera(hand)

        if not self._palm_flip_active:
            if is_palm:
                self._palm_normal_count += 1
                self._palm_back_count = 0
            else:
                self._palm_back_count += 1
                self._palm_normal_count = 0
                if self._palm_back_count >= PALM_CONFIRM_FRAMES:
                    self._palm_flip_active = True
                    self._flip_start = now
                    self._flip_return_count = 0
        else:
            if now - self._flip_start > PALM_FLIP_TIMEOUT:
                self._palm_flip_active = False
                self._palm_back_count = 0
                self._palm_normal_count = 0
                self._flip_return_count = 0
                return False
            if is_palm:
                self._flip_return_count += 1
                if self._flip_return_count >= PALM_CONFIRM_FRAMES:
                    self._palm_flip_active = False
                    self._palm_back_count = 0
                    self._palm_normal_count = 0
                    self._flip_return_count = 0
                    return True
            else:
                self._flip_return_count = 0

        return False

    def _is_palm_facing_camera(self, hand: HandData) -> bool:
        """
        True se a palma está voltada para a câmera.
        Heurística: mão direita com palma para câmera → polegar à esquerda do
        MCP do indicador (x menor). Ao virar, polegar passa para a direita.
        """
        thumb_x = float(hand.landmarks[4][0])       # THUMB_TIP.x
        index_mcp_x = float(hand.landmarks[5][0])   # INDEX_FINGER_MCP.x
        margin = 0.03  # zona morta para evitar flicker
        # Imagem enviada ao MediaPipe já está espelhada (flip antes da detecção).
        # Mão Direita (user): polegar à DIREITA do índice MCP quando palma virada.
        if hand.handedness == "Right":
            return thumb_x > index_mcp_x + margin
        else:
            return thumb_x < index_mcp_x - margin

    # ── Pose detection (angle-based, perspective-invariant) ──────────────

    def _angle_at_joint(self, lms: np.ndarray, a: int, b: int, c: int) -> float:
        v1 = lms[a] - lms[b]
        v2 = lms[c] - lms[b]
        n1 = float(np.linalg.norm(v1))
        n2 = float(np.linalg.norm(v2))
        if n1 < 1e-7 or n2 < 1e-7:
            return 0.0
        cos_a = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
        return float(np.degrees(np.arccos(cos_a)))

    def _finger_extended(self, hand: HandData, finger: str) -> bool:
        lms = hand.world_landmarks if hand.world_landmarks is not None else hand.landmarks
        _joints = {
            "index":  (5,  6,  8),
            "middle": (9,  10, 12),
            "ring":   (13, 14, 16),
            "pinky":  (17, 18, 20),
        }
        a, b, c = _joints[finger]
        return self._angle_at_joint(lms, a, b, c) > 145.0

    def _is_fist(self, hand: HandData) -> bool:
        return not any(self._finger_extended(hand, f) for f in ("index", "middle", "ring", "pinky"))

    def _is_open_hand(self, hand: HandData) -> bool:
        return sum(1 for f in ("index", "middle", "ring", "pinky") if self._finger_extended(hand, f)) >= 3

    # ── Reset ────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reseta o classificador (chamado quando a mão desaparece da câmera)."""
        self._state = _State.IDLE
        self._fist_count = 0
        self._open_count = 0
        self._had_fist = False
        self._fist_jitter = 0
        self._palm_flip_active = False
        self._palm_back_count = 0
        self._palm_normal_count = 0
        self._flip_return_count = 0
        self._nav_history.clear()
        self._nav_fist_count = 0
        self._current_pose = "OTHER"
