"""Browser do JARVIS — Playwright como motor principal.

Sub-módulos:
- `profiles`   — diretórios de perfil isolados por (perfil, plataforma).
- `human`      — utilidades de comportamento humano (delays, jitter, hover).
- `launcher`   — flags Chromium otimizadas (leveza + stealth + off-screen).
- `pool`       — `BrowserPool` reutiliza contextos persistentes (LRU).

Princípio (Plano 04): **toda operação usa a API do Playwright** (`page.click`,
`page.fill`, `page.evaluate`). Nunca capturamos o mouse/teclado do usuário.
PyAutoGUI permanece apenas como fallback explícito documentado.
"""

from .profiles import profile_dir, ensure_profile  # noqa: F401
from .human import (  # noqa: F401
    human_pause,
    human_type,
    human_click,
    human_scroll,
)
from .launcher import (  # noqa: F401
    chromium_launch_args,
    off_screen_window_args,
)
from .playwright_setup import (  # noqa: F401
    chromium_missing,
    ensure_chromium_sync,
    ensure_chromium_async,
)

__all__ = [
    "profile_dir",
    "ensure_profile",
    "human_pause",
    "human_type",
    "human_click",
    "human_scroll",
    "chromium_launch_args",
    "off_screen_window_args",
    "get_pool",
]


def get_pool():
    """Acesso lazy ao `BrowserPool` (evita import síncrono de playwright)."""
    from .pool import get_pool as _gp

    return _gp()
