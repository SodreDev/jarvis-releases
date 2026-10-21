"""Stub gerado de `browser.launch` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/browser.launch.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: transitorio_reversivel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: processo do navegador iniciado numa sessão própria, sem
    URL; ou, já aberto, a janela do dono à frente e nenhuma janela nova
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "browser.launch"
CAPABILITY: Final = "browser.launch"
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
    "processo do navegador iniciado numa sessão própria, sem URL; ou, já aberto, a janela do dono "
    "à frente e nenhuma janela nova"
)


@dataclass(frozen=True, slots=True)
class BrowserLaunchEntrada:
    """Argumentos normalizados de `browser.launch` (input_schema do §4)."""

    navegador: str | None = None


@dataclass(frozen=True, slots=True)
class BrowserLaunchSaida:
    """Resultado de `browser.launch` (output_schema do §4)."""

    navegador: Any
    pid: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("navegador",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> BrowserLaunchEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return BrowserLaunchEntrada(**bruto)


def executar(_entrada: BrowserLaunchEntrada) -> BrowserLaunchSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
