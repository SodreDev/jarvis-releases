"""Configurações centrais do sistema de gestos."""
from __future__ import annotations

# ── MediaPipe Hands ──────────────────────────────────────────────────────────
MP_MAX_HANDS: int = 2
MP_MIN_DETECTION_CONFIDENCE: float = 0.7
MP_MIN_TRACKING_CONFIDENCE: float = 0.6

# ── MediaPipe Face / Eye tracking (head pose via solvePnP) ────────────────────
EYE_TRACKING_ENABLED: bool = False    # NÃO ativa com gestos — comando de voz separado
EYE_MIN_DETECTION_CONFIDENCE: float = 0.6
EYE_MIN_TRACKING_CONFIDENCE: float = 0.5
EYE_SMOOTHING_FRAMES: int = 6         # média móvel para suavizar olhar (90fps)
EYE_SMOOTHING_ALPHA: float = 0.35    # fator EMA (0=liso, 1=reativo) — 0.35 para responsividade
EYE_MOVE_THRESHOLD: float = 0.0005   # movimento mín. para atualizar cursor
EYE_SWEEP_ROWS: int = 5              # linhas do sweep de calibração
EYE_SWEEP_ROW_DURATION: float = 3.0  # segundos por linha do sweep

# ── Facial gestures (wink-click, eyebrow-click) ─────────────────────────────
WINK_EAR_THRESHOLD: float = 0.08     # Eye Aspect Ratio < this = closed (mais fechado)
WINK_CHEEK_BROW_THRESHOLD: float = 0.04  # cheek-brow dist < this = strong wink (bochecha quase encosta)
WINK_CONFIRM_FRAMES: int = 4         # frames consecutivos para confirmar wink
WINK_COOLDOWN: float = 0.6           # segundos entre winks
EYEBROW_RAISE_MULTIPLIER: float = 2.0  # brow dist > baseline * this = raised (precisa levantar MUITO)
EYEBROW_CONFIRM_FRAMES: int = 5      # frames consecutivos para confirmar
EYEBROW_COOLDOWN: float = 0.8        # segundos entre right-clicks

# ── Câmera ───────────────────────────────────────────────────────────────────
CAMERA_INDEX: int = 0
CAMERA_WIDTH: int = 1280
CAMERA_HEIGHT: int = 720
CAMERA_FPS: int = 90

# ── Reconhecimento de gestos ─────────────────────────────────────────────────
SWIPE_MIN_SPEED: float = 0.18          # velocidade mín. para swipe de desktop
SWIPE_MIN_FRAMES: int = 5              # frames de histórico para swipe
SWIPE_COOLDOWN: float = 0.8            # cooldown entre swipes de desktop

# ── Window Switcher (punho → mão aberta → Win+Tab) ───────────────────────────
FIST_CONFIRM_FRAMES: int = 5           # frames de punho para confirmar trigger
OPEN_CONFIRM_FRAMES: int = 4           # frames de mão aberta para confirmar
WINSW_TIMEOUT: float = 12.0            # timeout do seletor de janelas (s)
SWIPE_NAV_MIN_SPEED: float = 0.25      # velocidade mín. para nav no seletor
SWIPE_NAV_FRAMES: int = 6              # frames para detectar swipe de nav
SWIPE_NAV_COOLDOWN: float = 0.5        # cooldown entre gestos de nav

# ── Palm Flip (virar palma → minimizar janela) ────────────────────────────────
PALM_CONFIRM_FRAMES: int = 4           # frames para confirmar orientação da palma
PALM_FLIP_TIMEOUT: float = 2.5         # tempo máx. para completar o flip (s)
BOTH_FLIP_WINDOW: float = 1.5          # janela para dois flips = minimizar tudo

# ── Alt+F4 (pedra bate na mão aberta — duas mãos) ────────────────────────────
ALT_F4_PROXIMITY_THRESHOLD: float = 0.50  # distância normalizada entre as mãos
ALT_F4_CONFIRM_FRAMES: int = 4         # frames confirmados para disparar

