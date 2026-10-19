"""Stub gerado de `input.key.press` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/input.key.press.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: local
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: a tecla saiu pelo backend de entrada do sistema, sem
    modificador preso, na janela conferida antes
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "input.key.press"
CAPABILITY: Final = "input.key.press"
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
    "a tecla saiu pelo backend de entrada do sistema, sem modificador preso, na janela conferida antes"
)


@dataclass(frozen=True, slots=True)
class InputKeyPressEntrada:
    """Argumentos normalizados de `input.key.press` (input_schema do §4)."""

    tecla: str


@dataclass(frozen=True, slots=True)
class InputKeyPressSaida:
    """Resultado de `input.key.press` (output_schema do §4)."""

    tecla: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("tecla",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("tecla",))


def validar_entrada(bruto: dict[str, Any]) -> InputKeyPressEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return InputKeyPressEntrada(**bruto)


def executar(_entrada: InputKeyPressEntrada) -> InputKeyPressSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
