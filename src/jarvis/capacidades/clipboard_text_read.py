"""Stub gerado de `clipboard.text.read` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/clipboard.text.read.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: leitura · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o texto devolvido é o da área de transferência, já sem
    segredos
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "clipboard.text.read"
CAPABILITY: Final = "clipboard.text.read"
RISK_CLASS: Final = "leitura"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 3000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "o texto devolvido é o da área de transferência, já sem segredos"


@dataclass(frozen=True, slots=True)
class ClipboardTextReadEntrada:
    """Argumentos normalizados de `clipboard.text.read` (input_schema do §4)."""

    pass


@dataclass(frozen=True, slots=True)
class ClipboardTextReadSaida:
    """Resultado de `clipboard.text.read` (output_schema do §4)."""

    texto: Any
    vazia: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(())
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> ClipboardTextReadEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return ClipboardTextReadEntrada(**bruto)


def executar(_entrada: ClipboardTextReadEntrada) -> ClipboardTextReadSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