# ── Tolerância de jitter ─────────────────────────────────────────────────────
HOLD_JITTER_TOLERANCE: int = 4         # frames de jitter permitidos

# ── Gesture guard layer ──────────────────────────────────────────────────────
DESKTOP_DANGEROUS_COOLDOWN: float = 1.5  # cooldown de gestos destrutivos
GESTURE_GLOBAL_COOLDOWN: float = 0.35    # cooldown geral do recognizer

# ── Gesture training (DTW custom gestures) ───────────────────────────────────
DTW_MATCH_THRESHOLD: float = 30.0      # distância DTW máxima para match (menor = mais estrito)
TRAINING_MAX_FRAMES: int = 60          # máximo de frames por gesto gravado

MODES = {
    "full":        {"desktop": True,  "canvas2d": True,  "workspace3d": True},
    "desktop":     {"desktop": True,  "canvas2d": False, "workspace3d": False},
    "desktop_2d":  {"desktop": True,  "canvas2d": True,  "workspace3d": False},
    "design3d":    {"desktop": False, "canvas2d": False, "workspace3d": True},
}
DEFAULT_MODE = "full"

# ── Desktop control ─────────────────────────────────────────────────────────
VIRTUAL_DESKTOP_SWIPE_THRESHOLD: float = 0.25   # distância mín. pra trocar desktop
WINDOW_DRAG_SMOOTHING: int = 3                   # frames de suavização

# ── Canvas 2D ────────────────────────────────────────────────────────────────
CANVAS_DEFAULT_COLOR: str = "#00e6ff"
CANVAS_DEFAULT_WIDTH: int = 3
CANVAS_ERASER_RADIUS: int = 30

# ── Workspace 3D ─────────────────────────────────────────────────────────────
PARTICLE_COUNT_DEFAULT: int = 5000
PARTICLE_SIZE: float = 0.02
PHYSICS_FORCE_MULTIPLIER: float = 2.0
PHYSICS_DAMPING: float = 0.92

# ── PyWebView ────────────────────────────────────────────────────────────────
UI_WIDTH: int = 1400
UI_HEIGHT: int = 900
UI_TITLE: str = "J.A.R.V.I.S — Gesture Interface"
UI_BG_COLOR: str = "#0a0a0a"

# ── Frases de ativação por voz ───────────────────────────────────────────────
VOICE_PHRASES: dict[str, list[str]] = {
    "full":       ["modo completo", "interface total", "ativar interface total"],
    "desktop":    ["modo controle", "controlar tela"],
    "desktop_2d": ["modo desenho", "controle com desenho"],
    "design3d":   ["modo design", "abrir estudio 3d", "estudio 3d",
                   "abrir estúdio 3d", "estúdio 3d"],
}

# ── Live View (tkinter camera UI) ───────────────────────────────────────────
LIVE_VIEW_WIDTH: int = 1200
LIVE_VIEW_HEIGHT: int = 750
LIVE_VIEW_CAMERA_W: int = 800          # largura do painel da câmera
LIVE_VIEW_SIDEBAR_W: int = 400        # largura do painel lateral
LIVE_VIEW_FPS: int = 90               # taxa de atualização da UI

# ── Mouse calibration ────────────────────────────────────────────────────────
MOUSE_CAL_DWELL_SECONDS: float = 1.5  # segundos parado para capturar ponto
MOUSE_CAL_JITTER_THRESHOLD: float = 0.015  # movimento máx. considerado "parado"

# ── Thumb-side click (mouse mode) ────────────────────────────────────────────
# Distância do dedão até a lateral do indicador para disparar clique.
# Em metros (world_landmarks); cai para PINCH_THRESHOLD*1.2 se não houver world.
THUMB_SIDE_CLICK_THRESHOLD: float = 0.032
DOUBLE_CLICK_WINDOW: float = 0.7       # janela (s) para considerar 2ª pressionada = right click
