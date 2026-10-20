"""Stub gerado de `browser.tela` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/browser.tela.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: leitura · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: a imagem e o mapa vêm da mesma aba no mesmo instante, e as
    caixas estão em pixels da imagem
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "browser.tela"
CAPABILITY: Final = "browser.tela"
RISK_CLASS: Final = "leitura"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 20000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "a imagem e o mapa vêm da mesma aba no mesmo instante, e as caixas estão em pixels da imagem"
)


@dataclass(frozen=True, slots=True)
class BrowserTelaEntrada:
    """Argumentos normalizados de `browser.tela` (input_schema do §4)."""

    tab_id: int | None = None


@dataclass(frozen=True, slots=True)
class BrowserTelaSaida:
    """Resultado de `browser.tela` (output_schema do §4)."""

    instantaneo: Any
    tela: Any
    inspecao: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("tab_id",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> BrowserTelaEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return BrowserTelaEntrada(**bruto)


def executar(_entrada: BrowserTelaEntrada) -> BrowserTelaSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
