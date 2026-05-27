# JARVIS.spec — PyInstaller build spec (onedir, sem console)
# Gera: dist/JARVIS/JARVIS.exe
#
# Como buildar:
#   .venv\Scripts\python.exe -m PyInstaller JARVIS.spec --noconfirm
# ---------------------------------------------------------------------------

import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath('.')

# ── Coletar dados de pacotes com assets embutidos ──────────────────────────
mp_datas,  mp_bins,  mp_hidden  = collect_all('mediapipe')
wv_datas,  wv_bins,  wv_hidden  = collect_all('webview')
cv_datas,  cv_bins,  cv_hidden  = collect_all('cv2')
np_datas,  np_bins,  np_hidden  = collect_all('numpy')

# ── Sprint 1 modular — deps do pacote jarvis/ ─────────────────────────────
# pydantic v2: schema tipado de jarvis/config.
# playwright:  browser pool + comportamento humano (jarvis/browser).
# cryptography: vault tier 2 (opt-in via security.vault_encrypted=True).
# openai:      client unificado LM Studio + Groq (jarvis/llm).
# tomli/tomllib: leitura do config.user.toml (tomllib é stdlib >=3.11).
try:
    pyd_datas, pyd_bins, pyd_hidden = collect_all('pydantic')
except Exception:
    pyd_datas, pyd_bins, pyd_hidden = [], [], []
try:
    pw_datas, pw_bins, pw_hidden = collect_all('playwright')
except Exception:
    pw_datas, pw_bins, pw_hidden = [], [], []
try:
    cr_datas, cr_bins, cr_hidden = collect_all('cryptography')
except Exception:
    cr_datas, cr_bins, cr_hidden = [], [], []
try:
    oa_datas, oa_bins, oa_hidden = collect_all('openai')
except Exception:
    oa_datas, oa_bins, oa_hidden = [], [], []

# ── Fases 2026: painel, documentos, updater ────────────────────────────────
# fastapi/uvicorn → dashboard server (Painel Global)
# python-pptx/python-docx/reportlab/openpyxl → engines de documentos
# rembg/yfinance → image_gen_ctrl (fundo transparente) + painel (cotações)
try:
    fa_datas, fa_bins, fa_hidden = collect_all('fastapi')
except Exception:
    fa_datas, fa_bins, fa_hidden = [], [], []
try:
    uv_datas, uv_bins, uv_hidden = collect_all('uvicorn')
except Exception:
    uv_datas, uv_bins, uv_hidden = [], [], []
try:
    pptx_datas, pptx_bins, pptx_hidden = collect_all('pptx')
except Exception:
    pptx_datas, pptx_bins, pptx_hidden = [], [], []
try:
    docx_datas, docx_bins, docx_hidden = collect_all('docx')
except Exception:
    docx_datas, docx_bins, docx_hidden = [], [], []
try:
    rl_datas, rl_bins, rl_hidden = collect_all('reportlab')
except Exception:
    rl_datas, rl_bins, rl_hidden = [], [], []
try:
    yf_datas, yf_bins, yf_hidden = collect_all('yfinance')
except Exception:
    yf_datas, yf_bins, yf_hidden = [], [], []

# ── Dados do projeto ───────────────────────────────────────────────────────
project_datas = [
    # UI principal (pywebview)
    (os.path.join(ROOT, 'ui'),                                 'ui'),
    # Modelos MediaPipe dos gestos
    (os.path.join(ROOT, 'gesture_interface', 'gesture_data'),
                                  os.path.join('gesture_interface', 'gesture_data')),
    # Templates/static da interface gestual (workspace3d, canvas2d, etc.)
    (os.path.join(ROOT, 'gesture_interface', 'ui'),
                                  os.path.join('gesture_interface', 'ui')),
    # Configurações da interface gestual
    (os.path.join(ROOT, 'gesture_interface', 'config.py'),
                                  'gesture_interface'),
    # Configs globais
    (os.path.join(ROOT, 'config'),                             'config'),
    # Templates de credenciais — bundled e copiados para credentials/ no 1º run
    # (NUNCA bundlar o .env real ou os JSONs com dados pessoais)
    (os.path.join(ROOT, 'credentials', '.env.example'),        'credentials'),
    (os.path.join(ROOT, 'credentials', 'README.md'),           'credentials'),
    # VERSION (lido pelo updater para comparar releases)
    (os.path.join(ROOT, 'VERSION'),                            '.'),
    # Dashboard static (Painel Global HTML/CSS/JS)
    (os.path.join(ROOT, 'dashboard', 'static'),                os.path.join('dashboard', 'static')),
    # IDE frontend (index.html + ide.js)
    (os.path.join(ROOT, 'ide', 'static'),                      os.path.join('ide', 'static')),
]

all_datas    = project_datas + mp_datas + wv_datas + cv_datas + np_datas + pyd_datas + pw_datas + cr_datas + oa_datas + fa_datas + uv_datas + pptx_datas + docx_datas + rl_datas + yf_datas
all_binaries = mp_bins + wv_bins + cv_bins + np_bins + pyd_bins + pw_bins + cr_bins + oa_bins + fa_bins + uv_bins + pptx_bins + docx_bins + rl_bins + yf_bins

