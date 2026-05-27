"""
Camera Broker — singleton dono do `cv2.VideoCapture`, distribui frames a
múltiplos consumidores (gesture tracker, presence detector, vision tools).

Modelo:
    [Hardware] → [Broker thread única] → publish para queue de cada consumer
                                       → cada consumer processa no próprio ritmo

Garantias:
- Reference counting: primeiro `subscribe` abre a câmera; último `unsubscribe`
  fecha. Reabre se um novo subscribe vier depois.
- Resolução adaptativa: se TODOS os consumers ativos pedirem resolução baixa
  (ex.: só presence em 320×240@2fps), a câmera é configurada nesse modo. Quando
  o gesture tracker entra (640×480@30fps+), reconfigura.
- Drop-frame por consumer: cada queue é `maxsize=2` com política de descarte
  (drop oldest) para nunca acumular lag.
- Thread-safe.

Uso:
    from core.camera_broker import get_broker
    bro = get_broker()
    q = bro.subscribe("presence", fps_max=2, width=320, height=240)
    while True:
        frame = q.get()  # numpy BGR
        ...
    bro.unsubscribe("presence")

Notas de performance:
- Câmera é OPENCV-CAP_DSHOW no Windows (mais estável que default MSMF).
- FPS efetivo é o MAIOR `fps_max` entre consumers ativos.
- Resolução efetiva é a MAIOR `width`/`height` solicitada.
"""
from __future__ import annotations

import threading
import time
import queue
from dataclasses import dataclass, field
from typing import Optional

try:
    import cv2  # type: ignore
    _CV2_OK = True
except Exception:
    _CV2_OK = False


@dataclass
class _Subscriber:
    name: str
    fps_max: float
    width: int
    height: int
    queue: "queue.Queue" = field(default_factory=lambda: queue.Queue(maxsize=2))
    last_pushed_ts: float = 0.0


