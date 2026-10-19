"""Stub gerado de `browser.scroll` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/browser.scroll.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: local
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: a página rolou no máximo 2000 pixels, na aba pedida
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "browser.scroll"
CAPABILITY: Final = "browser.scroll"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "local"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 8000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "a página rolou no máximo 2000 pixels, na aba pedida"


@dataclass(frozen=True, slots=True)
class BrowserScrollEntrada:
    """Argumentos normalizados de `browser.scroll` (input_schema do §4)."""

    pixels: int | None = None
    tab_id: int | None = None


@dataclass(frozen=True, slots=True)
class BrowserScrollSaida:
    """Resultado de `browser.scroll` (output_schema do §4)."""

    deslocamento: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("pixels", "tab_id"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> BrowserScrollEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return BrowserScrollEntrada(**bruto)


def executar(_entrada: BrowserScrollEntrada) -> BrowserScrollSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
