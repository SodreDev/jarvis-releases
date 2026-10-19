"""Stub gerado de `browser.read` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/browser.read.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: leitura · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o texto vem da aba pedida, sem script, e o endereço da aba
    foi conferido antes de ler
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "browser.read"
CAPABILITY: Final = "browser.read"
RISK_CLASS: Final = "leitura"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 15000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "o texto vem da aba pedida, sem script, e o endereço da aba foi conferido antes de ler"
)


@dataclass(frozen=True, slots=True)
class BrowserReadEntrada:
    """Argumentos normalizados de `browser.read` (input_schema do §4)."""

    tab_id: int | None = None


@dataclass(frozen=True, slots=True)
class BrowserReadSaida:
    """Resultado de `browser.read` (output_schema do §4)."""

    url: Any
    texto: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("tab_id",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> BrowserReadEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return BrowserReadEntrada(**bruto)


def executar(_entrada: BrowserReadEntrada) -> BrowserReadSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
