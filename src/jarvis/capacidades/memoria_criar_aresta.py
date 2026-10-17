"""Stub gerado de `memoria.criar_aresta` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/memoria.criar_aresta.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  risco: escrita_recuperavel · confirmação: once_per_batch · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: aresta com source_episode_id e validade
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "memoria.criar_aresta"
CAPABILITY: Final = "memoria.write.relacao"
RISK_CLASS: Final = "escrita_recuperavel"
CONFIRMATION: Final = "once_per_batch"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 500
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "aresta com source_episode_id e validade"


@dataclass(frozen=True, slots=True)
class MemoriaCriarArestaEntrada:
    """Argumentos normalizados de `memoria.criar_aresta` (input_schema do §4)."""

    destino: str
    origem: str
    relacao: str
    ate: str | None = None
    desde: str | None = None


@dataclass(frozen=True, slots=True)
class MemoriaCriarArestaSaida:
    """Resultado de `memoria.criar_aresta` (output_schema do §4)."""

    edge_id: Any
    estado: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("destino", "origem", "relacao", "ate", "desde"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("destino", "origem", "relacao"))


def validar_entrada(bruto: dict[str, Any]) -> MemoriaCriarArestaEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return MemoriaCriarArestaEntrada(**bruto)


def executar(_entrada: MemoriaCriarArestaEntrada) -> MemoriaCriarArestaSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
