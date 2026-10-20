"""Stub gerado de `browser.click` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/browser.click.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: local
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o elemento foi inspecionado antes do clique e o clique foi
    no mesmo elemento da mesma aba
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "browser.click"
CAPABILITY: Final = "browser.click"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "local"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 20000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "o elemento foi inspecionado antes do clique e o clique foi no mesmo elemento da mesma aba"
)


@dataclass(frozen=True, slots=True)
class BrowserClickEntrada:
    """Argumentos normalizados de `browser.click` (input_schema do §4)."""

    alvo: str | None = None
    ref: str | None = None
    tab_id: int | None = None


@dataclass(frozen=True, slots=True)
class BrowserClickSaida:
    """Resultado de `browser.click` (output_schema do §4)."""

    clicado: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("alvo", "ref", "tab_id"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> BrowserClickEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return BrowserClickEntrada(**bruto)


def executar(_entrada: BrowserClickEntrada) -> BrowserClickSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
