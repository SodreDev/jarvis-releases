"""Sentinela para capacidade indisponível: qualquer uso levanta CapabilityUnavailable."""
from __future__ import annotations

from typing import List, Tuple

from ..errors import CapabilityUnavailable

# Atributos que o próprio Unavailable precisa guardar sem estourar no __getattr__.
_INTERNOS = {"_cap", "_tried"}


class Unavailable:
    """Placeholder de backend ausente.

    Guardado no cache quando nenhuma implementação resolve. Acessar QUALQUER
    atributo ou chamar QUALQUER método levanta CapabilityUnavailable(cap, tried).
    """

    def __init__(self, cap, tried: List[Tuple[str, str]] | None = None):
        object.__setattr__(self, "_cap", cap)
        object.__setattr__(self, "_tried", list(tried or []))

    def __getattr__(self, name):
        # Só chamado para atributos não encontrados normalmente.
        raise CapabilityUnavailable(
            object.__getattribute__(self, "_cap"),
            object.__getattribute__(self, "_tried"),
        )

    def __call__(self, *args, **kwargs):
        raise CapabilityUnavailable(
            object.__getattribute__(self, "_cap"),
            object.__getattribute__(self, "_tried"),
        )
