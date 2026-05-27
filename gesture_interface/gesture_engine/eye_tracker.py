"""
Eye / Gaze tracker via face direction (head pose estimation).

Usa a DIRECAO DA CABECA para estimar para onde o usuario esta olhando
e mapear para coordenadas de tela.  Funciona perfeitamente COM oculos:
usa landmarks faciais 3D + cv2.solvePnP, sem depender da iris.

Calibracao via "sweep": um ponto percorre a tela enquanto o usuario
acompanha com o rosto.  O mapeamento (yaw, pitch) -> (screen_x, screen_y)
e salvo em arquivo e reutilizado nas proximas sessoes.

Toda imagem e processada LOCALMENTE — nenhum frame sai do processo.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import mediapipe as mp
import numpy as np

from gesture_interface.config import (
    EYE_MIN_DETECTION_CONFIDENCE,
    EYE_MIN_TRACKING_CONFIDENCE,
    EYE_MOVE_THRESHOLD,
    EYE_SMOOTHING_ALPHA,
    EYE_SMOOTHING_FRAMES,
    WINK_EAR_THRESHOLD,
    WINK_CHEEK_BROW_THRESHOLD,
    WINK_CONFIRM_FRAMES,
    WINK_COOLDOWN,
    EYEBROW_RAISE_MULTIPLIER,
    EYEBROW_CONFIRM_FRAMES,
    EYEBROW_COOLDOWN,
)

# ── Model download ──────────────────────────────────────────────────────────
_FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
)
_DATA_DIR = Path(__file__).resolve().parent.parent / "gesture_data"
_FACE_MODEL_PATH = _DATA_DIR / "face_landmarker.task"
_CALIBRATION_PATH = _DATA_DIR / "eye_calibration.json"


def _ensure_face_model() -> str:
    if _FACE_MODEL_PATH.exists():
        return str(_FACE_MODEL_PATH)
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("[EyeTracker] Baixando modelo face_landmarker.task...")
    urllib.request.urlretrieve(_FACE_MODEL_URL, str(_FACE_MODEL_PATH))
    print(f"[EyeTracker] Modelo salvo em {_FACE_MODEL_PATH}")
    return str(_FACE_MODEL_PATH)


# ── Head pose landmarks (6-point model for solvePnP) ───────────────────────
_NOSE_TIP = 1
_CHIN = 152
_LEFT_EYE_OUTER = 263    # pessoa: esquerdo, imagem: direita
_RIGHT_EYE_OUTER = 33    # pessoa: direito, imagem: esquerda
_LEFT_MOUTH = 291
_RIGHT_MOUTH = 61

_FACE_INDICES = [_NOSE_TIP, _CHIN, _LEFT_EYE_OUTER, _RIGHT_EYE_OUTER,
                 _LEFT_MOUTH, _RIGHT_MOUTH]

# Modelo 3D generico do rosto (mm) para os 6 landmarks acima
_FACE_3D = np.array([
    (0.0, 0.0, 0.0),             # Nose tip
    (0.0, -330.0, -65.0),        # Chin
    (-225.0, 170.0, -135.0),     # Left eye outer
    (225.0, 170.0, -135.0),      # Right eye outer
    (-150.0, -150.0, -125.0),    # Left mouth
    (150.0, -150.0, -125.0),     # Right mouth
], dtype=np.float64)

# Blink / wink detection landmarks
_LEFT_EYE_TOP = 159
_LEFT_EYE_BOTTOM = 145
_LEFT_EYE_INNER = 133
_RIGHT_EYE_TOP = 386
_RIGHT_EYE_BOTTOM = 374
_RIGHT_EYE_INNER = 362

# Eyebrow landmarks (top of brow arch)
_LEFT_BROW_TOP = 105     # left eyebrow upper
_RIGHT_BROW_TOP = 334    # right eyebrow upper

# Cheek landmarks (for strong wink = cheek touches brow)
_LEFT_CHEEK = 117        # left cheekbone high
_RIGHT_CHEEK = 346       # right cheekbone high


@dataclass
class GazeData:
    """Dados processados do olhar baseado em direcao da cabeca."""
    screen_x: float = 0.5
    screen_y: float = 0.5
    yaw: float = 0.0        # graus — negativo=esquerda, positivo=direita
    pitch: float = 0.0      # graus — negativo=cima, positivo=baixo
    left_eye_open: bool = True
    right_eye_open: bool = True
    confidence: float = 0.0
    timestamp: float = 0.0
    # Facial gestures
    wink_left: bool = False    # strong wink left eye (cheek+brow) = left click
    wink_right: bool = False   # strong wink right eye = left click
    eyebrows_raised: bool = False  # both eyebrows raised = right click


@dataclass
class EyeTrackerState:
    """Estado thread-safe do eye tracker."""
    gaze: GazeData = field(default_factory=GazeData)
    running: bool = False
    calibrated: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _raw_face_landmarks: list | None = field(default=None, repr=False)

    def update(self, gaze: GazeData, raw_landmarks: list | None = None) -> None:
        with self._lock:
            self.gaze = gaze
            self._raw_face_landmarks = raw_landmarks

    def snapshot(self) -> GazeData:
        with self._lock:
            return self.gaze

    def get_raw_landmarks(self) -> list | None:
        with self._lock:
            return self._raw_face_landmarks


class EyeTracker:
    """
    Rastreia o olhar via direcao da cabeca (head pose estimation).

    Usa cv2.solvePnP com 6 landmarks faciais para calcular yaw/pitch
    da cabeca, depois mapeia para coordenadas de tela via calibracao linear.

    Funciona COM ou SEM oculos.  Processa frames fornecidos pelo
    HandTracker (compartilha a camera).
    """

    def __init__(self, on_gaze: Callable[[GazeData], None] | None = None):
        self.state = EyeTrackerState()
        self._on_gaze = on_gaze
        self._landmarker = None

        # Frame / camera info (set on first frame)
        self._frame_w: int = 0
        self._frame_h: int = 0
        self._camera_matrix: np.ndarray | None = None
        self._dist_coeffs = np.zeros((4, 1), dtype=np.float64)
        self._frame_ts_ms: int = 0

        # Smoothing: single-pass EMA for responsive 90fps movement
        self._ema_x: float = 0.5
        self._ema_y: float = 0.5
        self._alpha: float = EYE_SMOOTHING_ALPHA
        self._initialized_ema: bool = False

        # Raw head direction (for calibration sampling)
        self._raw_yaw: float = 0.0
        self._raw_pitch: float = 0.0
        self._has_face: bool = False

        # Calibration: linear mapping (yaw, pitch) -> (screen_x, screen_y)
        self._cal_yaw_scale: float = -0.0167
        self._cal_yaw_offset: float = 0.5
        self._cal_pitch_scale: float = -0.025
        self._cal_pitch_offset: float = 0.5
        self._cal_samples: list[tuple[float, float, float, float]] = []

        # ── Wink detection state ─────────────────────────────────────────
        self._l_wink_count: int = 0   # consecutive frames left eye closed
        self._r_wink_count: int = 0   # consecutive frames right eye closed
        self._last_wink_time: float = 0.0
        # ── Eyebrow raise detection state ────────────────────────────────
        self._brow_raise_count: int = 0
        self._brow_baseline: float = 0.0  # baseline brow distance (rolling avg)
        self._brow_baseline_init: bool = False
        self._last_brow_time: float = 0.0

    # ── Lifecycle ────────────────────────────────────────────────────────
    def initialize(self) -> None:
        """Carrega o modelo FaceLandmarker.  Chamar antes de process_frame."""
        model_path = _ensure_face_model()
        vision = mp.tasks.vision
        base_options = mp.tasks.BaseOptions(model_asset_path=model_path)
        options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=EYE_MIN_DETECTION_CONFIDENCE,
            min_face_presence_confidence=EYE_MIN_DETECTION_CONFIDENCE,
            min_tracking_confidence=EYE_MIN_TRACKING_CONFIDENCE,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self.state.running = True
        self.load_calibration()

    def close(self) -> None:
        if self._landmarker:
            self._landmarker.close()
            self._landmarker = None
        self.state.running = False

    # ── Frame processing ─────────────────────────────────────────────────
    def process_frame(self, rgb_frame: np.ndarray) -> GazeData | None:
        """
        Processa um frame RGB e retorna GazeData.
        Chamado pelo loop do HandTracker (compartilha frames da camera).
        """
        if self._landmarker is None:
            return None

        h, w = rgb_frame.shape[:2]
        if w != self._frame_w or h != self._frame_h:
            self._frame_w = w
            self._frame_h = h
            focal = float(w)
            cx, cy = w / 2.0, h / 2.0
            self._camera_matrix = np.array([
                [focal, 0.0, cx],
                [0.0, focal, cy],
                [0.0, 0.0, 1.0],
            ], dtype=np.float64)

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        self._frame_ts_ms = int(time.perf_counter() * 1000)
        result = self._landmarker.detect_for_video(mp_image, self._frame_ts_ms)

        if not result.face_landmarks or len(result.face_landmarks) == 0:
            self._has_face = False
            self.state.update(GazeData(timestamp=time.perf_counter()))
            return None

        lm = result.face_landmarks[0]
        now = time.perf_counter()

        # ── Head pose via solvePnP ──────────────────────────────────────
        face_2d = np.array(
            [[lm[idx].x * w, lm[idx].y * h] for idx in _FACE_INDICES],
            dtype=np.float64,
        )

        success, rvec, tvec = cv2.solvePnP(
            _FACE_3D, face_2d, self._camera_matrix, self._dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not success:
            self._has_face = False
            self.state.update(GazeData(timestamp=now), raw_landmarks=result.face_landmarks)
            return None

        # Euler angles via RQDecomp3x3
        rmat, _ = cv2.Rodrigues(rvec)
        angles, _, _, _, _, _ = cv2.RQDecomp3x3(rmat)
        yaw = float(angles[1])    # left / right
        pitch = float(angles[0])  # up / down

        self._raw_yaw = yaw
        self._raw_pitch = pitch
        self._has_face = True

        # ── Blink / wink detection ───────────────────────────────────────
        l_ear = 0.3   # default open
        r_ear = 0.3
        l_open = True
        r_open = True
        wink_left = False
        wink_right = False
        eyebrows_raised = False

        max_idx = max(_LEFT_EYE_TOP, _LEFT_EYE_BOTTOM,
                      _RIGHT_EYE_TOP, _RIGHT_EYE_BOTTOM,
                      _LEFT_EYE_OUTER, _LEFT_EYE_INNER,
                      _RIGHT_EYE_OUTER, _RIGHT_EYE_INNER,
                      _LEFT_BROW_TOP, _RIGHT_BROW_TOP,
                      _LEFT_CHEEK, _RIGHT_CHEEK)
        if len(lm) > max_idx:
            # Eye Aspect Ratio (EAR)
            l_h = abs(lm[_LEFT_EYE_TOP].y - lm[_LEFT_EYE_BOTTOM].y)
            l_w = abs(lm[_LEFT_EYE_OUTER].x - lm[_LEFT_EYE_INNER].x)
            r_h = abs(lm[_RIGHT_EYE_TOP].y - lm[_RIGHT_EYE_BOTTOM].y)
            r_w = abs(lm[_RIGHT_EYE_OUTER].x - lm[_RIGHT_EYE_INNER].x)
            if l_w > 1e-6:
                l_ear = l_h / l_w
                l_open = l_ear > WINK_EAR_THRESHOLD
            if r_w > 1e-6:
                r_ear = r_h / r_w
                r_open = r_ear > WINK_EAR_THRESHOLD

            # Strong wink: eye closed + cheek-brow distance small
            # Left eye wink (person's left = landmark left)
            l_cheek_brow = abs(lm[_LEFT_CHEEK].y - lm[_LEFT_BROW_TOP].y)
            r_cheek_brow = abs(lm[_RIGHT_CHEEK].y - lm[_RIGHT_BROW_TOP].y)

            l_strong_wink = (not l_open) and r_open and l_cheek_brow < WINK_CHEEK_BROW_THRESHOLD
            r_strong_wink = (not r_open) and l_open and r_cheek_brow < WINK_CHEEK_BROW_THRESHOLD

            if l_strong_wink:
                self._l_wink_count += 1
            else:
                self._l_wink_count = 0
            if r_strong_wink:
                self._r_wink_count += 1
            else:
                self._r_wink_count = 0

            if self._l_wink_count >= WINK_CONFIRM_FRAMES and (now - self._last_wink_time) > WINK_COOLDOWN:
                wink_left = True
                self._last_wink_time = now
                self._l_wink_count = 0
            if self._r_wink_count >= WINK_CONFIRM_FRAMES and (now - self._last_wink_time) > WINK_COOLDOWN:
                wink_right = True
                self._last_wink_time = now
                self._r_wink_count = 0

            # Eyebrow raise: both brows significantly above baseline
            l_brow_eye_dist = abs(lm[_LEFT_BROW_TOP].y - lm[_LEFT_EYE_TOP].y)
            r_brow_eye_dist = abs(lm[_RIGHT_BROW_TOP].y - lm[_RIGHT_EYE_TOP].y)
            avg_brow_dist = (l_brow_eye_dist + r_brow_eye_dist) / 2.0

            if not self._brow_baseline_init:
                self._brow_baseline = avg_brow_dist
                self._brow_baseline_init = True
            else:
                # Slow-update baseline (only when not raised)
                if avg_brow_dist < self._brow_baseline * 1.5:
                    self._brow_baseline = 0.98 * self._brow_baseline + 0.02 * avg_brow_dist

            if self._brow_baseline > 1e-6 and avg_brow_dist > self._brow_baseline * EYEBROW_RAISE_MULTIPLIER:
                self._brow_raise_count += 1
            else:
                self._brow_raise_count = 0

            if self._brow_raise_count >= EYEBROW_CONFIRM_FRAMES and (now - self._last_brow_time) > EYEBROW_COOLDOWN:
                eyebrows_raised = True
                self._last_brow_time = now
                self._brow_raise_count = 0

        # ── Map to screen via calibration ───────────────────────────────
        raw_x = yaw * self._cal_yaw_scale + self._cal_yaw_offset
        raw_y = pitch * self._cal_pitch_scale + self._cal_pitch_offset

        # Clamp before smoothing so EMA doesn't chase out-of-bounds
        raw_x = max(0.0, min(1.0, raw_x))
        raw_y = max(0.0, min(1.0, raw_y))

        # Double Exponential Moving Average for silky 90fps movement
        a = self._alpha
        if not self._initialized_ema:
            self._ema_x = raw_x
            self._ema_y = raw_y
            self._initialized_ema = True
        else:
            self._ema_x += a * (raw_x - self._ema_x)
            self._ema_y += a * (raw_y - self._ema_y)

        screen_x = max(0.0, min(1.0, self._ema_x))
        screen_y = max(0.0, min(1.0, self._ema_y))

        gaze = GazeData(
            screen_x=screen_x,
            screen_y=screen_y,
            yaw=yaw,
            pitch=pitch,
            left_eye_open=l_open,
            right_eye_open=r_open,
            confidence=1.0,
            timestamp=now,
            wink_left=wink_left,
            wink_right=wink_right,
            eyebrows_raised=eyebrows_raised,
        )

        self.state.update(gaze, raw_landmarks=result.face_landmarks)

        if self._on_gaze:
            try:
                self._on_gaze(gaze)
            except Exception:
                pass

        return gaze

    # ── Calibration ─────────────────────────────────────────────────────
    def get_raw_direction(self) -> tuple[float, float] | None:
        """Return (yaw, pitch) in degrees, or None if no face detected."""
        if not self._has_face:
            return None
        return (self._raw_yaw, self._raw_pitch)

    def add_calibration_point(self, screen_x: float, screen_y: float,
                              yaw: float, pitch: float) -> None:
        """Registra amostra de calibracao: posicao-alvo na tela + angulos."""
        self._cal_samples.append((screen_x, screen_y, yaw, pitch))

    def apply_calibration(self) -> None:
        """Ajusta mapeamento linear (yaw,pitch) -> (screen_x,screen_y)."""
        if len(self._cal_samples) < 10:
            return

        data = np.array(self._cal_samples)
        sx = data[:, 0]   # screen x targets
        sy = data[:, 1]   # screen y targets
        yaw = data[:, 2]
        pitch = data[:, 3]

        # Linear regression: screen_x = yaw * scale + offset
        if np.std(yaw) > 0.1:
            A = np.vstack([yaw, np.ones(len(yaw))]).T
            res = np.linalg.lstsq(A, sx, rcond=None)
            self._cal_yaw_scale = float(res[0][0])
            self._cal_yaw_offset = float(res[0][1])

        if np.std(pitch) > 0.1:
            A = np.vstack([pitch, np.ones(len(pitch))]).T
            res = np.linalg.lstsq(A, sy, rcond=None)
            self._cal_pitch_scale = float(res[0][0])
            self._cal_pitch_offset = float(res[0][1])

        self.state.calibrated = True
        self.save_calibration()

    def reset_calibration(self) -> None:
        self._cal_samples.clear()
        self._cal_yaw_scale = -0.025
        self._cal_yaw_offset = 0.5
        self._cal_pitch_scale = -0.04
        self._cal_pitch_offset = 0.5
        self.state.calibrated = False

    def save_calibration(self) -> None:
        """Salva calibracao em arquivo JSON."""
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "yaw_scale": self._cal_yaw_scale,
            "yaw_offset": self._cal_yaw_offset,
            "pitch_scale": self._cal_pitch_scale,
            "pitch_offset": self._cal_pitch_offset,
        }
        _CALIBRATION_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_calibration(self) -> bool:
        """Carrega calibracao salva.  Retorna True se carregou."""
        if not _CALIBRATION_PATH.exists():
            return False
        try:
            data = json.loads(_CALIBRATION_PATH.read_text(encoding="utf-8"))
            self._cal_yaw_scale = float(data["yaw_scale"])
            self._cal_yaw_offset = float(data["yaw_offset"])
            self._cal_pitch_scale = float(data["pitch_scale"])
            self._cal_pitch_offset = float(data["pitch_offset"])
            self.state.calibrated = True
            return True
        except (json.JSONDecodeError, KeyError, ValueError):
            return False
