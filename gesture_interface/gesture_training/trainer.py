"""
Gesture trainer — gravação e reconhecimento de gestos customizados via DTW.

Workflow:
    1. Usuário escolhe uma ação destino
    2. Inicia gravação (record_start)
    3. Movimento é capturado como sequência de landmarks
    4. Padrão é salvo localmente em gestures.json
    5. No reconhecimento, compara DTW com padrões salvos

Usa Dynamic Time Warping (DTW) simplificado para matching de sequências.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from gesture_interface.config import DTW_MATCH_THRESHOLD, TRAINING_MAX_FRAMES
from gesture_interface.gesture_engine.tracker import HandData

_GESTURES_FILE = Path(__file__).resolve().parent.parent / "gesture_data" / "custom_gestures.json"


@dataclass
class CustomGesture:
    """Um gesto customizado gravado pelo usuário."""
    name: str
    action: str                        # ação a executar quando reconhecido
    sequence: list[list[float]]        # lista de (21*3=63) valores flatten por frame
    created_at: str = ""

    def to_dict(self) -> dict:
        return self.__dict__

    @classmethod
    def from_dict(cls, d: dict) -> CustomGesture:
        return cls(**d)


class GestureTrainer:
    """Grava, salva e reconhece gestos customizados."""

    def __init__(self, on_match: Callable[[str, str, float], None] | None = None) -> None:
        """
        on_match: callback(gesture_name, action, score) quando um gesto é reconhecido.
        """
        self._on_match = on_match
        self._gestures: list[CustomGesture] = []
        self._recording: bool = False
        self._record_buffer: list[list[float]] = []
        self._record_action: str = ""
        self._record_name: str = ""
        self._lock = threading.Lock()
        self._load()

    # ── persistence ──────────────────────────────────────────────────────
    def _load(self) -> None:
        if _GESTURES_FILE.exists():
            try:
                data = json.loads(_GESTURES_FILE.read_text(encoding="utf-8"))
                self._gestures = [CustomGesture.from_dict(g) for g in data]
            except Exception:
                self._gestures = []

    def _save(self) -> None:
        _GESTURES_FILE.parent.mkdir(parents=True, exist_ok=True)
        _GESTURES_FILE.write_text(
            json.dumps([g.to_dict() for g in self._gestures], indent=2),
            encoding="utf-8",
        )

    # ── recording ────────────────────────────────────────────────────────
    def record_start(self, name: str, action: str) -> None:
        """Inicia gravação de um novo gesto."""
        with self._lock:
            self._recording = True
            self._record_buffer = []
            self._record_name = name
            self._record_action = action

    def record_frame(self, hand: HandData) -> bool:
        """Adiciona um frame à gravação. Retorna False se gravação terminou."""
        with self._lock:
            if not self._recording:
                return False
            flat = hand.landmarks.flatten().tolist()
            self._record_buffer.append(flat)
            if len(self._record_buffer) >= TRAINING_MAX_FRAMES:
                self._recording = False
                return False
            return True

    def record_stop(self) -> CustomGesture | None:
        """Para a gravação e salva o gesto."""
        with self._lock:
            if not self._record_buffer:
                self._recording = False
                return None

            # Normalizar sequência (centralizar no wrist, normalizar escala)
            seq = self._normalize_sequence(self._record_buffer)

            gesture = CustomGesture(
                name=self._record_name,
                action=self._record_action,
                sequence=seq,
                created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            self._gestures.append(gesture)
            self._recording = False
            self._record_buffer = []

        self._save()
        return gesture

    @property
    def is_recording(self) -> bool:
        return self._recording

    # ── recognition ──────────────────────────────────────────────────────
    def match(self, sequence: list[list[float]]) -> tuple[str, str, float] | None:
        """
        Compara uma sequência observada com os gestos salvos via DTW.
        Retorna (name, action, score) ou None se nenhum match.
        """
        if not self._gestures or len(sequence) < 5:
            return None

        seq_norm = self._normalize_sequence(sequence)
        best_score = float("inf")
        best_gesture: CustomGesture | None = None

        for g in self._gestures:
            score = self._dtw_distance(seq_norm, g.sequence)
            if score < best_score:
                best_score = score
                best_gesture = g

        if best_gesture and best_score < DTW_MATCH_THRESHOLD:
            if self._on_match:
                self._on_match(best_gesture.name, best_gesture.action, best_score)
            return (best_gesture.name, best_gesture.action, best_score)

        return None

    def process_hand_for_matching(self, hand: HandData) -> None:
        """Feed contínuo de frames para matching em tempo real."""
        if self._recording:
            self.record_frame(hand)

    # ── DTW ──────────────────────────────────────────────────────────────
    @staticmethod
    def _dtw_distance(seq_a: list[list[float]], seq_b: list[list[float]]) -> float:
        """Dynamic Time Warping simplificado com janela de Sakoe-Chiba."""
        n, m = len(seq_a), len(seq_b)
        if n == 0 or m == 0:
            return float("inf")

        window = max(n, m) // 3 + 1
        cost = np.full((n + 1, m + 1), np.inf)
        cost[0, 0] = 0.0

        a = np.array(seq_a)
        b = np.array(seq_b)

        for i in range(1, n + 1):
            j_start = max(1, i - window)
            j_end = min(m, i + window)
            for j in range(j_start, j_end + 1):
                d = float(np.linalg.norm(a[i - 1] - b[j - 1]))
                cost[i, j] = d + min(cost[i - 1, j], cost[i, j - 1], cost[i - 1, j - 1])

        return float(cost[n, m]) / max(n, m)

    # ── normalization ────────────────────────────────────────────────────
    @staticmethod
    def _normalize_sequence(seq: list[list[float]]) -> list[list[float]]:
        """Centraliza cada frame no wrist e normaliza escala pela distância wrist→middle_mcp."""
        result = []
        for frame in seq:
            arr = np.array(frame).reshape(21, 3)
            wrist = arr[0].copy()
            arr -= wrist                          # centraliza no wrist
            scale = np.linalg.norm(arr[9])        # middle_finger_mcp
            if scale > 1e-6:
                arr /= scale
            result.append(arr.flatten().tolist())
        return result

    # ── management ───────────────────────────────────────────────────────
    def list_gestures(self) -> list[dict]:
        return [{"name": g.name, "action": g.action, "frames": len(g.sequence),
                 "created_at": g.created_at} for g in self._gestures]

    def delete_gesture(self, name: str) -> bool:
        before = len(self._gestures)
        self._gestures = [g for g in self._gestures if g.name != name]
        if len(self._gestures) < before:
            self._save()
            return True
        return False