# ── Hidden imports ─────────────────────────────────────────────────────────
hidden = [
    # pywebview backends (Windows)
    'webview.platforms.edgechromium',
    'webview.platforms.winforms',
    'webview.platforms.mshtml',
    # system tray
    'pystray._win32',
    'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.PngImagePlugin',
    # audio
    'sounddevice', 'soundfile',
    # win32 / COM
    'win32com', 'win32com.client', 'win32com.shell', 'win32com.shell.shell',
    'win32api', 'win32con', 'win32gui', 'win32process',
    'pywintypes',
    # asyncio / edge-tts
    'asyncio.selector_events',
    # outros imports dinâmicos
    'charset_normalizer',
    'docopt',
    # coloredlogs (usado por alguns pacotes)
    'coloredlogs',
    # unittest — mediapipe.tasks.python.test importa em runtime
    'unittest',
    'unittest.case',
    'unittest.loader',
    'unittest.main',
    'unittest.mock',
    'unittest.result',
    'unittest.runner',
    'unittest.signals',
    'unittest.suite',
    'unittest.util',
    # pynput (backend win32)
    'pynput.keyboard._win32',
    'pynput.mouse._win32',
    # pygetwindow
    'pygetwindow._pygetwindow_win',
    # pyautogui win32
    'pyautogui._pyautogui_win',
    # gesture_interface — submódulos dinâmicos (não detectados pelo scanner estático)
    'gesture_interface',
    'gesture_interface.main',
    'gesture_interface.config',
    'gesture_interface.mouse_calibration',
    'gesture_interface.canvas2d.engine',
    'gesture_interface.desktop_control.controller',
    'gesture_interface.gesture_engine.eye_tracker',
    'gesture_interface.gesture_engine.recognizer',
    'gesture_interface.gesture_engine.tracker',
    'gesture_interface.gesture_training.trainer',
    'gesture_interface.interaction.event_router',
    'gesture_interface.interaction.mode_classifier',
    'gesture_interface.ui.api',
    'gesture_interface.ui.app',
    'gesture_interface.ui.live_view',
    'gesture_interface.voice_control.commands',
    'gesture_interface.workspace3d.engine',
    # sentence-transformers (embeddings da memória de contatos)
    'sentence_transformers',
    'sentence_transformers.models',
    # Sprint 1 modular — pacote jarvis/ (live-source via launcher.py)
    'jarvis',
    'jarvis.config', 'jarvis.config.loader', 'jarvis.config.schema',
    'jarvis.config.defaults', 'jarvis.config.paths',
    'jarvis.credentials', 'jarvis.credentials.vault',
    'jarvis.browser', 'jarvis.browser.pool', 'jarvis.browser.human',
    'jarvis.browser.launcher', 'jarvis.browser.profiles',
    'jarvis.messaging', 'jarvis.messaging.base',
    'jarvis.messaging.router', 'jarvis.messaging.stubs',
    'jarvis.intents', 'jarvis.intents.registry',
    'jarvis.intents.patterns', 'jarvis.intents.spotify',
    'jarvis.llm', 'jarvis.llm.client',
    # tomli (fallback se tomllib stdlib não estiver presente; >=3.11 tem)
    'tomllib',
    # ── Fases 2026: painel, documentos, updater ──────────────────────────
    'dashboard', 'dashboard.server',
    'documents', 'documents.pptx_engine', 'documents.docx_engine',
    'documents.pdf_engine', 'documents.xlsx_engine',
    'documents.chart_builder', 'documents.design_system',
    'updater', 'updater.check_update', 'updater.apply_update',
    # Bibliotecas dinâmicas usadas via lazy-import nos novos módulos
    'ddgs', 'duckduckgo_search',
    'rembg', 'rembg.bg',
    'yfinance',
    'fastapi', 'fastapi.responses', 'fastapi.staticfiles',
    'uvicorn', 'uvicorn.loops', 'uvicorn.loops.auto',
    'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan', 'uvicorn.lifespan.on',
    *mp_hidden,
    *wv_hidden,
    *cv_hidden,
    *np_hidden,
    *pyd_hidden,
    *pw_hidden,
    *cr_hidden,
    *oa_hidden,
    *fa_hidden,
    *uv_hidden,
    *pptx_hidden,
    *docx_hidden,
    *rl_hidden,
    *yf_hidden,
]

# ── Analysis ───────────────────────────────────────────────────────────────
a = Analysis(
    ['launcher.py'],   # entry point → live-source loader (ver launcher.py)
    pathex=[ROOT],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=hidden,
    hookspath=[
        os.path.join(ROOT, '.venv', 'Lib', 'site-packages', 'webview', '__pyinstaller'),
    ],
    hooksconfig={},
    runtime_hooks=[os.path.join(ROOT, 'rthook_errlog.py')],
    excludes=[
        # remove módulos desnecessários para reduzir tamanho
        'tkinter.test',
        'xmlrunner',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
        'matplotlib.tests',
        # 'numpy.testing',  # não excluir — _core depende de partes do testing
        'torch.testing',
        'torchvision.datasets',  # não usado
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='JARVIS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX desligado — compressão lenta, ganha minutos no build
    console=False,          # Sem janela de CMD
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, 'jarvis_icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,              # idem
    upx_exclude=[],
    name='JARVIS',
)
