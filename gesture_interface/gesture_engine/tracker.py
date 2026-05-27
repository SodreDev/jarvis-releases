"""
Hand tracker via MediaPipe Hands (Tasks API v0.10+).

Toda imagem da câmera é processada LOCALMENTE — nenhum frame é enviado
a qualquer modelo de IA ou serviço externo.
"""
from __future__ import annotations

import os
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import mediapipe as mp
import numpy as np

from gesture_interface.config import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_INDEX,
    CAMERA_WIDTH,
    MP_MAX_HANDS,
    MP_MIN_DETECTION_CONFIDENCE,
    MP_MIN_TRACKING_CONFIDENCE,
)

# ── Model download ──────────────────────────────────────────────────────────
_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
_MODEL_DIR = Path(__file__).resolve().parent.parent / "gesture_data"
_MODEL_PATH = _MODEL_DIR / "hand_landmarker.task"


def _ensure_model() -> str:
    """Download hand_landmarker.task if not present. Returns path string."""
    if _MODEL_PATH.exists():
        return str(_MODEL_PATH)
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[HandTracker] Baixando modelo hand_landmarker.task...")
    urllib.request.urlretrieve(_MODEL_URL, str(_MODEL_PATH))
    print(f"[HandTracker] Modelo salvo em {_MODEL_PATH}")
    return str(_MODEL_PATH)


# 21 landmark names
LANDMARK_NAMES: list[str] = [
    "WRIST",
    "THUMB_CMC", "THUMB_MCP", "THUMB_IP", "THUMB_TIP",
    "INDEX_FINGER_MCP", "INDEX_FINGER_PIP", "INDEX_FINGER_DIP", "INDEX_FINGER_TIP",
    "MIDDLE_FINGER_MCP", "MIDDLE_FINGER_PIP", "MIDDLE_FINGER_DIP", "MIDDLE_FINGER_TIP",
    "RING_FINGER_MCP", "RING_FINGER_PIP", "RING_FINGER_DIP", "RING_FINGER_TIP",
    "PINKY_MCP", "PINKY_PIP", "PINKY_DIP", "PINKY_TIP",
]


@dataclass
class HandData:
    """Dados processados de uma mão detectada."""
    landmarks: np.ndarray                # (21, 3) — coordenadas normalizadas
    handedness: str                      # "Left" | "Right"
    world_landmarks: np.ndarray | None = None  # (21, 3) — coordenadas em metros
    timestamp: float = 0.0

    # ── helpers ──────────────────────────────────────────────────────────
    @property
    def wrist(self) -> np.ndarray:
        return self.landmarks[0]

    @property
    def thumb_tip(self) -> np.ndarray:
        return self.landmarks[4]

    @property
    def index_tip(self) -> np.ndarray:
        return self.landmarks[8]

    @property
    def middle_tip(self) -> np.ndarray:
        return self.landmarks[12]

    @property
    def ring_tip(self) -> np.ndarray:
        return self.landmarks[16]

    @property
    def pinky_tip(self) -> np.ndarray:
        return self.landmarks[20]

    @property
    def index_mcp(self) -> np.ndarray:
        return self.landmarks[5]

    @property
    def palm_center(self) -> np.ndarray:
        return np.mean(self.landmarks[[0, 5, 9, 13, 17]], axis=0)

    def finger_distances(self) -> dict[str, float]:
        """Distância de cada ponta do dedo ao centro da palma."""
        c = self.palm_center
        return {
            "thumb":  float(np.linalg.norm(self.thumb_tip - c)),
            "index":  float(np.linalg.norm(self.index_tip - c)),
            "middle": float(np.linalg.norm(self.middle_tip - c)),
            "ring":   float(np.linalg.norm(self.ring_tip - c)),
            "pinky":  float(np.linalg.norm(self.pinky_tip - c)),
        }


@dataclass
class TrackerState:
    """Estado corrente do tracker compartilhado thread-safe."""
    hands: list[HandData] = field(default_factory=list)
    frame_count: int = 0
    fps: float = 0.0
    running: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    # Frame BGR mais recente (para exibição na UI — NUNCA sai do processo)
    _latest_frame: np.ndarray | None = field(default=None, repr=False)
    # Landmarks nativos do MediaPipe para desenho de overlay
    _raw_hand_landmarks: list | None = field(default=None, repr=False)

    def update(self, hands: list[HandData], fps: float,
               frame: np.ndarray | None = None,
               raw_landmarks: list | None = None) -> None:
        with self._lock:
            self.hands = hands
            self.frame_count += 1
            self.fps = fps
            if frame is not None:
                self._latest_frame = frame
            self._raw_hand_landmarks = raw_landmarks

    def snapshot(self) -> list[HandData]:
        with self._lock:
            return list(self.hands)

    def get_frame(self) -> np.ndarray | None:
        """Retorna cópia do último frame (thread-safe). Só para uso LOCAL na UI."""
        with self._lock:
            if self._latest_frame is not None:
                return self._latest_frame.copy()
            return None

    def get_raw_landmarks(self) -> list | None:
        """Retorna os landmarks nativos do MediaPipe para overlay."""
        with self._lock:
            return self._raw_hand_landmarks


