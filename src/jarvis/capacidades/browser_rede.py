"""Stub gerado de `browser.rede` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/browser.rede.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: leitura · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: os pedidos vêm da mesma aba, sem nenhum efeito na página
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "browser.rede"
CAPABILITY: Final = "browser.rede"
RISK_CLASS: Final = "leitura"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 20000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "os pedidos vêm da mesma aba, sem nenhum efeito na página"


@dataclass(frozen=True, slots=True)
class BrowserRedeEntrada:
    """Argumentos normalizados de `browser.rede` (input_schema do §4)."""

    tab_id: int | None = None


@dataclass(frozen=True, slots=True)
class BrowserRedeSaida:
    """Resultado de `browser.rede` (output_schema do §4)."""

    pedidos: Any
    anexado: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("tab_id",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> BrowserRedeEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return BrowserRedeEntrada(**bruto)


def executar(_entrada: BrowserRedeEntrada) -> BrowserRedeSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
