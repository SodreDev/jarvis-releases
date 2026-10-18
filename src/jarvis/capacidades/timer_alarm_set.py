"""Stub gerado de `timer.alarm.set` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/timer.alarm.set.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o alarme está na agenda, gravado em disco, e dispara no
    instante pedido
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "timer.alarm.set"
CAPABILITY: Final = "timer.alarm.set"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 1000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "o alarme está na agenda, gravado em disco, e dispara no instante pedido"


@dataclass(frozen=True, slots=True)
class TimerAlarmSetEntrada:
    """Argumentos normalizados de `timer.alarm.set` (input_schema do §4)."""

    mensagem: str
    em_segundos: int | None = None
    quando: str | None = None


@dataclass(frozen=True, slots=True)
class TimerAlarmSetSaida:
    """Resultado de `timer.alarm.set` (output_schema do §4)."""

    alarme_id: Any
    quando_humano: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("mensagem", "em_segundos", "quando"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("mensagem",))


def validar_entrada(bruto: dict[str, Any]) -> TimerAlarmSetEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return TimerAlarmSetEntrada(**bruto)


def executar(_entrada: TimerAlarmSetEntrada) -> TimerAlarmSetSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
