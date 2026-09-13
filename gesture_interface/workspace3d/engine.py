"""
Workspace 3D engine — modelagem baseada em micro-partículas controlada por gestos.

A renderização 3D é feita no frontend via Three.js (workspace3d.html).
Este módulo processa gestos → gera comandos de manipulação → envia ao frontend.

Cada objeto é composto de muitas micro-partículas que se comportam como
esferas pequenas e formam malhas dinâmicas que respondem a forças gestuais.
"""
from __future__ import annotations

import json
import math
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from gesture_interface.config import (
    PARTICLE_COUNT_DEFAULT,
    PARTICLE_SIZE,
    PHYSICS_DAMPING,
    PHYSICS_FORCE_MULTIPLIER,
)
from gesture_interface.gesture_engine.recognizer import GestureEvent, GestureType


@dataclass
class Object3D:
    """Representa um objeto 3D no workspace."""
    id: str
    shape: str                         # "cube" | "sphere" | "cylinder" | "custom"
    position: list[float]              # [x, y, z]
    rotation: list[float]              # [rx, ry, rz] em radianos
    scale: list[float]                 # [sx, sy, sz]
    particle_count: int = PARTICLE_COUNT_DEFAULT
    color: str = "#00e6ff"

    def to_dict(self) -> dict:
        return self.__dict__


@dataclass
class SceneCommand:
    """Comando enviado ao frontend 3D."""
    action: str      # "create_object" | "deform" | "rotate" | "scale"
                     # | "translate" | "delete" | "select" | "clear"
    object_id: str = ""
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"action": self.action, "object_id": self.object_id, "params": self.params}