class CameraBroker:
    def __init__(self, device_index: int = 0):
        self._device_index = device_index
        self._lock = threading.RLock()
        self._subs: dict[str, _Subscriber] = {}
        self._cap = None  # cv2.VideoCapture
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._current_w = 0
        self._current_h = 0
        self._current_fps = 0
        # Última falha — evita reconectar em loop quando câmera está ocupada
        self._last_failure_ts = 0.0
        self._failure_cooldown = 5.0

    # ── API pública ──────────────────────────────────────────────────────

    def subscribe(self, name: str, fps_max: float = 5.0,
                  width: int = 640, height: int = 480) -> "queue.Queue":
        """Registra (ou substitui) um consumer e devolve sua queue."""
        if not _CV2_OK:
            raise RuntimeError("OpenCV (cv2) não disponível.")
        with self._lock:
            sub = _Subscriber(name=name, fps_max=fps_max,
                              width=width, height=height)
            self._subs[name] = sub
            self._reconfigure_if_needed_locked()
            self._ensure_running_locked()
            return sub.queue

    def unsubscribe(self, name: str) -> None:
        with self._lock:
            self._subs.pop(name, None)
            if not self._subs:
                self._stop_locked()
            else:
                self._reconfigure_if_needed_locked()

    def is_active(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def list_subscribers(self) -> list[str]:
        with self._lock:
            return list(self._subs.keys())

    # ── Internos ─────────────────────────────────────────────────────────

    def _ensure_running_locked(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if time.time() - self._last_failure_ts < self._failure_cooldown:
            print("[CameraBroker] Cooldown ativo após falha — aguardando.")
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="camera-broker"
        )
        self._thread.start()
        print(f"[CameraBroker] Thread iniciada (subs={list(self._subs.keys())}).")

    def _stop_locked(self) -> None:
        self._stop.set()
        # Não dá join aqui — chamador externo, evita deadlock se chamado
        # de dentro do próprio loop.
        self._thread = None

    def _reconfigure_if_needed_locked(self) -> None:
        if not self._subs:
            return
        max_w = max(s.width  for s in self._subs.values())
        max_h = max(s.height for s in self._subs.values())
        max_fps = max(int(s.fps_max) for s in self._subs.values())
        max_fps = max(1, max_fps)
        if (max_w == self._current_w and max_h == self._current_h
                and max_fps == self._current_fps):
            return
        # Marca pra reconfigurar — o loop vai aplicar quando puder
        self._current_w = max_w
        self._current_h = max_h
        self._current_fps = max_fps
        print(f"[CameraBroker] Reconfig pendente → {max_w}x{max_h}@{max_fps}fps")
        # Se já está rodando, fecha cap pra forçar reabrir com novos params.
        # Marca via flag — o loop fecha e reabre.
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _open_cap_locked(self) -> bool:
        # Tenta DSHOW primeiro (Windows mais estável)
        backends = []
        if _CV2_OK and hasattr(cv2, "CAP_DSHOW"):
            backends.append(cv2.CAP_DSHOW)
        backends.append(0)  # default
        for be in backends:
            try:
                cap = cv2.VideoCapture(self._device_index, be) if be else \
                      cv2.VideoCapture(self._device_index)
                if not cap.isOpened():
                    print(f"[CameraBroker] backend={be} não abriu (provável "
                          f"câmera ocupada por outro app).")
                    cap.release()
                    continue
                cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self._current_w or 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._current_h or 480)
                cap.set(cv2.CAP_PROP_FPS,          self._current_fps or 30)
                self._cap = cap
                print(f"[CameraBroker] Câmera aberta backend={be} "
                      f"{self._current_w}x{self._current_h}@{self._current_fps}")
                return True
            except Exception as e:
                print(f"[CameraBroker] backend={be} falhou: {e}")
        print("[CameraBroker] FALHA ao abrir câmera em todos os backends — "
              "verifique se outro app (Discord/OBS/Teams) está usando.")
        self._last_failure_ts = time.time()
        return False

    def _loop(self) -> None:
        if _CV2_OK is False:
            return
        # Garante que current_* estão setados
        with self._lock:
            if self._current_w == 0 and self._subs:
                self._reconfigure_if_needed_locked()
        try:
            while not self._stop.is_set():
                with self._lock:
                    if self._cap is None and not self._open_cap_locked():
                        break
                ok, frame = self._cap.read() if self._cap else (False, None)
                if not ok or frame is None:
                    # Falha transitória
                    time.sleep(0.05)
                    with self._lock:
                        # Tenta reabrir uma vez
                        if self._cap is not None:
                            try:
                                self._cap.release()
                            except Exception:
                                pass
                            self._cap = None
                    continue
                now = time.perf_counter()
                # Distribui para cada consumer respeitando seu fps_max
                with self._lock:
                    subs = list(self._subs.values())
                for sub in subs:
                    interval = 1.0 / max(0.1, sub.fps_max)
                    if now - sub.last_pushed_ts < interval:
                        continue
                    # drop oldest se queue cheia
                    try:
                        sub.queue.put_nowait(frame)
                    except queue.Full:
                        try:
                            sub.queue.get_nowait()
                        except queue.Empty:
                            pass
                        try:
                            sub.queue.put_nowait(frame)
                        except queue.Full:
                            pass
                    sub.last_pushed_ts = now
        finally:
            with self._lock:
                if self._cap is not None:
                    try:
                        self._cap.release()
                    except Exception:
                        pass
                    self._cap = None
            print("[CameraBroker] Loop encerrado.")


# ── Singleton ───────────────────────────────────────────────────────────

_BROKER: Optional[CameraBroker] = None
_BROKER_LOCK = threading.Lock()


def get_broker(device_index: int = 0) -> CameraBroker:
    global _BROKER
    with _BROKER_LOCK:
        if _BROKER is None:
            _BROKER = CameraBroker(device_index=device_index)
        return _BROKER
