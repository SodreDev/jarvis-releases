"""
Presence Detector — detecta se você está em frente ao PC ou ausente.

Roda no Camera Broker @ low-fps (default 2 fps), uso de CPU desprezível.
Usa MediaPipe Tasks API (FaceDetector) — compatível com mediapipe ≥ 0.10.

Estados:
    "present" → rosto detectado
    "away"    → sem rosto há ≥ 5s
    "unknown" → ainda não inicializado / desligado

Eventos publicados em event_bus:
    presence.changed → {"state": <novo>, "previous": <antigo>}
"""
from __future__ import annotations

import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

try:
    import cv2  # type: ignore
    import mediapipe as mp  # type: ignore
    _DEPS_OK = True
    _DEPS_ERR = ""
except Exception as _e_dep:
    _DEPS_OK = False
    _DEPS_ERR = repr(_e_dep)

print(f"[Presence] Módulo carregado (DEPS_OK={_DEPS_OK}{(' err='+_DEPS_ERR) if _DEPS_ERR else ''}).")

from core import event_bus

import config as _cfg


# ── Modelo ─────────────────────────────────────────────────────────────────

_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"
)
_MODEL_DIR = Path(__file__).resolve().parent.parent / "gesture_interface" / "gesture_data"
_MODEL_PATH = _MODEL_DIR / "blaze_face_short_range.tflite"


def _ensure_model() -> str:
    if _MODEL_PATH.exists():
        return str(_MODEL_PATH)
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    print("[Presence] Baixando modelo blaze_face_short_range.tflite...")
    urllib.request.urlretrieve(_MODEL_URL, str(_MODEL_PATH))
    print(f"[Presence] Modelo salvo em {_MODEL_PATH}")
    return str(_MODEL_PATH)


# ── Estado global ──────────────────────────────────────────────────────────

_STATE = "unknown"
_LOCK = threading.RLock()
_THREAD: Optional[threading.Thread] = None
_STOP = threading.Event()

_NO_FACE_AWAY_S = 5.0  # sem rosto por 5s → "away"


def get_state() -> str:
    with _LOCK:
        return _STATE


def _set_state(novo: str) -> None:
    global _STATE
    with _LOCK:
        if novo == _STATE:
            return
        antigo = _STATE
        _STATE = novo
    print(f"[Presence] {antigo} → {novo}")
    try:
        event_bus.publish("presence.changed", {
            "state": novo,
            "previous": antigo,
        })
    except Exception:
        pass


def _loop() -> None:
    import sys as _sys
    print("[Presence] Loop iniciado.", flush=True)
    _sys.stdout.flush()
    if not _DEPS_OK:
        print("[Presence] cv2/mediapipe indisponível — encerrando.")
        return
    try:
        model_path = _ensure_model()
        print(f"[Presence] Modelo OK: {model_path}")
    except Exception as e:
        print(f"[Presence] Falha ao obter modelo: {e}")
        return

    fps = max(1, int(getattr(_cfg, "PRESENCE_FPS", 2)))
    try:
        from core.camera_broker import get_broker
        broker = get_broker(device_index=0)
        q = broker.subscribe("presence", fps_max=fps, width=320, height=240)
        print(f"[Presence] Subscrito no CameraBroker (fps={fps}).")
    except Exception as e:
        print(f"[Presence] Falha ao subscrever no CameraBroker: {e}")
        return

    # MediaPipe Tasks API — FaceDetector em modo VIDEO
    try:
        vision = mp.tasks.vision
        base_options = mp.tasks.BaseOptions(model_asset_path=model_path)
        # Algumas versões do mediapipe não aceitam min_detection_confidence
        # diretamente em FaceDetectorOptions — tentamos com e sem.
        try:
            options = vision.FaceDetectorOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.VIDEO,
                min_detection_confidence=0.5,
            )
        except TypeError:
            options = vision.FaceDetectorOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.VIDEO,
            )
        detector = vision.FaceDetector.create_from_options(options)
        print("[Presence] FaceDetector criado.")
    except Exception as e:
        print(f"[Presence] Falha ao criar FaceDetector: {e}")
        try:
            broker.unsubscribe("presence")
        except Exception:
            pass
        return

    last_face_ts = 0.0

    try:
        while not _STOP.is_set():
            try:
                frame = q.get(timeout=1.0)
            except Exception:
                if last_face_ts and (time.time() - last_face_ts) > _NO_FACE_AWAY_S:
                    _set_state("away")
                continue

            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                ts_ms = int(time.perf_counter() * 1000)
                result = detector.detect_for_video(mp_image, ts_ms)
            except Exception:
                continue

            now = time.time()
            tem_rosto = bool(result and result.detections)

            if tem_rosto:
                last_face_ts = now
                if get_state() != "present":
                    _set_state("present")
            else:
                if last_face_ts == 0.0:
                    last_face_ts = now - _NO_FACE_AWAY_S  # considera away já
                if (now - last_face_ts) >= _NO_FACE_AWAY_S \
                        and get_state() != "away":
                    _set_state("away")
    finally:
        try:
            detector.close()
        except Exception:
            pass
        try:
            broker.unsubscribe("presence")
        except Exception:
            pass


def start() -> str:
    """Inicia o detector. Idempotente."""
    global _THREAD
    print(f"[Presence] start() chamado. DEPS_OK={_DEPS_OK}")
    if not _DEPS_OK:
        return f"Câmera indisponível, Senhor ({_DEPS_ERR or 'cv2/mediapipe não instalados'})."
    with _LOCK:
        if _THREAD and _THREAD.is_alive():
            return "Detecção de presença já está ativa, Senhor."
        _STOP.clear()
        _THREAD = threading.Thread(target=_loop, daemon=True, name="presence-detector")
        _THREAD.start()
        print(f"[Presence] Thread criada (alive={_THREAD.is_alive()}, ident={_THREAD.ident}).")
    return "Detecção de presença ativada, Senhor."


def stop() -> str:
    global _THREAD
    with _LOCK:
        _STOP.set()
        t = _THREAD
        _THREAD = None
    if t and t.is_alive():
        t.join(timeout=2.0)
    _set_state("unknown")
    return "Detecção de presença desativada, Senhor."


def is_running() -> bool:
    with _LOCK:
        return _THREAD is not None and _THREAD.is_alive()
