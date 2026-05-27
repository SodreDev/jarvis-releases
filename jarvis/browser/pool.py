"""BrowserPool — contextos persistentes reutilizados (LRU).

Cada `(profile, platform)` mantém **um** `BrowserContext` persistente
através de `playwright.chromium.launch_persistent_context(user_data_dir=...)`.
Isso preserva login (QR code do WhatsApp Web, cookies do Gmail, etc.) entre
execuções.

API assíncrona — toda a stack web do JARVIS deve usar `asyncio`. Para uso
síncrono pontual, usar `pool.run_sync(coro)`.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from jarvis.config import settings

from .launcher import chromium_launch_args
from .profiles import Profile, ensure_profile

if TYPE_CHECKING:  # pragma: no cover
    from playwright.async_api import BrowserContext, Playwright

log = logging.getLogger(__name__)


@dataclass
class _Entry:
    context: "BrowserContext"
    profile: Profile
    platform: str


class BrowserPool:
    """Singleton de pool de contextos."""

    def __init__(self) -> None:
        self._pw: Optional["Playwright"] = None
        self._contexts: "OrderedDict[tuple[Profile, str], _Entry]" = OrderedDict()
        self._lock = asyncio.Lock()

    # — ciclo de vida —
    async def start(self) -> None:
        if self._pw is not None:
            return
        from playwright.async_api import async_playwright  # import lazy

        self._pw = await async_playwright().start()
        log.info("BrowserPool iniciado")

    async def stop(self) -> None:
        async with self._lock:
            for entry in list(self._contexts.values()):
                try:
                    await entry.context.close()
                except Exception:
                    pass
            self._contexts.clear()
            if self._pw is not None:
                await self._pw.stop()
                self._pw = None
        log.info("BrowserPool parado")

    # — contexto —
    async def get_context(
        self,
        platform: str,
        *,
        profile: Profile = "jarvis",
        headless: bool | None = None,
    ) -> "BrowserContext":
        if self._pw is None:
            await self.start()

        key = (profile, platform)
        async with self._lock:
            if key in self._contexts:
                # touch LRU
                self._contexts.move_to_end(key)
                return self._contexts[key].context

            # evict se necessário
            max_n = max(1, settings.browser.max_contexts)
            while len(self._contexts) >= max_n:
                _evicted_key, evicted = self._contexts.popitem(last=False)
                try:
                    await evicted.context.close()
                except Exception:
                    pass

            udd = ensure_profile(profile, platform)

            # Detecta "primeiro login" desta (profile, platform): se ainda
            # não existe Cookies salvos, abrimos VISÍVEL (mesmo que
            # BROWSER_OFFSCREEN=True) para usuário conseguir escanear QR /
            # digitar senha. Controlado por config.BROWSER_FIRST_LOGIN_VISIBLE
            # (UI: drawer Configurações → "Tudo").
            first_login_visible = True
            try:
                import config as _cfg_legacy
                first_login_visible = bool(getattr(_cfg_legacy, "BROWSER_FIRST_LOGIN_VISIBLE", True))
            except Exception:
                pass
            cookies_path = udd / "Default" / "Network" / "Cookies"
            # Fallback: versões antigas do Chromium (<96) usavam Default/Cookies
            if not cookies_path.exists():
                cookies_path = udd / "Default" / "Cookies"
            is_first_login = first_login_visible and not cookies_path.exists()

            # Se primeiro login: força janela visível (não off-screen) e não-headless
            launch_args = chromium_launch_args(
                headless=False if is_first_login else headless,
                force_visible=is_first_login,
            )
            effective_headless = bool(settings.browser.headless_after_login) if headless is None else headless
            if is_first_login:
                effective_headless = False
                log.info(
                    "BrowserContext PRIMEIRO LOGIN: profile=%s platform=%s — janela visível para autenticação",
                    profile, platform,
                )

            assert self._pw is not None
            context = await self._pw.chromium.launch_persistent_context(
                user_data_dir=str(udd),
                headless=effective_headless,
                args=launch_args,
                viewport={"width": 1280, "height": 800},
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                ignore_https_errors=False,
            )
            await _apply_stealth_init(context)
            self._contexts[key] = _Entry(context=context, profile=profile, platform=platform)
            log.info("BrowserContext criado: profile=%s platform=%s headless=%s", profile, platform, effective_headless)
            return context

    async def close_context(self, platform: str, *, profile: Profile = "jarvis") -> bool:
        key = (profile, platform)
        async with self._lock:
            entry = self._contexts.pop(key, None)
        if entry is None:
            return False
        try:
            await entry.context.close()
        except Exception:
            pass
        return True

    def list_active(self) -> list[tuple[str, str]]:
        return [(p, plat) for (p, plat) in self._contexts.keys()]


async def _apply_stealth_init(context: "BrowserContext") -> None:
    """Injeta stealth básico sem dependência externa."""
    if not settings.browser.stealth:
        return
    script = r"""
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR','pt','en-US'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
    window.chrome = window.chrome || { runtime: {} };
    const origQuery = window.navigator.permissions && window.navigator.permissions.query;
    if (origQuery) {
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : origQuery(parameters)
        );
    }
    """
    try:
        await context.add_init_script(script)
    except Exception:
        pass


# ------- singleton + bridge sync -------
_pool: BrowserPool | None = None
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_thread_lock = threading.Lock()


def get_pool() -> BrowserPool:
    global _pool
    if _pool is None:
        _pool = BrowserPool()
    return _pool


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """Cria um loop dedicado em thread separada para chamadas síncronas."""
    global _loop, _thread
    with _thread_lock:
        if _loop is not None and _loop.is_running():
            return _loop
        _loop = asyncio.new_event_loop()

        def _runner():  # pragma: no cover
            assert _loop is not None
            asyncio.set_event_loop(_loop)
            _loop.run_forever()

        _thread = threading.Thread(target=_runner, name="jarvis-browser-loop", daemon=True)
        _thread.start()
    return _loop


def run_sync(coro):
    """Executa uma coroutine no loop dedicado e bloqueia até finalizar.

    Útil para chamar a partir de código síncrono (ex.: tools regulares).
    """
    loop = _ensure_loop()
    fut = asyncio.run_coroutine_threadsafe(coro, loop)
    return fut.result()


__all__ = ["BrowserPool", "get_pool", "run_sync"]