class HandTracker:
    """
    Captura webcam em thread dedicada e extrai landmarks via MediaPipe.

    SEGURANÇA: nenhum frame sai desta classe. Apenas `HandData` (coordenadas
    numéricas) é exposto para os módulos de reconhecimento de gestos.
    Frames ficam disponíveis via TrackerState apenas para exibição LOCAL na UI.
    """

    def __init__(self, on_hands: Callable[[list[HandData]], None] | None = None,
                 eye_tracker=None):
        self.state = TrackerState()
        self._on_hands = on_hands
        self._eye_tracker = eye_tracker  # EyeTracker opcional (compartilha frames)
        self._eye_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def set_eye_tracker(self, eye_tracker) -> None:
        """Define ou remove o eye tracker dinamicamente (thread-safe)."""
        with self._eye_lock:
            self._eye_tracker = eye_tracker

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self) -> None:
        if self.state.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="hand-tracker")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)
        self.state.running = False

    # ── main loop ────────────────────────────────────────────────────────
    def _loop(self) -> None:
        model_path = _ensure_model()

        # Tenta usar o Camera Broker compartilhado (permite que presence
        # detector e gesture tracker dividam a mesma webcam). Fallback para
        # cv2.VideoCapture direto se o broker estiver desabilitado/indisponível.
        use_broker = False
        broker_q = None
        cap = None
        try:
            import config as _cfg
            if getattr(_cfg, "CAMERA_BROKER_ENABLED", True):
                from core.camera_broker import get_broker
                broker = get_broker(device_index=CAMERA_INDEX)
                broker_q = broker.subscribe(
                    "gesture_tracker",
                    fps_max=CAMERA_FPS,
                    width=CAMERA_WIDTH,
                    height=CAMERA_HEIGHT,
                )
                use_broker = True
                print("[hand-tracker] Usando CameraBroker.")
        except Exception as e:
            print(f"[hand-tracker] CameraBroker indisponível ({e}) — fallback direto.")

        if not use_broker:
            cap = cv2.VideoCapture(CAMERA_INDEX)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
            cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)

        # MediaPipe Tasks API — HandLandmarker em modo VIDEO (síncrono por frame)
        vision = mp.tasks.vision
        base_options = mp.tasks.BaseOptions(model_asset_path=model_path)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_hands=MP_MAX_HANDS,
            min_hand_detection_confidence=MP_MIN_DETECTION_CONFIDENCE,
            min_hand_presence_confidence=MP_MIN_DETECTION_CONFIDENCE,
            min_tracking_confidence=MP_MIN_TRACKING_CONFIDENCE,
        )
        landmarker = vision.HandLandmarker.create_from_options(options)

        self.state.running = True
        t_prev = time.perf_counter()
        fps_smooth = 0.0

        try:
            while not self._stop_event.is_set():
                if use_broker:
                    try:
                        frame = broker_q.get(timeout=0.5)
                    except Exception:
                        continue
                    ok = frame is not None
                else:
                    ok, frame = cap.read()
                if not ok:
                    time.sleep(0.01)
                    continue

                # Converter BGR → RGB e espelhar (selfie mode) para handedness correto
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb = cv2.flip(rgb, 1)
                frame = cv2.flip(frame, 1)  # frame de exibição também espelhado
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

                now = time.perf_counter()
                frame_ts_ms = int(now * 1000)  # timestamp real em ms
                try:
                    result = landmarker.detect_for_video(mp_image, frame_ts_ms)
                except RuntimeError:
                    # MediaPipe executor já encerrado — sair do loop
                    break

                # Processar eye tracking no mesmo frame (se ativado)
                with self._eye_lock:
                    et = self._eye_tracker
                if et is not None:
                    try:
                        et.process_frame(rgb)
                    except Exception:
                        pass

                dt = now - t_prev
                if dt > 0:
                    fps_smooth = 0.9 * fps_smooth + 0.1 * (1.0 / dt)
                t_prev = now

                hand_list: list[HandData] = []
                if result.hand_landmarks:
                    for i, lm_list in enumerate(result.hand_landmarks):
                        coords = np.array(
                            [[p.x, p.y, p.z] for p in lm_list],
                            dtype=np.float32,
                        )
                        # Handedness
                        hand_label = "Right"
                        if result.handedness and i < len(result.handedness):
                            cats = result.handedness[i]
                            if cats:
                                hand_label = cats[0].category_name

                        # World landmarks
                        wl = None
                        if result.hand_world_landmarks and i < len(result.hand_world_landmarks):
                            wlm = result.hand_world_landmarks[i]
                            wl = np.array(
                                [[p.x, p.y, p.z] for p in wlm],
                                dtype=np.float32,
                            )
                        hand_list.append(HandData(
                            landmarks=coords,
                            handedness=hand_label,
                            world_landmarks=wl,
                            timestamp=now,
                        ))

                # Armazenar frame + landmarks para a UI (frame NUNCA sai do processo)
                self.state.update(
                    hand_list, fps_smooth,
                    frame=frame,
                    raw_landmarks=result.hand_landmarks if result.hand_landmarks else None,
                )

                if self._on_hands and hand_list:
                    try:
                        self._on_hands(hand_list)
                    except Exception:
                        pass  # callbacks do consumidor não devem travar o tracker
        finally:
            try:
                landmarker.close()
            except (RuntimeError, OSError):
                pass  # MediaPipe executor já encerrado
            # Após close(), substituir o método na instância para que __del__
            # não tente fechar novamente após o executor já estar encerrado.
            # HandLandmarker é Python puro, então podemos sobrescrever no __dict__.
            try:
                landmarker.close = lambda: None
            except Exception:
                pass
            if use_broker:
                try:
                    from core.camera_broker import get_broker
                    get_broker(device_index=CAMERA_INDEX).unsubscribe("gesture_tracker")
                except Exception:
                    pass
            elif cap is not None:
                cap.release()
            self.state.running = False
