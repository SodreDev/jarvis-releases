"""Stub gerado de `tela.fechar` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/tela.fechar.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: transitorio_reversivel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: as exibições pedidas saíram da janela
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "tela.fechar"
CAPABILITY: Final = "tela.fechar"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 500
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "as exibições pedidas saíram da janela"


@dataclass(frozen=True, slots=True)
class TelaFecharEntrada:
    """Argumentos normalizados de `tela.fechar` (input_schema do §4)."""

    id: str | None = None
    todas: bool | None = None


@dataclass(frozen=True, slots=True)
class TelaFecharSaida:
    """Resultado de `tela.fechar` (output_schema do §4)."""

    fechadas: list[Any]


PERMITIDOS: Final[frozenset[str]] = frozenset(("id", "todas"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> TelaFecharEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return TelaFecharEntrada(**bruto)


def executar(_entrada: TelaFecharEntrada) -> TelaFecharSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
