"""
PyWebView API bridge — expõe métodos Python para o frontend JavaScript.

Todas as chamadas de JS → Python passam por esta classe.
"""
from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gesture_interface.main import GestureSystem


class GestureAPI:
    """Bridge JS ↔ Python para interface gestual via pywebview."""

    def __init__(self) -> None:
        self._system: GestureSystem | None = None

    def bind(self, system: GestureSystem) -> None:
        self._system = system

    # ── Mode ─────────────────────────────────────────────────────────────
    def get_mode(self) -> str:
        if self._system:
            return self._system.classifier.current_mode
        return "full"

    def set_mode(self, mode: str) -> str:
        if not self._system:
            return json.dumps({"error": "system not ready"})
        try:
            state = self._system.classifier.set_mode(mode)
            return json.dumps({
                "mode": mode,
                "desktop": state.desktop,
                "canvas2d": state.canvas2d,
                "workspace3d": state.workspace3d,
            })
        except ValueError as e:
            return json.dumps({"error": str(e)})

    def get_available_modes(self) -> str:
        if self._system:
            return json.dumps(self._system.classifier.available_modes())
        return json.dumps([])

    # ── Tracker ──────────────────────────────────────────────────────────
    def get_tracker_status(self) -> str:
        if not self._system:
            return json.dumps({"running": False, "fps": 0, "hands": 0})
        st = self._system.tracker.state
        return json.dumps({
            "running": st.running,
            "fps": round(st.fps, 1),
            "hands": len(st.hands),
            "frames": st.frame_count,
        })

    def start_tracker(self) -> str:
        if self._system:
            self._system.tracker.start()
            return json.dumps({"ok": True})
        return json.dumps({"ok": False})

    def stop_tracker(self) -> str:
        if self._system:
            self._system.tracker.stop()
            return json.dumps({"ok": True})
        return json.dumps({"ok": False})

    # ── Hand data (polling from JS) ──────────────────────────────────────
    def get_hand_data(self) -> str:
        if not self._system:
            return json.dumps([])
        hands = self._system.tracker.state.snapshot()
        result = []
        for h in hands:
            result.append({
                "handedness": h.handedness,
                "landmarks": h.landmarks.tolist(),
                "palm": h.palm_center.tolist(),
            })
        return json.dumps(result)

    # ── 3D workspace ─────────────────────────────────────────────────────
    def create_object(self, shape: str) -> str:
        if self._system and self._system.workspace3d:
            obj_id = self._system.workspace3d.create_object(shape)
            return json.dumps({"id": obj_id, "shape": shape})
        return json.dumps({"error": "workspace3d not available"})

    def get_scene(self) -> str:
        if self._system and self._system.workspace3d:
            return json.dumps(self._system.workspace3d.get_scene_state())
        return json.dumps([])

    # ── Canvas 2D ────────────────────────────────────────────────────────
    def get_canvas_state(self) -> str:
        if self._system and self._system.canvas2d:
            return json.dumps({
                "strokes": self._system.canvas2d.stroke_count,
                "color": self._system.canvas2d.current_color,
            })
        return json.dumps({})

    # ── Gesture training ─────────────────────────────────────────────────
    def list_custom_gestures(self) -> str:
        if self._system and self._system.trainer:
            return json.dumps(self._system.trainer.list_gestures())
        return json.dumps([])

    def start_recording(self, name: str, action: str) -> str:
        if self._system and self._system.trainer:
            self._system.trainer.record_start(name, action)
            return json.dumps({"recording": True})
        return json.dumps({"error": "trainer not available"})

    def stop_recording(self) -> str:
        if self._system and self._system.trainer:
            gesture = self._system.trainer.record_stop()
            if gesture:
                return json.dumps({"saved": True, "name": gesture.name})
            return json.dumps({"saved": False})
        return json.dumps({"error": "trainer not available"})

    def delete_gesture(self, name: str) -> str:
        if self._system and self._system.trainer:
            ok = self._system.trainer.delete_gesture(name)
            return json.dumps({"deleted": ok})
        return json.dumps({"error": "trainer not available"})
