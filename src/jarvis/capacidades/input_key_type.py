"""Stub gerado de `input.key.type` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/input.key.type.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: local
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o texto saiu pelo backend de entrada do sistema, na janela
    que estava em foco e foi conferida antes
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "input.key.type"
CAPABILITY: Final = "input.key.type"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "local"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 30000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "o texto saiu pelo backend de entrada do sistema, na janela que estava em foco e foi conferida antes"
)


@dataclass(frozen=True, slots=True)
class InputKeyTypeEntrada:
    """Argumentos normalizados de `input.key.type` (input_schema do §4)."""

    texto: str


@dataclass(frozen=True, slots=True)
class InputKeyTypeSaida:
    """Resultado de `input.key.type` (output_schema do §4)."""

    caracteres: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("texto",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("texto",))


def validar_entrada(bruto: dict[str, Any]) -> InputKeyTypeEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return InputKeyTypeEntrada(**bruto)


def executar(_entrada: InputKeyTypeEntrada) -> InputKeyTypeSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
