"""Feature flags de plataforma: o que fica ligado por padrão em cada kind.

Diferente das capacidades (Cap), features são recursos opcionais/ambiciosos que
podem ser ligados/desligados por ambiente. O padrão por kind é conservador no
Linux (Wayland/headless começam sem nada); o override JARVIS_FEATURES permite
ajustar com "+nome"/"-nome".

F2-00: no Linux, algumas features também ligam pela capacidade real
(``DERIVED_FEATURES``): global_hotkeys = has(HOTKEYS), tray = has(TRAY) e
clipboard_monitor = has(CLIPBOARD) e can_watch. ``features_for`` continua pura e
estática; a derivação fica em ``feature_enabled``/``effective_features``, que
no win32 devolvem o estático sem sondar nada.
"""
from __future__ import annotations

import os
import warnings
from typing import Callable, FrozenSet, Iterator, Mapping, Optional, Tuple

from .capabilities import Cap
from .detect import PlatformContext

ALL_FEATURES: FrozenSet[str] = frozenset(
    {
        "global_hotkeys",
        "tray",
        "notification_reader",
        "clipboard_monitor",
        "self_update_payload",
        "gestures",
    }
)

_DEFAULTS = {
    "win32": ALL_FEATURES,
    "linux-x11": frozenset({"global_hotkeys"}),
    "linux-wayland": frozenset(),
    "linux-headless": frozenset(),
    "unsupported": frozenset(),
}

# Features que, no Linux, ligam quando a capacidade correspondente existe.
DERIVED_FEATURES: FrozenSet[str] = frozenset({"global_hotkeys", "tray", "clipboard_monitor"})


def _override_ops(environ: Mapping[str, str], *, warn: bool) -> Iterator[Tuple[str, str]]:
    """(op, nome) de cada item válido do JARVIS_FEATURES, na ordem."""
    override = environ.get("JARVIS_FEATURES")
    if not override:
        return
    for token in override.split(","):
        token = token.strip()
        if not token:
            continue
        op = "+"
        name = token
        if token[0] in "+-":
            op = token[0]
            name = token[1:].strip()
        if name not in ALL_FEATURES:
            if warn:
                warnings.warn(
                    f"JARVIS_FEATURES: feature desconhecida {name!r} (ignorada)"
                )
            continue
        yield op, name


def features_for(
    ctx: PlatformContext, environ: Optional[Mapping[str, str]] = None
) -> FrozenSet[str]:
    """Features ativas para ``ctx``, aplicando o override JARVIS_FEATURES.

    Override: lista separada por vírgula de "+nome"/"-nome" (nome sem sinal = "+").
    Nome desconhecido → aviso e ignora. INVARIANTE: win32 sem override = ALL_FEATURES.
    """
    if environ is None:
        environ = os.environ
    base = set(_DEFAULTS.get(ctx.kind, frozenset()))

    for op, name in _override_ops(environ, warn=True):
        if op == "-":
            base.discard(name)
        else:
            base.add(name)

    return frozenset(base)


def removed_by_override(environ: Optional[Mapping[str, str]] = None) -> FrozenSet[str]:
    """Nomes cujo último item no JARVIS_FEATURES é "-nome" (vence o derivado)."""
    if environ is None:
        environ = os.environ
    last = {}
    for op, name in _override_ops(environ, warn=False):
        last[name] = op
    return frozenset(name for name, op in last.items() if op == "-")


def derived_feature(
    name: str, has: Callable[[Cap], bool], get: Callable[[Cap], object]
) -> bool:
    """Valor derivado da capacidade real. Nunca levanta (falha = False)."""
    try:
        if name == "global_hotkeys":
            return bool(has(Cap.HOTKEYS))
        if name == "tray":
            return bool(has(Cap.TRAY))
        if name == "clipboard_monitor":
            return bool(has(Cap.CLIPBOARD)) and bool(
                getattr(get(Cap.CLIPBOARD), "can_watch", False)
            )
    except Exception:
        return False
    return False


def feature_enabled(
    ctx: PlatformContext,
    name: str,
    *,
    has: Callable[[Cap], bool],
    get: Callable[[Cap], object],
    environ: Optional[Mapping[str, str]] = None,
) -> bool:
    """``name`` ∈ estático OU (só no Linux) derivado; o "-nome" vence o derivado.

    Fora do Linux (win32, unsupported) é o estático puro: ``has``/``get`` nunca
    são chamados.
    """
    if environ is None:
        environ = os.environ
    if name in features_for(ctx, environ):
        return True
    if not ctx.is_linux or name not in DERIVED_FEATURES:
        return False
    if name in removed_by_override(environ):
        return False
    return derived_feature(name, has, get)


def effective_features(
    ctx: PlatformContext,
    *,
    has: Callable[[Cap], bool],
    get: Callable[[Cap], object],
    environ: Optional[Mapping[str, str]] = None,
) -> FrozenSet[str]:
    """Conjunto efetivo (estático + derivado no Linux), para o report()."""
    if environ is None:
        environ = os.environ
    static = features_for(ctx, environ)
    if not ctx.is_linux:
        return static
    removed = removed_by_override(environ)
    extra = {
        name
        for name in DERIVED_FEATURES - static
        if name not in removed and derived_feature(name, has, get)
    }
    return static | extra
