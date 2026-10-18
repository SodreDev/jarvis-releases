"""Stub gerado de `media.player.status` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/media.player.status.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: leitura · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: a resposta lista os players de mídia abertos no instante da
    chamada, ou diz que não há nenhum
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "media.player.status"
CAPABILITY: Final = "media.player.status"
RISK_CLASS: Final = "leitura"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 3000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "a resposta lista os players de mídia abertos no instante da chamada, ou diz que não há nenhum"
)


@dataclass(frozen=True, slots=True)
class MediaPlayerStatusEntrada:
    """Argumentos normalizados de `media.player.status` (input_schema do §4)."""

    pass


@dataclass(frozen=True, slots=True)
class MediaPlayerStatusSaida:
    """Resultado de `media.player.status` (output_schema do §4)."""

    players: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(())
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> MediaPlayerStatusEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return MediaPlayerStatusEntrada(**bruto)


def executar(_entrada: MediaPlayerStatusEntrada) -> MediaPlayerStatusSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
