"""Flags de inicialização do Chromium — leveza + stealth + off-screen."""
from __future__ import annotations

from jarvis.config import settings


_OFF_SCREEN_X = -32000  # truque para esconder a janela sem afetar foco do usuário


def chromium_launch_args(
    *,
    headless: bool | None = None,
    stealth: bool | None = None,
    force_visible: bool = False,
) -> list[str]:
    """Flags otimizadas para uso não-intrusivo.

    Args:
        headless: override pontual.
        stealth: override pontual.
        force_visible: se True, ignora off-screen (usado no PRIMEIRO LOGIN
            de cada plataforma para o usuário escanear QR/fazer login).
    """
    cfg = settings.browser
    is_stealth = cfg.stealth if stealth is None else bool(stealth)

    # Respeita config.py BROWSER_OFFSCREEN (editado pela UI) por cima do TOML.
    off_screen = bool(cfg.off_screen_position)
    try:
        import config as _cfg_legacy
        if hasattr(_cfg_legacy, "BROWSER_OFFSCREEN"):
            off_screen = bool(_cfg_legacy.BROWSER_OFFSCREEN)
    except Exception:
        pass
    if force_visible:
        off_screen = False

    args: list[str] = [
        "--mute-audio",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,AcceptCHFrame,MediaRouter,OptimizationHints",
        "--disable-component-update",
        "--disable-sync",
        "--disable-background-networking",
        "--disable-breakpad",
        "--disable-domain-reliability",
        "--disable-client-side-phishing-detection",
        "--disable-renderer-accessibility",
        # PERF: o tab não deve ficar throttlado quando minimizado/oculto
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
    ]

    if is_stealth:
        args.append("--disable-blink-features=AutomationControlled")
        # importante: NÃO setar `--enable-automation` (Playwright já cuida)

    if off_screen and (headless is False or headless is None):
        args.extend(off_screen_window_args())

    return args


def off_screen_window_args() -> list[str]:
    """Posiciona a janela fora da área visível para não atrapalhar o usuário."""
    return [f"--window-position={_OFF_SCREEN_X},0", "--window-size=1280,800"]


__all__ = ["chromium_launch_args", "off_screen_window_args"]
