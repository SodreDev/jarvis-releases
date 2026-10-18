"""Stub gerado de `sites.open` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/sites.open.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: transitorio_reversivel · confirmação: never · egress: local
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o navegador configurado (ou o portal do desktop) aceitou
    abrir a URL
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "sites.open"
CAPABILITY: Final = "sites.open"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "local"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 3000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "o navegador configurado (ou o portal do desktop) aceitou abrir a URL"


@dataclass(frozen=True, slots=True)
class SitesOpenEntrada:
    """Argumentos normalizados de `sites.open` (input_schema do §4)."""

    url: str
    navegador: str | None = None


@dataclass(frozen=True, slots=True)
class SitesOpenSaida:
    """Resultado de `sites.open` (output_schema do §4)."""

    url: Any
    dominio: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("url", "navegador"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("url",))


def validar_entrada(bruto: dict[str, Any]) -> SitesOpenEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return SitesOpenEntrada(**bruto)


def executar(_entrada: SitesOpenEntrada) -> SitesOpenSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
