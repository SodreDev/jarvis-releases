"""
J.A.R.V.I.S Gesture Interface — entry point.

Orquestra todos os módulos:
    - HandTracker (captura webcam local — NENHUM frame sai do processo)
    - EyeTracker (rastreamento de olhar via íris — local)
    - GestureRecognizer (detecção por TRANSIÇÃO de pose)
    - ModeClassifier
    - EventRouter
    - DesktopController
    - Canvas2DEngine
    - Workspace3DEngine
    - GestureTrainer
    - VoiceCommands
    - LiveView (tkinter — câmera + overlays + tutorial)
    - GestureUI (PyWebView — interface completa)
"""
from __future__ import annotations

import json
import sys
import threading
from typing import TYPE_CHECKING

import pyautogui

from gesture_interface.canvas2d.engine import Canvas2DEngine
from gesture_interface.config import DEFAULT_MODE
from gesture_interface.desktop_control.controller import DesktopController
from gesture_interface.gesture_engine.eye_tracker import EyeTracker, GazeData
from gesture_interface.gesture_engine.recognizer import GestureEvent, GestureRecognizer
from gesture_interface.gesture_engine.tracker import HandData, HandTracker
from gesture_interface.gesture_training.trainer import GestureTrainer
from gesture_interface.interaction.event_router import EventRouter
from gesture_interface.interaction.mode_classifier import ModeClassifier
from gesture_interface.mouse_calibration import MouseCalibration
from gesture_interface.ui.api import GestureAPI
from gesture_interface.ui.app import GestureUI
from gesture_interface.ui.live_view import LiveView
from gesture_interface.voice_control.commands import VoiceCommands
from gesture_interface.workspace3d.engine import Workspace3DEngine


