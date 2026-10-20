"""Stub gerado de `window.focus_app` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/window.focus_app.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: transitorio_reversivel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: a janela escolhida pelo código na lista real (ou a do
    janela_id, conferida nela) ficou em foco
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "window.focus_app"
CAPABILITY: Final = "window.focus_app"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 3000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "a janela escolhida pelo código na lista real (ou a do janela_id, conferida nela) ficou em foco"
)


@dataclass(frozen=True, slots=True)
class WindowFocusAppEntrada:
    """Argumentos normalizados de `window.focus_app` (input_schema do §4)."""

    app: str
    janela_id: str | None = None


@dataclass(frozen=True, slots=True)
class WindowFocusAppSaida:
    """Resultado de `window.focus_app` (output_schema do §4)."""

    janela_id: str | None = None


PERMITIDOS: Final[frozenset[str]] = frozenset(("app", "janela_id"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("app",))


def validar_entrada(bruto: dict[str, Any]) -> WindowFocusAppEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return WindowFocusAppEntrada(**bruto)


def executar(_entrada: WindowFocusAppEntrada) -> WindowFocusAppSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
