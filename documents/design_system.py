# -*- coding: utf-8 -*-
"""
documents.design_system — Identidade visual única para todos os documentos
gerados pelo JARVIS (apresentações, relatórios, planilhas, charts).

Inspiração: HUD Stark — fundo escuro #0a0e1a, ciano #00d8ff, tipografia
limpa, hierarquia clara.
"""

from __future__ import annotations
from dataclasses import dataclass


# ─────────────────────────────────────────────────────────────────────────────
# Paleta principal (compartilhada com o painel web)
# ─────────────────────────────────────────────────────────────────────────────
PALETTE = {
    "bg_dark":    "#0a0e1a",
    "bg_panel":   "#0f1626",
    "bg_card":    "#11192b",
    "accent":     "#00d8ff",
    "accent_dim": "#0091b3",
    "warn":       "#ffb347",
    "crit":       "#ff4d6d",
    "ok":         "#4dffb8",
    "text":       "#d9e7ff",
    "text_dim":   "#6a7fa5",
    "grid":       "#1a2a44",
    # Variante "clara" para relatórios mais formais
    "light_bg":   "#f5f8fc",
    "light_text": "#0a0e1a",
}


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    panel: str
    text: str
    accent: str
    accent_dim: str
    grid: str
    is_dark: bool = True


THEMES = {
    "stark_dark": Theme("stark_dark", PALETTE["bg_dark"], PALETTE["bg_panel"], PALETTE["text"],
                       PALETTE["accent"], PALETTE["accent_dim"], PALETTE["grid"], True),
    "stark_light": Theme("stark_light", PALETTE["light_bg"], "#ffffff", PALETTE["light_text"],
                        "#0066aa", "#88b8d0", "#cfd8e4", False),
}


def get_theme(name: str = "stark_dark") -> Theme:
    return THEMES.get(name, THEMES["stark_dark"])


# ─────────────────────────────────────────────────────────────────────────────
# Cores nomeadas em PT-BR / EN  →  hex
# ─────────────────────────────────────────────────────────────────────────────
_COLOR_MAP: dict[str, str] = {
    # PT-BR
    "azul":      "#1565c0", "azul claro": "#42a5f5", "azul escuro": "#0d3e8c",
    "vermelho":  "#c62828", "verde":      "#2e7d32", "verde claro": "#43a047",
    "amarelo":   "#f9a825", "laranja":    "#e65100", "roxo":        "#6a1b9a",
    "violeta":   "#7b1fa2", "rosa":       "#e91e63", "cinza":       "#546e7a",
    "preto":     "#0a0a0a", "branco":     "#f5f5f5", "ciano":       "#00bcd4",
    "dourado":   "#f5b400", "prata":      "#9e9e9e", "marrom":      "#5d4037",
    "turquesa":  "#00acc1", "índigo":     "#283593",
    # EN aliases
    "blue":   "#1565c0", "red":    "#c62828", "green":  "#2e7d32",
    "yellow": "#f9a825", "orange": "#e65100", "purple": "#6a1b9a",
    "pink":   "#e91e63", "gray":   "#546e7a",  "grey":  "#546e7a",
    "black":  "#0a0a0a", "white":  "#f5f5f5", "cyan":   "#00bcd4",
    "gold":   "#f5b400", "silver": "#9e9e9e", "brown":  "#5d4037",
    "teal":   "#00897b", "indigo": "#283593",
}


