"""Stub gerado de `browser.acao_sensivel` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/browser.acao_sensivel.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: perigoso
  risco: representacao_do_dono · confirmação: per_action · egress: network:web
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o dono confirmou na janela esta ação, e só esta, antes de
    qualquer efeito
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "browser.acao_sensivel"
CAPABILITY: Final = "browser.acao_sensivel"
RISK_CLASS: Final = "representacao_do_dono"
CONFIRMATION: Final = "per_action"
TIER: Final = "perigoso"
DATA_EGRESS: Final = "network:web"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 35000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "o dono confirmou na janela esta ação, e só esta, antes de qualquer efeito"


@dataclass(frozen=True, slots=True)
class BrowserAcaoSensivelEntrada:
    """Argumentos normalizados de `browser.acao_sensivel` (input_schema do §4)."""

    acao: str
    detalhe: str


@dataclass(frozen=True, slots=True)
class BrowserAcaoSensivelSaida:
    """Resultado de `browser.acao_sensivel` (output_schema do §4)."""

    confirmado: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("acao", "detalhe"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("acao", "detalhe"))


def validar_entrada(bruto: dict[str, Any]) -> BrowserAcaoSensivelEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return BrowserAcaoSensivelEntrada(**bruto)


def executar(_entrada: BrowserAcaoSensivelEntrada) -> BrowserAcaoSensivelSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