class GestureSystem:
    """
    Sistema central de gestos — coordena todos os módulos.

    REGRA DE SEGURANÇA:
    Toda captura de câmera é processada LOCALMENTE pelo HandTracker.
    Nenhum frame de vídeo ou imagem é enviado para IA ou serviços externos.
    Os módulos consumidores recebem apenas coordenadas numéricas abstratas
    (GestureEvent, HandData, GazeData).
    """

    def __init__(self) -> None:
        # Core
        self.classifier = ModeClassifier()
        self.recognizer = GestureRecognizer()
        self.router = EventRouter(self.classifier)

        # Eye tracking — desativado por padrao, ativado por comando de voz
        self.eye_tracker: EyeTracker | None = None
        self._eye_control_active = False

        self.tracker = HandTracker(
            on_hands=self._on_hands,
            eye_tracker=None,
        )

        # Mouse calibration — carrega do disco automaticamente
        self.mouse_calibration = MouseCalibration()

        # Modules
        self.desktop = DesktopController(calibration=self.mouse_calibration)
        self.canvas2d = Canvas2DEngine()
        self.workspace3d = Workspace3DEngine()
        self.trainer = GestureTrainer()
        self.voice = VoiceCommands(self.classifier)

        # Register modules with the router
        self.router.register("desktop", self.desktop)
        self.router.register("canvas2d", self.canvas2d)
        self.router.register("workspace3d", self.workspace3d)

        # UI
        self._api = GestureAPI()
        self._ui = GestureUI(self._api)

        # Live View (tkinter — câmera em tempo real)
        self.live_view = LiveView(
            self.tracker, self.recognizer, None,
            mouse_calibration=self.mouse_calibration,
        )

        # Wire canvas/3D callbacks to push commands to frontend via JS bridge
        self.canvas2d.set_callback(self._on_canvas_command)
        self.workspace3d.set_callback(self._on_scene_command)

        # Gesture recognizer callback → router
        self.recognizer.set_callback(self._on_gesture)

        # Mode change listener
        self.classifier.on_change(self._on_mode_change)

        # Screen size for eye gaze
        self._screen_w, self._screen_h = pyautogui.size()

    # ── Pipeline: tracker → recognizer → router → modules ───────────
    def _on_hands(self, hands: list[HandData]) -> None:
        """Chamado pelo HandTracker a cada frame com landmarks detectados."""
        events = self.recognizer.process(hands)
        for h in hands:
            self.trainer.process_hand_for_matching(h)

    def _on_gesture(self, event: GestureEvent) -> None:
        """Chamado pelo GestureRecognizer para cada gesto detectado."""
        self.router.route(event)

        # Log no live view
        self.live_view.log_action(
            f"{event.gesture.name} ({event.hand})", "#00e6ff"
        )

        # Push gesture event to UI log via JS
        self._push_js(f"GestureApp.addLog('{event.gesture.name} ({event.hand})', 'gesture')")

    def _on_gaze(self, gaze: GazeData) -> None:
        """Chamado pelo EyeTracker a cada frame com dados de olhar."""
        if not self._eye_control_active or gaze.confidence <= 0:
            return

        # Se mouse mode (2 dedos) estiver ativo, NÃO mover cursor pelo olhar
        # Mas continuar processando wink/eyebrow para cliques
        hand_cursor_active = self.recognizer.in_mouse_mode

        if not hand_cursor_active:
            # Mover cursor para onde o olhar aponta
            x = int(gaze.screen_x * self._screen_w)
            y = int(gaze.screen_y * self._screen_h)
            x = max(0, min(x, self._screen_w - 1))
            y = max(0, min(y, self._screen_h - 1))
            pyautogui.moveTo(x, y, _pause=False)

        # Piscar forte (wink) → clique esquerdo
        if gaze.wink_left or gaze.wink_right:
            pyautogui.click(_pause=False)
            side = "esquerdo" if gaze.wink_left else "direito"
            self.live_view.log_action(f"Wink {side} → Click", "#ffaa00")

        # Levantar sobrancelhas → clique direito
        if gaze.eyebrows_raised:
            pyautogui.click(button="right", _pause=False)
            self.live_view.log_action("Sobrancelhas → Right Click", "#ff6600")

    # ── JS bridge ────────────────────────────────────────────────────
    def _on_canvas_command(self, cmd) -> None:
        data = json.dumps(cmd.to_dict())
        self._push_js(f"if(typeof Canvas2D !== 'undefined') Canvas2D.executeCommand({data})")

    def _on_scene_command(self, cmd) -> None:
        data = json.dumps(cmd.to_dict())
        self._push_js(f"if(typeof Workspace3D !== 'undefined') Workspace3D.handleCommand({data})")

    def _on_mode_change(self, mode: str, state) -> None:
        self._push_js(f"GestureApp.updateModeUI('{mode}')")
        # Auto-launch 3D viewport only when explicitly entering design3d mode
        if mode == "design3d":
            self._open_3d_viewport()

    def _open_3d_viewport(self) -> None:
        """Abre o Workspace 3D no navegador do sistema."""
        import webbrowser
        from pathlib import Path
        html = Path(__file__).resolve().parent / "ui" / "templates" / "workspace3d.html"
        webbrowser.open(html.as_uri())

    def _push_js(self, script: str) -> None:
        self._ui.evaluate_js(script)

    # ── Lifecycle ────────────────────────────────────────────────────
    def start(self, start_tracker: bool = True) -> None:
        """Inicia o sistema. Chame live_view.run() logo depois (na main thread) para abrir a UI."""
        if start_tracker:
            self.tracker.start()
        self.classifier.set_mode(DEFAULT_MODE)

    def start_with_webview(self, start_tracker: bool = True) -> None:
        """Inicia com a interface PyWebView completa (bloqueia thread)."""
        if start_tracker:
            self.tracker.start()
        self.classifier.set_mode(DEFAULT_MODE)
        self.live_view.start()  # thead secundária (webview ocupa a main thread)
        self._ui.start(self)

    def start_headless(self, start_tracker: bool = True) -> None:
        """Inicia sem UI (para integração com o Jarvis existente)."""
        if start_tracker:
            self.tracker.start()
        self.classifier.set_mode(DEFAULT_MODE)

    def start_live_view(self) -> None:
        """Inicia apenas o Live View (para quem já tem o tracker rodando)."""
        self.live_view.start()

    # ── Eye control (ativado separadamente por comando de voz) ───────
    def enable_eye_control(self) -> str:
        """Ativa controle do cursor pela direção da cabeça."""
        if self._eye_control_active:
            return "Controle pelo olho já está ativo, Senhor."
        self.eye_tracker = EyeTracker(on_gaze=self._on_gaze)
        self.eye_tracker.initialize()
        self.tracker.set_eye_tracker(self.eye_tracker)
        self.live_view.set_eye_tracker(self.eye_tracker)
        self._eye_control_active = True
        if self.eye_tracker.state.calibrated:
            return "Controle pelo olho ativado com calibração salva, Senhor."
        return "Controle pelo olho ativado, Senhor. Use 'calibrar olhos' para calibrar."

    def disable_eye_control(self) -> str:
        """Desativa controle do cursor pelo olhar."""
        if not self._eye_control_active:
            return "Controle pelo olho não está ativo, Senhor."
        self._eye_control_active = False
        self.tracker.set_eye_tracker(None)
        self.live_view.set_eye_tracker(None)
        if self.eye_tracker:
            self.eye_tracker.close()
            self.eye_tracker = None
        return "Controle pelo olho desativado, Senhor."

    def start_eye_calibration(self) -> str:
        """Inicia calibração sweep do eye tracker."""
        if not self._eye_control_active or self.eye_tracker is None:
            return "Ative o controle pelo olho primeiro com 'ativar controle pelo olho'."
        self.live_view.start_calibration()
        return "Calibração iniciada. Siga o ponto com o rosto."

    def stop(self) -> None:
        """Para todos os módulos."""
        self.live_view.stop()
        self.tracker.stop()
        if self.eye_tracker:
            self.eye_tracker.close()


def main() -> None:
    """Entry point standalone — abre Live View com câmera."""
    import argparse
    parser = argparse.ArgumentParser(description="J.A.R.V.I.S Gesture Interface")
    parser.add_argument("--webview", action="store_true",
                        help="Abre também a interface PyWebView")
    args = parser.parse_args()

    system = GestureSystem()
    try:
        if args.webview:
            system.start_with_webview()  # webview ocupa main thread, ui em secundária
        else:
            # Iniciar tracker (thread secundária) antes de bloquear na UI
            system.start(start_tracker=True)
            # live_view.run() bloqueia na main thread — Tkinter requer isso
            system.live_view.run()
    except KeyboardInterrupt:
        pass
    finally:
        system.stop()


if __name__ == "__main__":
    main()
