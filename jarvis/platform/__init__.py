"""Camada de abstração de plataforma do JARVIS (jarvis.platform).

Fachada única: detecção da plataforma (uma vez, com cache), resolução lazy de
backends por capacidade, feature flags e relatório de diagnóstico.

No import carregamos SÓ stdlib + os submódulos leves (detect, capabilities,
features, registry, errors): nenhum backend, nenhum subprocess, nenhuma
dependência pesada (pynput, webview, Qt, etc.).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from . import registry
from .capabilities import Cap
from .detect import PlatformContext, detect
from .errors import CapabilityUnavailable
from .features import feature_enabled

if TYPE_CHECKING:  # pragma: no cover - só para type checkers
    from .protocols import Paths, Processes, WebviewEngine

__all__ = [
    "Cap",
    "CapabilityUnavailable",
    "PlatformContext",
    "current",
    "get",
    "has",
    "has_feature",
    "report",
    "paths",
    "processes",
    "webview_engine",
]

_CTX: Optional[PlatformContext] = None


def current() -> PlatformContext:
    """PlatformContext do processo (detectado uma única vez e cacheado)."""
    global _CTX
    if _CTX is None:
        _CTX = detect()
    return _CTX


def get(cap: Cap):
    """Resolve o backend da capacidade (real ou Unavailable). Não levanta aqui."""
    return registry.resolve(cap, current())


def has(cap: Cap) -> bool:
    """True se há backend real para a capacidade. Não levanta."""
    return registry.has(cap, current())


def has_feature(name: str) -> bool:
    """True se a feature está ativa no contexto atual.

    Estático (features_for) OU, só no Linux, derivado da capacidade real:
    global_hotkeys = has(HOTKEYS), tray = has(TRAY), clipboard_monitor =
    has(CLIPBOARD) e can_watch. O "-nome" do JARVIS_FEATURES vence o derivado.
    No win32 é o estático puro, sem sondar nada.
    """
    return feature_enabled(current(), name, has=has, get=get)


def report() -> dict:
    """Relatório de diagnóstico (kind/source/desktops/capabilities/features)."""
    return registry.report(current())


# ── Helpers tipados (F1) ────────────────────────────────────────────────────────

def paths() -> "Paths":
    return get(Cap.PATHS)


def processes() -> "Processes":
    return get(Cap.PROCESSES)


def webview_engine() -> "WebviewEngine":
    return get(Cap.WEBVIEW_ENGINE)


def _reset_for_tests(ctx: Optional[PlatformContext] = None) -> None:
    """Zera o contexto cacheado (ou fixa `ctx`) e limpa o cache do registro."""
    global _CTX
    _CTX = ctx
    registry._clear_all()
