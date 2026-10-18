"""Stub gerado de `notify.desktop.send` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/notify.desktop.send.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: transitorio_reversivel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o desktop recebeu a notificação com o título e o texto
    pedidos
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "notify.desktop.send"
CAPABILITY: Final = "notify.desktop.send"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 3000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "o desktop recebeu a notificação com o título e o texto pedidos"


@dataclass(frozen=True, slots=True)
class NotifyDesktopSendEntrada:
    """Argumentos normalizados de `notify.desktop.send` (input_schema do §4)."""

    texto: str
    titulo: str


@dataclass(frozen=True, slots=True)
class NotifyDesktopSendSaida:
    """Resultado de `notify.desktop.send` (output_schema do §4)."""

    titulo: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("texto", "titulo"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("texto", "titulo"))


def validar_entrada(bruto: dict[str, Any]) -> NotifyDesktopSendEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return NotifyDesktopSendEntrada(**bruto)


def executar(_entrada: NotifyDesktopSendEntrada) -> NotifyDesktopSendSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
