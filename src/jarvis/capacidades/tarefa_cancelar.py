"""Stub gerado de `tarefa.cancelar` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/tarefa.cancelar.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: transitorio_reversivel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: a tarefa recebe o cancelamento e vira cancelada na próxima
    checagem do passo em curso
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "tarefa.cancelar"
CAPABILITY: Final = "tarefa.cancelar"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 1000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "a tarefa recebe o cancelamento e vira cancelada na próxima checagem do passo em curso"
)


@dataclass(frozen=True, slots=True)
class TarefaCancelarEntrada:
    """Argumentos normalizados de `tarefa.cancelar` (input_schema do §4)."""

    tarefa_id: str


@dataclass(frozen=True, slots=True)
class TarefaCancelarSaida:
    """Resultado de `tarefa.cancelar` (output_schema do §4)."""

    tarefa_id: Any
    estado: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("tarefa_id",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("tarefa_id",))


def validar_entrada(bruto: dict[str, Any]) -> TarefaCancelarEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return TarefaCancelarEntrada(**bruto)


def executar(_entrada: TarefaCancelarEntrada) -> TarefaCancelarSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
