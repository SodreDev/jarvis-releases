"""Stub gerado de `memoria.apagar` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/memoria.apagar.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: perigoso
  risco: apagar_permanente · confirmação: per_action · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: varredura de bruto, FTS, índice e grafo não acha o alvo
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "memoria.apagar"
CAPABILITY: Final = "memoria.write.exclusao"
RISK_CLASS: Final = "apagar_permanente"
CONFIRMATION: Final = "per_action"
TIER: Final = "perigoso"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 500
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "varredura de bruto, FTS, índice e grafo não acha o alvo"


@dataclass(frozen=True, slots=True)
class MemoriaApagarEntrada:
    """Argumentos normalizados de `memoria.apagar` (input_schema do §4)."""

    alvo_id: str
    escopo: Any


@dataclass(frozen=True, slots=True)
class MemoriaApagarSaida:
    """Resultado de `memoria.apagar` (output_schema do §4)."""

    removidos: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("alvo_id", "escopo"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("alvo_id", "escopo"))


def validar_entrada(bruto: dict[str, Any]) -> MemoriaApagarEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return MemoriaApagarEntrada(**bruto)


def executar(_entrada: MemoriaApagarEntrada) -> MemoriaApagarSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
