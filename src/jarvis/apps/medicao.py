"""Métricas puras para o corpus de regressão de pronúncia de aplicativos."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from jarvis.apps.resolvedor import ResolvedorDeApps


@dataclass(frozen=True, slots=True)
class CasoDePronuncia:
    fala: str
    app_id: str | None
    """Id esperado; ``None`` é uma frase que deve ser recusada, não adivinhada."""
    origem: str = "texto-sintetico"


@dataclass(frozen=True, slots=True)
class MetricasDePronuncia:
    total: int
    com_referencia: int
    top_1: int
    top_3: int
    falso_aceite: int

    @property
    def taxa_top_1(self) -> float:
        return self.top_1 / self.com_referencia if self.com_referencia else 0.0

    @property
    def taxa_top_3(self) -> float:
        return self.top_3 / self.com_referencia if self.com_referencia else 0.0

    @property
    def taxa_falso_aceite(self) -> float:
        return self.falso_aceite / self.total if self.total else 0.0


def medir(casos: Iterable[CasoDePronuncia], resolvedor: ResolvedorDeApps) -> MetricasDePronuncia:
    total = com_referencia = top_1 = top_3 = falso_aceite = 0
    for caso in casos:
        total += 1
        resultado = resolvedor.resolver(caso.fala)
        ids = [candidato.app.id for candidato in resultado.candidatos]
        if caso.app_id is not None:
            com_referencia += 1
            top_1 += int(bool(ids) and ids[0] == caso.app_id)
            top_3 += int(caso.app_id in ids)
        falso_aceite += int(
            resultado.estado == "encontrado"
            and resultado.app is not None
            and resultado.app.id != caso.app_id
        )
    return MetricasDePronuncia(total, com_referencia, top_1, top_3, falso_aceite)
