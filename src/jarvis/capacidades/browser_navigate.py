"""Stub gerado de `browser.navigate` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/browser.navigate.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: local
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: a aba (a atual, a escolhida, uma nova se pedida ou uma na
    janela do Jarvis) mostra a página pedida, conferida pela extensão, sem credencial; à vista do
    dono quando ele pediu para ver, e sem tirar o foco dele no trabalho de fundo
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "browser.navigate"
CAPABILITY: Final = "browser.navigate"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "local"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 15000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "a aba (a atual, a escolhida, uma nova se pedida ou uma na janela do Jarvis) mostra a página "
    "pedida, conferida pela extensão, sem credencial; à vista do dono quando ele pediu para ver, e "
    "sem tirar o foco dele no trabalho de fundo"
)


@dataclass(frozen=True, slots=True)
class BrowserNavigateEntrada:
    """Argumentos normalizados de `browser.navigate` (input_schema do §4)."""

    url: str
    nova_aba: bool | None = None
    segundo_plano: bool | None = None
    tab_id: int | None = None


@dataclass(frozen=True, slots=True)
class BrowserNavigateSaida:
    """Resultado de `browser.navigate` (output_schema do §4)."""

    url: Any
    dominio: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("url", "nova_aba", "segundo_plano", "tab_id"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("url",))


def validar_entrada(bruto: dict[str, Any]) -> BrowserNavigateEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return BrowserNavigateEntrada(**bruto)


def executar(_entrada: BrowserNavigateEntrada) -> BrowserNavigateSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
