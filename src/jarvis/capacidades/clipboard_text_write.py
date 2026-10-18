"""Stub gerado de `clipboard.text.write` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/clipboard.text.write.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: a área de transferência tem o texto pedido
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "clipboard.text.write"
CAPABILITY: Final = "clipboard.text.write"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 3000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "a área de transferência tem o texto pedido"


@dataclass(frozen=True, slots=True)
class ClipboardTextWriteEntrada:
    """Argumentos normalizados de `clipboard.text.write` (input_schema do §4)."""

    texto: str


@dataclass(frozen=True, slots=True)
class ClipboardTextWriteSaida:
    """Resultado de `clipboard.text.write` (output_schema do §4)."""

    caracteres: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("texto",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("texto",))


def validar_entrada(bruto: dict[str, Any]) -> ClipboardTextWriteEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return ClipboardTextWriteEntrada(**bruto)


def executar(_entrada: ClipboardTextWriteEntrada) -> ClipboardTextWriteSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
