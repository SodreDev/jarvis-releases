"""Stub gerado de `tarefa.iniciar` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/tarefa.iniciar.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: local
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: a tarefa existe, roda em linha própria e é cancelável; o id
    voltou sem esperar o fim
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "tarefa.iniciar"
CAPABILITY: Final = "tarefa.iniciar"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "local"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 1000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "a tarefa existe, roda em linha própria e é cancelável; o id voltou sem esperar o fim"
)


@dataclass(frozen=True, slots=True)
class TarefaIniciarEntrada:
    """Argumentos normalizados de `tarefa.iniciar` (input_schema do §4)."""

    descricao: str
    tool: str
    parametros: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class TarefaIniciarSaida:
    """Resultado de `tarefa.iniciar` (output_schema do §4)."""

    tarefa_id: Any
    estado: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("descricao", "tool", "parametros"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("descricao", "tool"))


def validar_entrada(bruto: dict[str, Any]) -> TarefaIniciarEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return TarefaIniciarEntrada(**bruto)


def executar(_entrada: TarefaIniciarEntrada) -> TarefaIniciarSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
