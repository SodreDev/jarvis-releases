"""Stub gerado de `media.player.control` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/media.player.control.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: transitorio_reversivel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o player que estava tocando (ou o pedido) recebeu o comando
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "media.player.control"
CAPABILITY: Final = "media.player.control"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 3000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "o player que estava tocando (ou o pedido) recebeu o comando"


@dataclass(frozen=True, slots=True)
class MediaPlayerControlEntrada:
    """Argumentos normalizados de `media.player.control` (input_schema do §4)."""

    acao: Any
    player: str | None = None


@dataclass(frozen=True, slots=True)
class MediaPlayerControlSaida:
    """Resultado de `media.player.control` (output_schema do §4)."""

    acao: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("acao", "player"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("acao",))


def validar_entrada(bruto: dict[str, Any]) -> MediaPlayerControlEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return MediaPlayerControlEntrada(**bruto)


def executar(_entrada: MediaPlayerControlEntrada) -> MediaPlayerControlSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