class Workspace3DEngine:
    """
    Handler de gestos para o workspace de modelagem 3D.

    Mapeamento:
        pinch               → selecionar objeto (ray cast na posição)
        pinch_hold+move     → mover/deformar objeto selecionado
        pinch_release       → soltar objeto
        open_hand           → push surface (empurrar partículas)
        fist                → pull/compress (puxar partículas)
        circle              → rotacionar objeto selecionado
        two_fingers+scale   → escalar objeto (distância entre mãos)
        swipe_up            → criar novo cubo primitivo
        swipe_down          → deletar objeto selecionado
    """

    PRIMITIVES = ["cube", "sphere", "cylinder"]

    def __init__(self, on_command: Callable[[SceneCommand], None] | None = None) -> None:
        self._on_command = on_command
        self._objects: dict[str, Object3D] = {}
        self._selected_id: str | None = None
        self._primitive_index: int = 0
        self._last_pinch_pos: tuple[float, float, float] | None = None
        self._last_create_time: float = 0.0

    def set_callback(self, cb: Callable[[SceneCommand], None]) -> None:
        self._on_command = cb

    def handle_gesture(self, event: GestureEvent) -> None:
        handler = {
            GestureType.PINCH: self._select_or_grab,
            GestureType.PINCH_HOLD: self._manipulate,
            GestureType.PINCH_RELEASE: self._release,
            GestureType.OPEN_HAND: self._push_surface,
            GestureType.FIST: self._pull_compress,
            GestureType.CIRCLE: self._rotate_object,
            GestureType.TWO_FINGERS: self._scale_mode,
            GestureType.SWIPE_UP: self._create_primitive,
            GestureType.SWIPE_DOWN: self._delete_selected,
        }.get(event.gesture)

        if handler:
            handler(event)

    # ── create / delete ──────────────────────────────────────────────────
    def _create_primitive(self, event: GestureEvent) -> None:
        now = time.perf_counter()
        if now - self._last_create_time < 1.0:
            return
        self._last_create_time = now

        shape = self.PRIMITIVES[self._primitive_index % len(self.PRIMITIVES)]
        self._primitive_index += 1

        obj_id = f"obj_{uuid.uuid4().hex[:8]}"
        obj = Object3D(
            id=obj_id,
            shape=shape,
            position=[event.position[0] * 4 - 2, event.position[1] * -4 + 2, 0.0],
            rotation=[0.0, 0.0, 0.0],
            scale=[1.0, 1.0, 1.0],
        )
        self._objects[obj_id] = obj
        self._selected_id = obj_id

        self._emit(SceneCommand(
            action="create_object",
            object_id=obj_id,
            params=obj.to_dict(),
        ))

    def create_object(self, shape: str = "cube", position: list[float] | None = None) -> str:
        """API programática para criar objetos (chamada pela voice control)."""
        obj_id = f"obj_{uuid.uuid4().hex[:8]}"
        pos = position or [0.0, 0.0, 0.0]
        obj = Object3D(
            id=obj_id,
            shape=shape,
            position=pos,
            rotation=[0.0, 0.0, 0.0],
            scale=[1.0, 1.0, 1.0],
        )
        self._objects[obj_id] = obj
        self._selected_id = obj_id
        self._emit(SceneCommand("create_object", obj_id, obj.to_dict()))
        return obj_id

    def _delete_selected(self, event: GestureEvent) -> None:
        if self._selected_id and self._selected_id in self._objects:
            del self._objects[self._selected_id]
            self._emit(SceneCommand("delete", self._selected_id))
            self._selected_id = None

    # ── select / grab ────────────────────────────────────────────────────
    def _select_or_grab(self, event: GestureEvent) -> None:
        self._last_pinch_pos = event.position
        # Encontrar objeto mais próximo da posição gestual
        best_id = None
        best_dist = float("inf")
        px = event.position[0] * 4 - 2
        py = event.position[1] * -4 + 2

        for obj in self._objects.values():
            d = math.sqrt((obj.position[0] - px) ** 2 + (obj.position[1] - py) ** 2)
            if d < best_dist:
                best_dist = d
                best_id = obj.id

        if best_id and best_dist < 2.0:
            self._selected_id = best_id
            self._emit(SceneCommand("select", best_id))

    def _manipulate(self, event: GestureEvent) -> None:
        if not self._selected_id or self._selected_id not in self._objects:
            return
        obj = self._objects[self._selected_id]
        obj.position = [
            event.position[0] * 4 - 2,
            event.position[1] * -4 + 2,
            event.position[2] * 4,
        ]
        self._emit(SceneCommand("translate", self._selected_id, {
            "position": obj.position,
        }))

    def _release(self, event: GestureEvent) -> None:
        self._last_pinch_pos = None

    # ── surface deformation ──────────────────────────────────────────────
    def _push_surface(self, event: GestureEvent) -> None:
        self._emit(SceneCommand("deform", self._selected_id or "", {
            "type": "push",
            "position": list(event.position),
            "force": PHYSICS_FORCE_MULTIPLIER,
            "radius": 0.5,
        }))

    def _pull_compress(self, event: GestureEvent) -> None:
        self._emit(SceneCommand("deform", self._selected_id or "", {
            "type": "pull",
            "position": list(event.position),
            "force": -PHYSICS_FORCE_MULTIPLIER,
            "radius": 0.5,
        }))

    # ── rotate ───────────────────────────────────────────────────────────
    def _rotate_object(self, event: GestureEvent) -> None:
        if not self._selected_id or self._selected_id not in self._objects:
            return
        obj = self._objects[self._selected_id]
        obj.rotation[1] += 0.3  # rotaciona no eixo Y
        self._emit(SceneCommand("rotate", self._selected_id, {
            "rotation": obj.rotation,
        }))

    # ── scale ────────────────────────────────────────────────────────────
    def _scale_mode(self, event: GestureEvent) -> None:
        if not self._selected_id or self._selected_id not in self._objects:
            return
        obj = self._objects[self._selected_id]
        factor = 1.1  # incremental scale
        obj.scale = [s * factor for s in obj.scale]
        self._emit(SceneCommand("scale", self._selected_id, {
            "scale": obj.scale,
        }))

    # ── emit ─────────────────────────────────────────────────────────────
    def _emit(self, cmd: SceneCommand) -> None:
        if self._on_command:
            try:
                self._on_command(cmd)
            except Exception:
                pass

    # ── state ────────────────────────────────────────────────────────────
    @property
    def object_count(self) -> int:
        return len(self._objects)

    @property
    def selected_object(self) -> Object3D | None:
        if self._selected_id:
            return self._objects.get(self._selected_id)
        return None

    def get_scene_state(self) -> list[dict]:
        return [obj.to_dict() for obj in self._objects.values()]
