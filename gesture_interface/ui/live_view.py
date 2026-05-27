"""
Live View — UI com câmera em tempo real, overlays de tracking e tutoriais.

Interface tkinter que mostra:
    - Feed da câmera com landmarks das mãos e olhos desenhados
    - Gesto atual detectado e indicador de transição
    - Ponto de olhar (gaze) na tela
    - Menu lateral com tutorial dos gestos
    - Log de ações executadas
    - Controles de configuração
"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

import cv2
import numpy as np
from PIL import Image, ImageTk

from gesture_interface.config import (
    LIVE_VIEW_CAMERA_W,
    LIVE_VIEW_FPS,
    LIVE_VIEW_HEIGHT,
    LIVE_VIEW_SIDEBAR_W,
    LIVE_VIEW_WIDTH,
)

if TYPE_CHECKING:
    from gesture_interface.gesture_engine.eye_tracker import EyeTracker, GazeData
    from gesture_interface.gesture_engine.recognizer import GestureEvent, GestureRecognizer
    from gesture_interface.gesture_engine.tracker import HandTracker
    from gesture_interface.mouse_calibration import MouseCalibration

# ── Cores do tema ────────────────────────────────────────────────────────────
_BG = "#0a0e14"
_BG_PANEL = "#111820"
_BG_CARD = "#162030"
_CYAN = "#00e6ff"
_GREEN = "#00ff88"
_ORANGE = "#ff8800"
_RED = "#ff3355"
_PINK = "#ff44aa"
_PURPLE = "#aa44ff"
_WHITE = "#e0e8f0"
_DIM = "#556680"
_BORDER = "#1a2a3a"

# Cores dos overlays OpenCV (BGR)
_OCV_CYAN = (255, 230, 0)
_OCV_GREEN = (136, 255, 0)
_OCV_RED = (51, 51, 255)
_OCV_YELLOW = (0, 220, 255)
_OCV_PINK = (180, 68, 255)
_OCV_WHITE = (240, 232, 224)

# Conexões dos landmarks da mão para desenhar linhas
_HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),        # polegar
    (0, 5), (5, 6), (6, 7), (7, 8),        # indicador
    (0, 9), (9, 10), (10, 11), (11, 12),   # médio
    (0, 13), (13, 14), (14, 15), (15, 16), # anelar
    (0, 17), (17, 18), (18, 19), (19, 20), # mindinho
    (5, 9), (9, 13), (13, 17),             # palma
]

# ── Tutorial dos gestos ─────────────────────────────────────────────────────
_GESTURE_TUTORIALS = [
    {
        "name": "📱 Trocar Desktop",
        "action": "Win+Ctrl+← / Win+Ctrl+→",
        "how": "Mover a mão RAPIDAMENTE para esquerda ou direita.\nQualquer pose de mão funciona.",
        "wrong": "❌ Movimento muito lento\n❌ Mão já em outro gesto",
        "color": _PURPLE,
    },
    {
        "name": "📱 Seletor de Janelas (Win+Tab)",
        "action": "Navegar e selecionar janelas abertas",
        "how": "1️⃣ FECHAR o punho (manter 0,5s)\n2️⃣ ABRIR a mão completamente\nInicia o Win+Tab\n\nNavegar: mover a mão ←→↓\nSelecionar: fechar o punho novamente",
        "wrong": "❌ Abrir sem fechar o punho antes\n❌ Fechar lentamente (dedo por dedo)",
        "color": _CYAN,
    },
    {
        "name": "🔄 Minimizar Janela",
        "action": "Minimiza a janela ativa (Win+↓)",
        "how": "Com a PALMA virada para a câmera:\n1️⃣ Virar a mão (palma para longe)\n2️⃣ Voltar a mão para a posição normal\nComo uma mão se despedindo.",
        "wrong": "❌ Não completar o retorno\n❌ Virar muito devagar (deve ser claro)",
        "color": _GREEN,
    },
    {
        "name": "🔄 Minimizar Tudo",
        "action": "Mostrar área de trabalho (Win+D)",
        "how": "Mesmo gesto anterior mas com AS DUAS MÃOS.\nAmbas viram e retornam juntas\n(dentro de 1,5 segundos uma da outra).",
        "wrong": "❌ Fazer só uma mão\n❌ Uma mão antes e outra muito depois",
        "color": _ORANGE,
    },
    {
        "name": "✊ Alt+F4 (Pedra no Papel)",
        "action": "Fechar o app ativo (Alt+F4)",
        "how": "Mão A: punho fechado (pedra)\nMão B: palm aberta (papel)\nAproximar as mãos e manter\nproximas por 0,5 segundos.",
        "wrong": "❌ Mãos muito distantes\n❌ Usar apenas uma mão",
        "color": _RED,
    },
]


class LiveView:
    """
    Janela tkinter com visualização em tempo real da câmera e tracking.
    """

    def __init__(self, tracker: HandTracker, recognizer: GestureRecognizer,
                 eye_tracker: EyeTracker | None = None,
                 mouse_calibration: "MouseCalibration | None" = None):
        self._tracker = tracker
        self._recognizer = recognizer
        self._eye_tracker = eye_tracker
        self._mouse_calibration = mouse_calibration
        self._running = False
        self._root: tk.Tk | None = None
        self._thread: threading.Thread | None = None
        self._action_log: list[tuple[float, str, str]] = []  # (time, gesture, color)
        self._max_log = 50
        self._after_id: str | None = None   # handle do after() agendado

    def set_eye_tracker(self, eye_tracker: EyeTracker | None) -> None:
        """Define ou remove o eye tracker dinamicamente."""
        self._eye_tracker = eye_tracker

    # ── Lifecycle ────────────────────────────────────────────────────────
    def run(self) -> None:
        """Inicia e BLOQUEIA na thread chamadora (deve ser a main thread).
        Tkinter exige que tk.Tk() e mainloop() rodem na main thread;
        rodar em thread secundária causa Variable.__del__ RTError e
        Tcl_AsyncDelete crash."""
        if self._running:
            return
        self._running = True
        try:
            self._run_ui()
        finally:
            self._running = False

    def start(self) -> None:
        """Compat: inicia em thread secundária (usar run() de preferência).
        Mantido apenas para código que não controla a main thread (p.ex. webview)."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_ui, daemon=True, name="live-view")
        self._thread.start()

    def stop(self) -> None:
        """Para o live view a partir de qualquer thread."""
        self._running = False
        root = self._root
        self._root = None   # impede novos after() de outras threads
        if root:
            try:
                root.after(0, root.destroy)
            except Exception:
                pass

    def log_action(self, text: str, color: str = _CYAN) -> None:
        self._action_log.append((time.perf_counter(), text, color))
        if len(self._action_log) > self._max_log:
            self._action_log = self._action_log[-self._max_log:]

    def start_calibration(self) -> None:
        """Dispara calibração a partir de qualquer thread."""
        if self._root and self._running:
            self._root.after(0, self._start_calibration)

    # ── UI construction ──────────────────────────────────────────────────
    def _run_ui(self) -> None:
        self._root = tk.Tk()
        self._root.title("J.A.R.V.I.S — Gesture Tracking")
        self._root.geometry(f"{LIVE_VIEW_WIDTH}x{LIVE_VIEW_HEIGHT}")
        self._root.configure(bg=_BG)
        self._root.resizable(True, True)
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Estilo ttk
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.TFrame", background=_BG)
        style.configure("Panel.TFrame", background=_BG_PANEL)
        style.configure("Card.TFrame", background=_BG_CARD)
        style.configure("Dark.TLabel", background=_BG, foreground=_WHITE, font=("Consolas", 10))
        style.configure("Title.TLabel", background=_BG_PANEL, foreground=_CYAN,
                        font=("Consolas", 14, "bold"))
        style.configure("Subtitle.TLabel", background=_BG_PANEL, foreground=_WHITE,
                        font=("Consolas", 11, "bold"))
        style.configure("Dim.TLabel", background=_BG_PANEL, foreground=_DIM,
                        font=("Consolas", 9))
        style.configure("Status.TLabel", background=_BG, foreground=_GREEN,
                        font=("Consolas", 12, "bold"))

        # Layout principal: câmera | sidebar
        main_frame = ttk.Frame(self._root, style="Dark.TFrame")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ── Painel da câmera ─────────────────────────────────────────────
        cam_frame = ttk.Frame(main_frame, style="Dark.TFrame")
        cam_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Header com status
        header = ttk.Frame(cam_frame, style="Dark.TFrame")
        header.pack(fill=tk.X, pady=(0, 4))

        self._lbl_status = ttk.Label(header, text="⏳ Aguardando câmera...",
                                     style="Status.TLabel")
        self._lbl_status.pack(side=tk.LEFT)

        self._lbl_fps = ttk.Label(header, text="FPS: --", style="Dark.TLabel")
        self._lbl_fps.pack(side=tk.RIGHT)

        self._lbl_gesture = ttk.Label(header, text="", style="Dark.TLabel")
        self._lbl_gesture.pack(side=tk.RIGHT, padx=20)

        # Canvas para a câmera
        self._canvas = tk.Canvas(cam_frame, bg="#000000", highlightthickness=1,
                                 highlightbackground=_BORDER)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._photo: ImageTk.PhotoImage | None = None

        # Barra inferior com controles
        ctrl_frame = ttk.Frame(cam_frame, style="Dark.TFrame")
        ctrl_frame.pack(fill=tk.X, pady=(4, 0))

        self._eye_var = tk.BooleanVar(value=self._eye_tracker is not None)
        eye_cb = tk.Checkbutton(ctrl_frame, text="👁 Eye Tracking",
                                variable=self._eye_var,
                                bg=_BG, fg=_GREEN, selectcolor=_BG_PANEL,
                                activebackground=_BG, activeforeground=_GREEN,
                                font=("Consolas", 10))
        eye_cb.pack(side=tk.LEFT, padx=8)

        cal_btn = tk.Button(ctrl_frame, text="🎯 Calibrar Olhos",
                            command=self._start_calibration,
                            bg=_BG_CARD, fg=_CYAN, activebackground=_BG_PANEL,
                            activeforeground=_CYAN, bd=1, relief=tk.FLAT,
                            font=("Consolas", 10))
        cal_btn.pack(side=tk.LEFT, padx=4)

        self._lbl_gaze = ttk.Label(ctrl_frame, text="Olhar: --", style="Dark.TLabel")
        self._lbl_gaze.pack(side=tk.RIGHT, padx=8)

        # ── Sidebar ─────────────────────────────────────────────────────
        sidebar = ttk.Frame(main_frame, style="Panel.TFrame", width=LIVE_VIEW_SIDEBAR_W)
        sidebar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4), pady=4)
        sidebar.pack_propagate(False)

        # Notebook com abas
        notebook = ttk.Notebook(sidebar)
        notebook.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # ── Aba: Tutorial ────────────────────────────────────────────────
        tutorial_frame = ttk.Frame(notebook, style="Panel.TFrame")
        notebook.add(tutorial_frame, text="📖 Tutorial")

        tutorial_canvas = tk.Canvas(tutorial_frame, bg=_BG_PANEL,
                                    highlightthickness=0)
        tutorial_scroll = ttk.Scrollbar(tutorial_frame, orient=tk.VERTICAL,
                                        command=tutorial_canvas.yview)
        tutorial_inner = ttk.Frame(tutorial_canvas, style="Panel.TFrame")

        tutorial_inner.bind("<Configure>",
                            lambda e: tutorial_canvas.configure(
                                scrollregion=tutorial_canvas.bbox("all")))
        tutorial_canvas.create_window((0, 0), window=tutorial_inner, anchor="nw")
        tutorial_canvas.configure(yscrollcommand=tutorial_scroll.set)

        tutorial_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tutorial_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Bind mousewheel para scroll
        def _on_mousewheel(event):
            tutorial_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        tutorial_canvas.bind_all("<MouseWheel>", _on_mousewheel)

        for tut in _GESTURE_TUTORIALS:
            self._create_tutorial_card(tutorial_inner, tut)

        # ── Aba: Ações ───────────────────────────────────────────────────
        log_frame = ttk.Frame(notebook, style="Panel.TFrame")
        notebook.add(log_frame, text="📋 Ações")

        ttk.Label(log_frame, text="Últimas Ações Detectadas",
                  style="Title.TLabel").pack(pady=(8, 4), padx=8)

        self._log_text = tk.Text(log_frame, bg=_BG_CARD, fg=_WHITE,
                                 font=("Consolas", 9), wrap=tk.WORD,
                                 state=tk.DISABLED, bd=0,
                                 highlightthickness=1,
                                 highlightbackground=_BORDER)
        self._log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # Tags de cor para o log
        self._log_text.tag_configure("cyan", foreground=_CYAN)
        self._log_text.tag_configure("green", foreground=_GREEN)
        self._log_text.tag_configure("red", foreground=_RED)
        self._log_text.tag_configure("orange", foreground=_ORANGE)
        self._log_text.tag_configure("dim", foreground=_DIM)

        # ── Aba: Config ──────────────────────────────────────────────────
        config_frame = ttk.Frame(notebook, style="Panel.TFrame")
        notebook.add(config_frame, text="⚙ Config")

        ttk.Label(config_frame, text="Configurações",
                  style="Title.TLabel").pack(pady=(8, 12), padx=8)

        self._create_config_panel(config_frame)

        # Iniciar loop de atualização
        self._update_interval = max(1, 1000 // LIVE_VIEW_FPS)
        self._last_loop_tick = time.perf_counter()
        self._root.bind("<Map>", self._on_window_restore)
        # Forçar paint inicial para janela aparecer imediatamente
        self._root.update_idletasks()
        self._after_id = self._root.after(50, self._update_loop)

        try:
            self._root.mainloop()
        except Exception:
            pass
        finally:
            self._running = False

    def _create_tutorial_card(self, parent: ttk.Frame, tut: dict) -> None:
        """Cria um card de tutorial para um gesto."""
        card = tk.Frame(parent, bg=_BG_CARD, highlightthickness=1,
                        highlightbackground=tut["color"])
        card.pack(fill=tk.X, padx=8, pady=4)

        # Título
        name_lbl = tk.Label(card, text=tut["name"], bg=_BG_CARD,
                            fg=tut["color"], font=("Consolas", 11, "bold"),
                            anchor="w")
        name_lbl.pack(fill=tk.X, padx=8, pady=(6, 0))

        # Ação
        action_lbl = tk.Label(card, text=f"→ {tut['action']}", bg=_BG_CARD,
                              fg=_WHITE, font=("Consolas", 9),
                              anchor="w")
        action_lbl.pack(fill=tk.X, padx=8, pady=(2, 0))

        # Como fazer
        how_lbl = tk.Label(card, text=f"✅ {tut['how']}", bg=_BG_CARD,
                           fg=_GREEN, font=("Consolas", 9),
                           anchor="w", justify=tk.LEFT)
        how_lbl.pack(fill=tk.X, padx=8, pady=(4, 0))

        # Erros comuns
        wrong_lbl = tk.Label(card, text=tut["wrong"], bg=_BG_CARD,
                             fg=_RED, font=("Consolas", 9),
                             anchor="w", justify=tk.LEFT)
        wrong_lbl.pack(fill=tk.X, padx=8, pady=(2, 6))

    def _create_config_panel(self, parent: ttk.Frame) -> None:
        """Cria o painel de configurações."""
        configs = [
            ("Confiança mínima", "0.7"),
            ("Cooldown (seg)", "0.25"),
            ("Frames de confirmação", "3"),
            ("Suavização olhar", "5 frames"),
        ]
        for label, value in configs:
            row = ttk.Frame(parent, style="Panel.TFrame")
            row.pack(fill=tk.X, padx=12, pady=3)
            ttk.Label(row, text=label, style="Dim.TLabel").pack(side=tk.LEFT)
            ttk.Label(row, text=value, style="Dark.TLabel").pack(side=tk.RIGHT)

        # Separador
        tk.Frame(parent, bg=_BORDER, height=1).pack(fill=tk.X, padx=12, pady=8)

        # Legenda das cores do overlay
        ttk.Label(parent, text="Cores do Overlay",
                  style="Subtitle.TLabel").pack(padx=12, anchor="w")
        legend = [
            ("●  Landmarks mão", _CYAN),
            ("●  Conexões", _GREEN),
            ("●  Direção do rosto", _PINK),
            ("●  Ponto de olhar", _ORANGE),
        ]
        for text, color in legend:
            lbl = tk.Label(parent, text=text, bg=_BG_PANEL,
                           fg=color, font=("Consolas", 10), anchor="w")
            lbl.pack(fill=tk.X, padx=16, pady=1)

    # ── Update loop ──────────────────────────────────────────────────────
    def _update_loop(self) -> None:
        self._after_id = None   # limpar handle ao entrar no callback
        if not self._running:
            return

        self._last_loop_tick = time.perf_counter()

        try:
            self._update_camera()
            self._update_status()
            self._update_log()
        except Exception:
            pass

        if self._root and self._running:
            try:
                self._after_id = self._root.after(self._update_interval, self._update_loop)
            except Exception:
                pass  # Root destruído durante minimize — loop para limpo

    def _on_window_restore(self, _event=None) -> None:
        """Reinicia o update loop se ele parou enquanto a janela estava minimizada."""
        if not self._running or not self._root:
            return
        # Se o loop não executou nos últimos 0.5s, ele morreu — reiniciar
        if time.perf_counter() - self._last_loop_tick > 0.5:
            # Cancelar after() pendente antes de reiniciar para evitar loop duplo
            if self._after_id:
                try:
                    self._root.after_cancel(self._after_id)
                except Exception:
                    pass
                self._after_id = None
            self._after_id = self._root.after(50, self._update_loop)

    def _update_camera(self) -> None:
        """Atualiza o frame da câmera com overlays."""
        frame = self._tracker.state.get_frame()
        if frame is None:
            return

        h, w = frame.shape[:2]
        canvas_w = self._canvas.winfo_width()
        canvas_h = self._canvas.winfo_height()
        if canvas_w < 10 or canvas_h < 10:
            return

        # Frame já chega espelhado do tracker — não reflip aqui

        # ── Desenhar landmarks das mãos ──────────────────────────────────
        hands = self._tracker.state.snapshot()
        for hand in hands:
            lms = hand.landmarks
            for i, (x, y, z) in enumerate(lms):
                # Invertido porque já espelhamos o frame
                px = int(x * w)
                py = int(y * h)
                # Ponta dos dedos → ponto maior
                r = 5 if i in (4, 8, 12, 16, 20) else 3
                color = _OCV_CYAN if i in (4, 8, 12, 16, 20) else _OCV_GREEN
                cv2.circle(frame, (px, py), r, color, -1)

            # Desenhar conexões
            for a, b in _HAND_CONNECTIONS:
                ax, ay = int(lms[a][0] * w), int(lms[a][1] * h)
                bx, by = int(lms[b][0] * w), int(lms[b][1] * h)
                cv2.line(frame, (ax, ay), (bx, by), _OCV_GREEN, 1, cv2.LINE_AA)

            # Label da mão
            wx, wy = int(lms[0][0] * w), int(lms[0][1] * h) - 15
            label = hand.handedness
            cv2.putText(frame, label, (wx, wy), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, _OCV_CYAN, 1, cv2.LINE_AA)

        # ── Desenhar eye tracking (direção do rosto) ────────────────────
        if self._eye_tracker and self._eye_var.get():
            gaze = self._eye_tracker.state.snapshot()
            face_lms = self._eye_tracker.state.get_raw_landmarks()

            # Desenhar landmarks faciais chave + seta de direção
            if face_lms and len(face_lms) > 0:
                fl = face_lms[0]
                # Nariz (ponto 1) — âncora da seta de direção
                if len(fl) > 1:
                    nx = int(fl[1].x * w)  # frame já espelhado
                    ny = int(fl[1].y * h)
                    cv2.circle(frame, (nx, ny), 5, _OCV_PINK, -1)

                    # Seta indicando direção do rosto (yaw/pitch)
                    arrow_len = 60
                    dx = int(-gaze.yaw * 2.0)   # yaw → horizontal
                    dy = int(-gaze.pitch * 2.0)  # pitch → vertical
                    end_x = nx + max(-arrow_len, min(arrow_len, dx))
                    end_y = ny + max(-arrow_len, min(arrow_len, dy))
                    cv2.arrowedLine(frame, (nx, ny), (end_x, end_y),
                                    _OCV_PINK, 2, cv2.LINE_AA, tipLength=0.3)

                    # Label yaw/pitch
                    cv2.putText(frame, f"Y:{gaze.yaw:.0f} P:{gaze.pitch:.0f}",
                                (nx + 10, ny - 10), cv2.FONT_HERSHEY_SIMPLEX,
                                0.4, _OCV_PINK, 1, cv2.LINE_AA)

                # Contornos dos olhos (pontos-chave)
                for idx in [33, 133, 159, 145, 263, 362, 386, 374]:
                    if idx < len(fl):
                        ex = int((1.0 - fl[idx].x) * w)
                        ey = int(fl[idx].y * h)
                        cv2.circle(frame, (ex, ey), 2, _OCV_PINK, -1)

            # Crosshair do ponto de olhar
            if gaze.confidence > 0:
                gx = int((1.0 - gaze.screen_x) * w)  # re-espelhar para overlay
                gy = int(gaze.screen_y * h)
                cv2.drawMarker(frame, (gx, gy), _OCV_YELLOW,
                               cv2.MARKER_CROSS, 20, 2, cv2.LINE_AA)
                cv2.circle(frame, (gx, gy), 12, _OCV_YELLOW, 1, cv2.LINE_AA)

        # ── Indicar gesto atual no frame ─────────────────────────────────
        poses = self._recognizer.confirmed_poses
        for h_key, state_name in poses.items():
            if state_name != "IDLE":
                cv2.putText(frame, f"{h_key}: {state_name}", (10, 30 if h_key == "Left" else 55),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, _OCV_WHITE, 2, cv2.LINE_AA)

        # ── Redimensionar e exibir ───────────────────────────────────────
        scale = min(canvas_w / w, canvas_h / h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        frame_resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

        # Converter BGR → RGB para tkinter
        rgb = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        self._photo = ImageTk.PhotoImage(image=img)
        self._canvas.delete("all")
        offset_x = (canvas_w - new_w) // 2
        offset_y = (canvas_h - new_h) // 2
        self._canvas.create_image(offset_x, offset_y, anchor=tk.NW, image=self._photo)

    def _update_status(self) -> None:
        """Atualiza labels de status."""
        state = self._tracker.state
        if state.running:
            self._lbl_status.configure(text="🟢 Tracking ativo", foreground=_GREEN)
            self._lbl_fps.configure(text=f"FPS: {state.fps:.0f}")
        else:
            self._lbl_status.configure(text="🔴 Câmera offline", foreground=_RED)
            self._lbl_fps.configure(text="FPS: --")

        # Gesto atual
        poses = self._recognizer.confirmed_poses
        parts = []
        for h_key, state_name in poses.items():
            if state_name != "IDLE":
                parts.append(f"{h_key[0]}: {state_name}")
        self._lbl_gesture.configure(text=" | ".join(parts) if parts else "")

        # Gaze
        if self._eye_tracker and self._eye_var.get():
            gaze = self._eye_tracker.state.snapshot()
            if gaze.confidence > 0:
                self._lbl_gaze.configure(
                    text=f"Olhar: ({gaze.screen_x:.2f}, {gaze.screen_y:.2f})"
                )
            else:
                self._lbl_gaze.configure(text="Olhar: sem rosto")
        else:
            self._lbl_gaze.configure(text="Olhar: desativado")

    def _update_log(self) -> None:
        """Atualiza o log de ações."""
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        for ts, text, color in reversed(self._action_log[-30:]):
            tag = "cyan"
            if color == _GREEN:
                tag = "green"
            elif color == _RED:
                tag = "red"
            elif color == _ORANGE:
                tag = "orange"

            elapsed = time.perf_counter() - ts
            if elapsed < 60:
                time_str = f"{elapsed:.0f}s"
            else:
                time_str = f"{elapsed / 60:.0f}m"

            self._log_text.insert(tk.END, f"[{time_str}] ", "dim")
            self._log_text.insert(tk.END, f"{text}\n", tag)
        self._log_text.configure(state=tk.DISABLED)

    # ── Calibração sweep ───────────────────────────────────────────────
    def _start_calibration(self) -> None:
        """Inicia calibração sweep: ponto percorre a tela, usuário segue com o rosto."""
        if not self._eye_tracker:
            self.log_action("⚠ Ative o controle pelo olho primeiro", _ORANGE)
            return

        self._eye_tracker.reset_calibration()
        self.log_action("🎯 Calibração sweep — siga o ponto com o rosto", _CYAN)

        cal_win = tk.Toplevel(self._root)
        cal_win.attributes("-fullscreen", True)
        cal_win.configure(bg="#000000")
        cal_win.focus_force()

        cal_canvas = tk.Canvas(cal_win, bg="#000000", highlightthickness=0)
        cal_canvas.pack(fill=tk.BOTH, expand=True)

        sw = cal_win.winfo_screenwidth()
        sh = cal_win.winfo_screenheight()

        self._cal_win = cal_win
        self._cal_canvas = cal_canvas
        self._cal_sw = sw
        self._cal_sh = sh

        # Instrução central
        self._cal_text_id = cal_canvas.create_text(
            sw // 2, sh // 2,
            text="Siga o ponto com o rosto.\nPressione ESC para cancelar.",
            fill=_CYAN, font=("Consolas", 20), justify=tk.CENTER,
        )

        cal_win.bind("<Escape>", lambda e: self._cancel_calibration())

        # Esperar 2s para usuário ler, depois iniciar sweep
        cal_win.after(2000, self._begin_sweep)

    def _begin_sweep(self) -> None:
        """Inicia a animação de sweep após o delay inicial."""
        if not hasattr(self, "_cal_win") or self._cal_win is None:
            return

        self._cal_canvas.delete(self._cal_text_id)

        from gesture_interface.config import EYE_SWEEP_ROWS, EYE_SWEEP_ROW_DURATION

        self._cal_n_rows = EYE_SWEEP_ROWS
        self._cal_margin = 0.07
        self._cal_row_dur = EYE_SWEEP_ROW_DURATION
        self._cal_total_dur = self._cal_row_dur * self._cal_n_rows
        self._cal_start_time = time.perf_counter()

        self._sweep_tick()

    def _sweep_tick(self) -> None:
        """Um passo da animação de sweep (~30 fps)."""
        if not hasattr(self, "_cal_win") or self._cal_win is None:
            return
        if not self._eye_tracker:
            self._cancel_calibration()
            return

        elapsed = time.perf_counter() - self._cal_start_time
        if elapsed >= self._cal_total_dur:
            self._finish_calibration()
            return

        row = min(int(elapsed / self._cal_row_dur), self._cal_n_rows - 1)
        row_progress = (elapsed - row * self._cal_row_dur) / self._cal_row_dur
        row_progress = max(0.0, min(1.0, row_progress))

        m = self._cal_margin
        # Serpentina: linhas pares esq→dir, ímpares dir→esq
        if row % 2 == 0:
            x_norm = m + row_progress * (1.0 - 2 * m)
        else:
            x_norm = (1.0 - m) - row_progress * (1.0 - 2 * m)

        y_norm = m + (row / max(1, self._cal_n_rows - 1)) * (1.0 - 2 * m)

        px = int(x_norm * self._cal_sw)
        py = int(y_norm * self._cal_sh)

        # Desenhar ponto + barra de progresso
        self._cal_canvas.delete("sweep")

        self._cal_canvas.create_oval(
            px - 18, py - 18, px + 18, py + 18,
            fill=_CYAN, outline=_WHITE, width=2, tags="sweep",
        )
        self._cal_canvas.create_oval(
            px - 5, py - 5, px + 5, py + 5,
            fill="#ffffff", tags="sweep",
        )

        progress = elapsed / self._cal_total_dur
        bw = 400
        bx = (self._cal_sw - bw) // 2
        by = self._cal_sh - 50
        self._cal_canvas.create_rectangle(
            bx, by, bx + bw, by + 12,
            fill="#1a1a1a", outline=_BORDER, tags="sweep",
        )
        self._cal_canvas.create_rectangle(
            bx, by, bx + int(bw * progress), by + 12,
            fill=_CYAN, outline="", tags="sweep",
        )
        self._cal_canvas.create_text(
            self._cal_sw // 2, by - 15,
            text=f"Calibrando... {int(progress * 100)}%",
            fill=_DIM, font=("Consolas", 11), tags="sweep",
        )

        # Amostrar direção do rosto neste instante
        direction = self._eye_tracker.get_raw_direction()
        if direction is not None:
            yaw, pitch = direction
            self._eye_tracker.add_calibration_point(x_norm, y_norm, yaw, pitch)

        self._cal_win.after(33, self._sweep_tick)

    def _finish_calibration(self) -> None:
        """Aplica a calibração e fecha a janela."""
        if self._eye_tracker:
            self._eye_tracker.apply_calibration()
            if self._eye_tracker.state.calibrated:
                self.log_action("✅ Calibração salva com sucesso!", _GREEN)
            else:
                self.log_action("⚠ Calibração falhou — poucos dados", _ORANGE)

        if hasattr(self, "_cal_win") and self._cal_win:
            self._cal_win.destroy()
            self._cal_win = None

    def _cancel_calibration(self) -> None:
        """Cancela a calibração."""
        self.log_action("❌ Calibração cancelada", _RED)
        if hasattr(self, "_cal_win") and self._cal_win:
            self._cal_win.destroy()
            self._cal_win = None

    # ── Close ────────────────────────────────────────────────────────────
    def _on_close(self) -> None:
        """Chamado pelo botão X — SEMPRE na thread do Tk."""
        self._running = False
        root = self._root
        self._root = None   # bloquear novas chamadas after() de fora
        if root:
            # Cancelar after() pendente antes de destroy() para evitar
            # Tcl_AsyncDelete (async handler liberado da thread errada)
            if self._after_id:
                try:
                    root.after_cancel(self._after_id)
                except Exception:
                    pass
                self._after_id = None
            try:
                root.destroy()
            except Exception:
                pass
