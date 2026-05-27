# -*- coding: utf-8 -*-
"""
documents.chart_builder — Geração de gráficos matplotlib com tema JARVIS.

Saída padrão: arquivo PNG em `data/temp_charts/` (gitignored). Retorna o path.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Iterable, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .design_system import get_theme, PALETTE


def _base() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _out_dir() -> str:
    d = os.path.join(_base(), "data", "temp_charts")
    os.makedirs(d, exist_ok=True)
    return d


def _apply_theme(ax, theme):
    fig = ax.figure
    fig.patch.set_facecolor(theme.bg)
    ax.set_facecolor(theme.panel)
    for spine in ax.spines.values():
        spine.set_color(theme.accent_dim)
    ax.tick_params(colors=theme.text, labelsize=9)
    ax.yaxis.label.set_color(theme.text)
    ax.xaxis.label.set_color(theme.text)
    ax.title.set_color(theme.accent)
    ax.grid(True, color=theme.grid, linewidth=0.5, alpha=0.6)


def _save(fig, name: str) -> str:
    path = os.path.join(_out_dir(), f"{name}_{int(time.time() * 1000)}.png")
    fig.savefig(path, dpi=160, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


def bar_chart(labels: Iterable[str], values: Iterable[float],
              *, title: str = "", theme_name: str = "stark_dark",
              ylabel: str = "", filename: str = "bar") -> str:
    theme = get_theme(theme_name)
    labels = list(labels); values = list(values)
    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.bar(labels, values, color=theme.accent,
                  edgecolor=theme.accent_dim, linewidth=1)
    for b in bars:
        b.set_alpha(0.85)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=10)
    _apply_theme(ax, theme)
    plt.xticks(rotation=20, ha="right")
    return _save(fig, filename)


def line_chart(x: Iterable, series: dict, *,
               title: str = "", theme_name: str = "stark_dark",
               filename: str = "line") -> str:
    """`series`: {nome: [valores]}"""
    theme = get_theme(theme_name)
    x = list(x)
    fig, ax = plt.subplots(figsize=(9, 5))
    palette_colors = [theme.accent, PALETTE["ok"], PALETTE["warn"], PALETTE["crit"], PALETTE["text_dim"]]
    for i, (name, vals) in enumerate(series.items()):
        ax.plot(x, list(vals), label=name, color=palette_colors[i % len(palette_colors)],
                linewidth=2, marker="o", markersize=4)
    ax.set_title(title, fontsize=14, fontweight="bold", pad=12)
    leg = ax.legend(facecolor=theme.panel, edgecolor=theme.accent_dim, labelcolor=theme.text)
    if leg:
        leg.get_frame().set_alpha(0.9)
    _apply_theme(ax, theme)
    return _save(fig, filename)


def pie_chart(labels: Iterable[str], values: Iterable[float], *,
              title: str = "", theme_name: str = "stark_dark",
              filename: str = "pie") -> str:
    theme = get_theme(theme_name)
    labels = list(labels); values = list(values)
    fig, ax = plt.subplots(figsize=(7, 7))
    colors = [theme.accent, PALETTE["ok"], PALETTE["warn"], PALETTE["crit"], PALETTE["text_dim"], theme.accent_dim]
    wedges, texts, autotexts = ax.pie(
        values, labels=labels, autopct="%1.1f%%",
        colors=[colors[i % len(colors)] for i in range(len(values))],
        textprops={"color": theme.text, "fontsize": 10},
        wedgeprops={"edgecolor": theme.bg, "linewidth": 2},
    )
    for at in autotexts:
        at.set_color(theme.bg if theme.is_dark else "#ffffff")
        at.set_fontweight("bold")
    ax.set_title(title, fontsize=14, fontweight="bold", color=theme.accent, pad=12)
    fig.patch.set_facecolor(theme.bg)
    return _save(fig, filename)


__all__ = ["bar_chart", "line_chart", "pie_chart"]
