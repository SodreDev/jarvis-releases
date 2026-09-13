"""Simulação humana para Playwright.

Todas as funções operam **apenas via API do Playwright** — não tocam no
mouse/teclado físicos do usuário. Cliques e digitação acontecem dentro do
contexto do browser (mesmo se a janela estiver fora de foco/minimizada).

Princípios:
- Distribuição gaussiana para delays de digitação (variação por caractere).
- Pausas extras em pontuação (`.,;:!?`).
- Cliques com hover prévio + jitter de pixels.
- Scroll com easing (não-linear).
- Operações `async` para não bloquear o loop principal.
"""
from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING

from jarvis.config import settings

if TYPE_CHECKING:  # pragma: no cover
    from playwright.async_api import Locator, Page


def _typing_delay_ms() -> float:
    """Delay médio entre teclas, derivado de `browser.human_typing_wpm`."""
    wpm = max(40, settings.browser.human_typing_wpm)
    # 1 char ≈ 60_000/wpm ms; aplica jitter gaussiano (sigma=25% da média)
    base = 60_000.0 / wpm
    return max(15.0, random.gauss(base, base * 0.25))


async def human_pause(min_ms: int | None = None, max_ms: int | None = None) -> None:
    """Pausa de `min`–`max` ms uniformemente; defaults vêm do config."""
    lo = min_ms if min_ms is not None else settings.browser.human_pause_min_ms
    hi = max_ms if max_ms is not None else settings.browser.human_pause_max_ms
    if hi <= lo:
        hi = lo + 1
    await asyncio.sleep(random.uniform(lo, hi) / 1000.0)


async def human_type(page_or_locator, text: str, *, selector: str | None = None) -> None:
    """Digita `text` caractere a caractere com delays humanos.

    Aceita tanto `Page` (precisa `selector`) quanto `Locator` (foca direto).
    """
    target = page_or_locator
    if selector is not None:
        await target.click(selector)
        target = target.locator(selector)
    else:
        await target.focus()

    for ch in text:
        await target.type(ch, delay=_typing_delay_ms())
        if ch in ".,;:!?":
            await asyncio.sleep(random.uniform(0.15, 0.35))
        elif ch == " " and random.random() < 0.08:
            # pausa micro ocasional entre palavras
            await asyncio.sleep(random.uniform(0.05, 0.18))


async def human_click(locator: "Locator", *, jitter_px: int | None = None) -> None:
    """Hover → micro-pausa → clique em ponto aleatório dentro da bbox."""
    j = jitter_px if jitter_px is not None else settings.browser.human_click_jitter_px
    box = await locator.bounding_box()
    await locator.hover()
    await asyncio.sleep(random.uniform(0.08, 0.22))
    if box and box["width"] > 4 and box["height"] > 4:
        cx = box["x"] + box["width"] / 2 + random.uniform(-j, j)
        cy = box["y"] + box["height"] / 2 + random.uniform(-j, j)
        await locator.page.mouse.click(cx, cy, delay=random.uniform(40, 110))
    else:
        await locator.click(delay=random.uniform(40, 110))


async def human_scroll(page: "Page", *, dy: int = 600, steps: int = 8) -> None:
    """Scroll com easing (in-out)."""
    if steps < 2:
        steps = 2
    accum = 0
    for i in range(1, steps + 1):
        # easing in-out cubic
        t = i / steps
        eased = (3 * t * t - 2 * t * t * t)
        target = int(dy * eased)
        delta = target - accum
        accum = target
        await page.mouse.wheel(0, delta)
        await asyncio.sleep(random.uniform(0.04, 0.12))


__all__ = ["human_pause", "human_type", "human_click", "human_scroll"]
