"""Stub gerado de `memoria.retratar` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/memoria.retratar.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  risco: escrita_recuperavel · confirmação: once_per_batch · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: alvo com status retracted e valid_to
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "memoria.retratar"
CAPABILITY: Final = "memoria.write.retratacao"
RISK_CLASS: Final = "escrita_recuperavel"
CONFIRMATION: Final = "once_per_batch"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 500
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "alvo com status retracted e valid_to"


@dataclass(frozen=True, slots=True)
class MemoriaRetratarEntrada:
    """Argumentos normalizados de `memoria.retratar` (input_schema do §4)."""

    alvo_id: str


@dataclass(frozen=True, slots=True)
class MemoriaRetratarSaida:
    """Resultado de `memoria.retratar` (output_schema do §4)."""

    alvo_id: Any
    estado: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("alvo_id",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("alvo_id",))


def validar_entrada(bruto: dict[str, Any]) -> MemoriaRetratarEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return MemoriaRetratarEntrada(**bruto)


def executar(_entrada: MemoriaRetratarEntrada) -> MemoriaRetratarSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
