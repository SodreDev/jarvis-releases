"""Stub gerado de `tarefa.estado` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/tarefa.estado.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: leitura · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o estado devolvido reflete o das tarefas no instante da
    chamada
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "tarefa.estado"
CAPABILITY: Final = "tarefa.estado"
RISK_CLASS: Final = "leitura"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 500
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "o estado devolvido reflete o das tarefas no instante da chamada"


@dataclass(frozen=True, slots=True)
class TarefaEstadoEntrada:
    """Argumentos normalizados de `tarefa.estado` (input_schema do §4)."""

    tarefa_id: str | None = None


@dataclass(frozen=True, slots=True)
class TarefaEstadoSaida:
    """Resultado de `tarefa.estado` (output_schema do §4)."""

    tarefas: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("tarefa_id",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> TarefaEstadoEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return TarefaEstadoEntrada(**bruto)


def executar(_entrada: TarefaEstadoEntrada) -> TarefaEstadoSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
