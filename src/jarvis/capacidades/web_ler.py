"""Stub gerado de `web.ler` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/web.ler.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: consulta_publica · confirmação: never · egress: network:web
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o texto vem de uma página pública, sem script, e o endereço
    final foi conferido
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "web.ler"
CAPABILITY: Final = "web.ler"
RISK_CLASS: Final = "consulta_publica"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "network:web"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 12000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "o texto vem de uma página pública, sem script, e o endereço final foi conferido"
)


@dataclass(frozen=True, slots=True)
class WebLerEntrada:
    """Argumentos normalizados de `web.ler` (input_schema do §4)."""

    url: str | None = None
    urls: list[Any] | None = None


@dataclass(frozen=True, slots=True)
class WebLerSaida:
    """Resultado de `web.ler` (output_schema do §4)."""

    paginas: list[Any] | None = None
    texto: str | None = None
    url: str | None = None


PERMITIDOS: Final[frozenset[str]] = frozenset(("url", "urls"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> WebLerEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return WebLerEntrada(**bruto)


def executar(_entrada: WebLerEntrada) -> WebLerSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
