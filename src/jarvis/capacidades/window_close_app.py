"""Stub gerado de `window.close_app` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/window.close_app.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: perigoso
  risco: transitorio_reversivel · confirmação: per_action · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o gerenciador de janelas recebeu o pedido de fechar a
    janela escolhida
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "window.close_app"
CAPABILITY: Final = "window.close_app"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "per_action"
TIER: Final = "perigoso"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 3000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "o gerenciador de janelas recebeu o pedido de fechar a janela escolhida"


@dataclass(frozen=True, slots=True)
class WindowCloseAppEntrada:
    """Argumentos normalizados de `window.close_app` (input_schema do §4)."""

    app: str


@dataclass(frozen=True, slots=True)
class WindowCloseAppSaida:
    """Resultado de `window.close_app` (output_schema do §4)."""

    app: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("app",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("app",))


def validar_entrada(bruto: dict[str, Any]) -> WindowCloseAppEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return WindowCloseAppEntrada(**bruto)


def executar(_entrada: WindowCloseAppEntrada) -> WindowCloseAppSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
