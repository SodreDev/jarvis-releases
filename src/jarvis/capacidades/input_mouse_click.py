"""Stub gerado de `input.mouse.click` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/input.mouse.click.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: local
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o clique saiu pelo backend de entrada do sistema, com a
    janela em foco conferida antes
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "input.mouse.click"
CAPABILITY: Final = "input.mouse.click"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "local"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 10000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "o clique saiu pelo backend de entrada do sistema, com a janela em foco conferida antes"
)


@dataclass(frozen=True, slots=True)
class InputMouseClickEntrada:
    """Argumentos normalizados de `input.mouse.click` (input_schema do §4)."""

    botao: str | None = None
    vezes: int | None = None


@dataclass(frozen=True, slots=True)
class InputMouseClickSaida:
    """Resultado de `input.mouse.click` (output_schema do §4)."""

    botao: Any
    vezes: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("botao", "vezes"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> InputMouseClickEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return InputMouseClickEntrada(**bruto)


def executar(_entrada: InputMouseClickEntrada) -> InputMouseClickSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
