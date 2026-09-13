"""Base para backends de plataforma."""
from __future__ import annotations

from typing import ClassVar, NamedTuple


class Probe(NamedTuple):
    """Resultado de um probe de disponibilidade de backend."""

    ok: bool
    reason: str = ""


class BackendBase:
    """Base opcional para backends: probe padrão OK e guarda o contexto."""

    name: ClassVar[str] = ""

    @classmethod
    def probe(cls, ctx) -> Probe:
        """Diz se o backend pode ser usado neste contexto (padrão: sim)."""
        return Probe(True)

    def __init__(self, ctx):
        self.ctx = ctx
