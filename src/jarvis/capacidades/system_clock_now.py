"""Stub gerado de `system.clock.now` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/system.clock.now.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: leitura · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: a resposta traz a data e a hora locais do instante da
    chamada
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "system.clock.now"
CAPABILITY: Final = "system.clock.now"
RISK_CLASS: Final = "leitura"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 500
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "a resposta traz a data e a hora locais do instante da chamada"


@dataclass(frozen=True, slots=True)
class SystemClockNowEntrada:
    """Argumentos normalizados de `system.clock.now` (input_schema do §4)."""

    pass


@dataclass(frozen=True, slots=True)
class SystemClockNowSaida:
    """Resultado de `system.clock.now` (output_schema do §4)."""

    iso: Any
    hora: Any
    data_por_extenso: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(())
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> SystemClockNowEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return SystemClockNowEntrada(**bruto)


def executar(_entrada: SystemClockNowEntrada) -> SystemClockNowSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
