"""Stub gerado de `browser.gesto` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/browser.gesto.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: local
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o gesto foi na mesma aba, no elemento inspecionado, e o
    risco foi avaliado antes
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "browser.gesto"
CAPABILITY: Final = "browser.gesto"
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
    "o gesto foi na mesma aba, no elemento inspecionado, e o risco foi avaliado antes"
)


@dataclass(frozen=True, slots=True)
class BrowserGestoEntrada:
    """Argumentos normalizados de `browser.gesto` (input_schema do §4)."""

    gesto: str
    alvo: str | None = None
    pixels: int | None = None
    ref: str | None = None
    tab_id: int | None = None
    texto: str | None = None


@dataclass(frozen=True, slots=True)
class BrowserGestoSaida:
    """Resultado de `browser.gesto` (output_schema do §4)."""

    feito: Any
    gesto: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("gesto", "alvo", "pixels", "ref", "tab_id", "texto"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("gesto",))


def validar_entrada(bruto: dict[str, Any]) -> BrowserGestoEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return BrowserGestoEntrada(**bruto)


def executar(_entrada: BrowserGestoEntrada) -> BrowserGestoSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
