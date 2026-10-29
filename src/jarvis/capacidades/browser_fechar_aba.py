"""Stub gerado de `browser.fechar_aba` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/browser.fechar_aba.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: a aba saiu do navegador; fora do escopo do pedido, só
    depois do sim do dono
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "browser.fechar_aba"
CAPABILITY: Final = "browser.fechar_aba"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 8000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "a aba saiu do navegador; fora do escopo do pedido, só depois do sim do dono"


@dataclass(frozen=True, slots=True)
class BrowserFecharAbaEntrada:
    """Argumentos normalizados de `browser.fechar_aba` (input_schema do §4)."""

    tab_id: int | None = None


@dataclass(frozen=True, slots=True)
class BrowserFecharAbaSaida:
    """Resultado de `browser.fechar_aba` (output_schema do §4)."""

    fechada: bool
    tab_id: int
    dominio: str | None = None
    titulo: str | None = None


PERMITIDOS: Final[frozenset[str]] = frozenset(("tab_id",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> BrowserFecharAbaEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return BrowserFecharAbaEntrada(**bruto)


def executar(_entrada: BrowserFecharAbaEntrada) -> BrowserFecharAbaSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
