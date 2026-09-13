"""Smoke test do browser pool.

Uso:
    .\\.venv\\Scripts\\python.exe -m jarvis.browser.smoke whatsapp_web jarvis

Abre uma página em perfil isolado, espera 5s e fecha. Útil para validar
que Playwright + perfil + flags otimizadas funcionam.
"""
from __future__ import annotations

import asyncio
import sys

from .pool import get_pool


async def _run(platform: str, profile: str, url: str) -> int:
    pool = get_pool()
    ctx = await pool.get_context(platform, profile=profile, headless=False)
    page = await ctx.new_page()
    print(f"[smoke] navegando para {url}")
    await page.goto(url, wait_until="domcontentloaded")
    title = await page.title()
    print(f"[smoke] title: {title!r}")
    await asyncio.sleep(5)
    await page.close()
    await pool.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) < 2:
        print("uso: jarvis.browser.smoke <platform> <profile> [url]", file=sys.stderr)
        return 2
    platform, profile = argv[0], argv[1]
    url = argv[2] if len(argv) > 2 else "https://example.com"
    return asyncio.run(_run(platform, profile, url))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
