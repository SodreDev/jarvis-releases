"""Stub gerado de `memoria.atualizar` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/memoria.atualizar.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: perigoso
  risco: escrita_recuperavel · confirmação: per_action · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: antiga superseded com valid_to; a nova ativa a substitui
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "memoria.atualizar"
CAPABILITY: Final = "memoria.write.correcao"
RISK_CLASS: Final = "escrita_recuperavel"
CONFIRMATION: Final = "per_action"
TIER: Final = "perigoso"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 500
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "antiga superseded com valid_to; a nova ativa a substitui"


@dataclass(frozen=True, slots=True)
class MemoriaAtualizarEntrada:
    """Argumentos normalizados de `memoria.atualizar` (input_schema do §4)."""

    assertion_id: str
    motivo: str
    texto: str


@dataclass(frozen=True, slots=True)
class MemoriaAtualizarSaida:
    """Resultado de `memoria.atualizar` (output_schema do §4)."""

    assertion_id: Any
    substituida: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("assertion_id", "motivo", "texto"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("assertion_id", "motivo", "texto"))


def validar_entrada(bruto: dict[str, Any]) -> MemoriaAtualizarEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return MemoriaAtualizarEntrada(**bruto)


def executar(_entrada: MemoriaAtualizarEntrada) -> MemoriaAtualizarSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
