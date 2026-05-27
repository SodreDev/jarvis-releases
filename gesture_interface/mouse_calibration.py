"""
Calibração do cursor de mouse para gestos de mão.

Mapeia a posição do dedo indicador no espaço da câmera para as coordenadas
reais da tela, eliminando a distorção perspectiva/margem e as diferenças
de posicionamento físico da câmera.

Fluxo:
    1. Mostrar 4 pontos de canto (ou 9 pontos em grade) na tela.
    2. Usuário aponta o indicador para cada ponto e mantém estável 1,5 s.
    3. Registrar a posição bruta do indicador no espaço de câmera (display).
    4. Computar transform perspectiva 4-pontos via cv2.getPerspectiveTransform.
    5. Salvar em JSON para reaproveitar nas próximas sessões.

Coordenadas:
    - "camera display X" = 1.0 - index_tip[0]  (espelho, igual ao controlador)
    - "camera display Y" = index_tip[1]
    - Saída: screen_x, screen_y em range [0, 1]
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np

_SAVE_PATH = Path(__file__).resolve().parent / "gesture_data" / "mouse_calibration.json"

# Pontos de referência da tela (normalizados 0-1) — cantos com pequena margem
# Ordem: topo-esq, topo-dir, base-dir, base-esq
_SCREEN_CORNERS: list[tuple[float, float]] = [
    (0.10, 0.10),  # topo-esquerda
    (0.90, 0.10),  # topo-direita
    (0.90, 0.90),  # base-direita
    (0.10, 0.90),  # base-esquerda
]


class MouseCalibration:
    """Gerencia a calibração câmera→tela para o cursor gestual."""

    def __init__(self) -> None:
        self._transform: np.ndarray | None = None   # 3×3 homografia
        self._calibrated: bool = False
        self.load()

    # ── Estado ───────────────────────────────────────────────────────────
    @property
    def calibrated(self) -> bool:
        return self._calibrated

    @property
    def screen_corners(self) -> list[tuple[float, float]]:
        """Retorna os pontos da tela usados na calibração."""
        return list(_SCREEN_CORNERS)

    # ── Mapeamento ───────────────────────────────────────────────────────
    def map_point(self, display_x: float, display_y: float) -> tuple[float, float]:
        """
        Mapeia coordenada de câmera (display) para coordenada de tela.

        Args:
            display_x: 1.0 - index_tip[0]  (já espelhado)
            display_y: index_tip[1]
        Returns:
            (screen_x, screen_y) normalizados [0, 1]
        """
        if not self._calibrated or self._transform is None:
            # Sem calibração: usar mapeamento linear simples (identidade)
            return float(np.clip(display_x, 0.0, 1.0)), float(np.clip(display_y, 0.0, 1.0))

        pt = np.array([[[display_x, display_y]]], dtype=np.float32)
        result = cv2.perspectiveTransform(pt, self._transform)
        sx = float(np.clip(result[0, 0, 0], 0.0, 1.0))
        sy = float(np.clip(result[0, 0, 1], 0.0, 1.0))
        return sx, sy

    # ── Calibração ───────────────────────────────────────────────────────
    def calibrate(
        self,
        cam_display_points: list[tuple[float, float]],
    ) -> bool:
        """
        Calcula o transform a partir de 4 pares de pontos.

        Args:
            cam_display_points: posições capturadas para cada _SCREEN_CORNERS[i]
                                 em coordenadas "display" (1.0 - raw_x, raw_y)
        Returns:
            True se a calibração foi aplicada com sucesso.
        """
        if len(cam_display_points) < 4:
            return False

        src = np.array(cam_display_points[:4], dtype=np.float32)
        dst = np.array(_SCREEN_CORNERS[:4], dtype=np.float32)

        # Verificar que os pontos de câmera não são degenerados (colineares)
        if _is_degenerate(src):
            return False

        try:
            self._transform = cv2.getPerspectiveTransform(src, dst)
            self._calibrated = True
            self.save()
            return True
        except cv2.error:
            return False

    def reset(self) -> None:
        """Remove a calibração atual."""
        self._transform = None
        self._calibrated = False
        if _SAVE_PATH.exists():
            try:
                _SAVE_PATH.unlink()
            except OSError:
                pass

    # ── Persistência ─────────────────────────────────────────────────────
    def save(self) -> None:
        if self._transform is None:
            return
        data = {
            "transform": self._transform.tolist(),
            "calibrated": self._calibrated,
            "screen_corners": _SCREEN_CORNERS,
        }
        try:
            _SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _SAVE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def load(self) -> None:
        try:
            if not _SAVE_PATH.exists():
                return
            data = json.loads(_SAVE_PATH.read_text(encoding="utf-8"))
            self._transform = np.array(data["transform"], dtype=np.float32)
            self._calibrated = bool(data.get("calibrated", True))
        except Exception:
            self._transform = None
            self._calibrated = False


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_degenerate(pts: np.ndarray, min_area: float = 0.01) -> bool:
    """Verifica se os 4 pontos formam um quadrilátero com área mínima."""
    try:
        area = math.fabs(
            cv2.contourArea(pts.reshape(4, 1, 2))
        )
        return area < min_area
    except Exception:
        return True
