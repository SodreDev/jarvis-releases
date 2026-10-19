"""Stub gerado de `web.canal_videos` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/web.canal_videos.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: consulta_publica · confirmação: never · egress: network:web
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: channel_id e RSS públicos revalidados a cada
    redirecionamento
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "web.canal_videos"
CAPABILITY: Final = "web.canal_videos"
RISK_CLASS: Final = "consulta_publica"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "network:web"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 12000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "channel_id e RSS públicos revalidados a cada redirecionamento"


@dataclass(frozen=True, slots=True)
class WebCanalVideosEntrada:
    """Argumentos normalizados de `web.canal_videos` (input_schema do §4)."""

    canal: str


@dataclass(frozen=True, slots=True)
class WebCanalVideosSaida:
    """Resultado de `web.canal_videos` (output_schema do §4)."""

    channel_id: Any
    videos: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("canal",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("canal",))


def validar_entrada(bruto: dict[str, Any]) -> WebCanalVideosEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return WebCanalVideosEntrada(**bruto)


def executar(_entrada: WebCanalVideosEntrada) -> WebCanalVideosSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