def _luminance(hex_color: str) -> float:
    """Calcula luminância relativa (WCAG 2.1)."""
    r, g, b = (c / 255 for c in hex_to_rgb(hex_color))
    def lin(c): return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _ensure_dark_contrast(accent_hex: str, bg_hex: str = "#0a0e1a",
                           min_ratio: float = 4.5) -> str:
    """Clareia `accent_hex` até atingir contraste mínimo com `bg_hex` (WCAG AA).

    Usado para garantir que cores do usuário fiquem legíveis em fundos escuros.
    """
    l_bg = _luminance(bg_hex)
    l_ac = _luminance(accent_hex)
    ratio = (max(l_ac, l_bg) + 0.05) / (min(l_ac, l_bg) + 0.05)
    if ratio >= min_ratio:
        return accent_hex
    # Clareia incrementalmente
    r, g, b = hex_to_rgb(accent_hex)
    for _ in range(30):
        r = min(255, int(r + (255 - r) * 0.15))
        g = min(255, int(g + (255 - g) * 0.15))
        b = min(255, int(b + (255 - b) * 0.15))
        h = "#{:02x}{:02x}{:02x}".format(r, g, b)
        if (max(_luminance(h), l_bg) + 0.05) / (min(_luminance(h), l_bg) + 0.05) >= min_ratio:
            return h
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


def build_custom_theme(accent_hex: str, dark: bool = True) -> Theme:
    """Cria um tema dinâmico com cor de acento customizada.

    Deriva automaticamente:
    - bg: quase-preto se `dark=True`, quase-branco se `dark=False`
    - accent_dim: 60% de saturação do acento
    - text / panel a partir do modo escuro/claro
    """
    def _darken(h: str, factor: float) -> str:
        r, g, b = hex_to_rgb(h)
        return "#{:02x}{:02x}{:02x}".format(
            int(r * factor), int(g * factor), int(b * factor))

    def _blend(h: str, bg: str, ratio: float) -> str:
        r1, g1, b1 = hex_to_rgb(h)
        r2, g2, b2 = hex_to_rgb(bg)
        return "#{:02x}{:02x}{:02x}".format(
            int(r1 * ratio + r2 * (1 - ratio)),
            int(g1 * ratio + g2 * (1 - ratio)),
            int(b1 * ratio + b2 * (1 - ratio)))

    if dark:
        bg      = "#0a0e1a"
        panel   = "#0f1626"
        text    = "#d9e7ff"
        grid    = "#1a2a44"
        # Garante contraste WCAG AA (4.5:1) em fundos escuros
        accent_hex = _ensure_dark_contrast(accent_hex, bg)
        dim     = _blend(accent_hex, bg, 0.45)
    else:
        bg      = "#f4f6fb"
        panel   = "#ffffff"
        text    = "#0a0e1a"
        grid    = "#dde3ee"
        dim     = _darken(accent_hex, 0.7)

    return Theme(
        name=f"custom_{accent_hex.lstrip('#')}",
        bg=bg, panel=panel, text=text,
        accent=accent_hex, accent_dim=dim, grid=grid,
        is_dark=dark,
    )


def parse_color_from_text(text: str) -> str | None:
    """Extrai uma cor hexadecimal do texto do usuário.

    Aceita:
    - Hex direto: #1a2b3c, #fff, 1a2b3c
    - Nomes PT-BR/EN: azul, vermelho, ciano, blue, red…
    Retorna hex normalizado (#rrggbb) ou None.
    """
    import re
    # Hex explícito
    m = re.search(r'#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b', text)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = h[0]*2 + h[1]*2 + h[2]*2
        return f"#{h.lower()}"
    # Nome de cor (tenta os compostos primeiro)
    tl = text.lower()
    for name in sorted(_COLOR_MAP, key=len, reverse=True):
        if name in tl:
            return _COLOR_MAP[name]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Tipografia
# ─────────────────────────────────────────────────────────────────────────────
FONTS = {
    "title":   {"family": "Segoe UI", "size_pt": 36, "bold": True},
    "h1":      {"family": "Segoe UI", "size_pt": 28, "bold": True},
    "h2":      {"family": "Segoe UI", "size_pt": 20, "bold": True},
    "body":    {"family": "Segoe UI", "size_pt": 14, "bold": False},
    "caption": {"family": "Segoe UI", "size_pt": 10, "bold": False},
    "mono":    {"family": "Consolas", "size_pt": 12, "bold": False},
}


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


__all__ = ["PALETTE", "Theme", "THEMES", "get_theme", "FONTS", "hex_to_rgb",
           "build_custom_theme", "parse_color_from_text",
           "_luminance", "_ensure_dark_contrast"]
