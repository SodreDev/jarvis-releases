"""Feature flags de plataforma: o que fica ligado por padrão em cada kind.

Diferente das capacidades (Cap), features são recursos opcionais/ambiciosos que
podem ser ligados/desligados por ambiente. O padrão por kind é conservador no
Linux (Wayland/headless começam sem nada); o override JARVIS_FEATURES permite
ajustar com "+nome"/"-nome".
"""
from __future__ import annotations

import os
import warnings
from typing import FrozenSet, Mapping, Optional

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

    override = environ.get("JARVIS_FEATURES")
    if override:
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
                warnings.warn(
                    f"JARVIS_FEATURES: feature desconhecida {name!r} (ignorada)"
                )
                continue
            if op == "-":
                base.discard(name)
            else:
                base.add(name)

    return frozenset(base)
