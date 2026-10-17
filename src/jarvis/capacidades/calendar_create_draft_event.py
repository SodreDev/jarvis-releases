"""Stub gerado de `calendar.create_draft_event` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/calendar.create_draft_event.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  risco: escrita_recuperavel · confirmação: per_action · egress: none
  modo mínimo: jarvis · elevação: False · raízes: jarvis_root
  pós-condição verificada pelo executor: arquivo .ics novo na pasta de rascunhos de agenda, sem
    convidados
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "calendar.create_draft_event"
CAPABILITY: Final = "calendar.write.draft"
RISK_CLASS: Final = "escrita_recuperavel"
CONFIRMATION: Final = "per_action"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 2000
ROOTS: Final[tuple[str, ...]] = ("jarvis_root",)
POSTCONDITION: Final = "arquivo .ics novo na pasta de rascunhos de agenda, sem convidados"


@dataclass(frozen=True, slots=True)
class CalendarCreateDraftEventEntrada:
    """Argumentos normalizados de `calendar.create_draft_event` (input_schema do §4)."""

    inicio: str
    titulo: str
    duracao_min: int | None = None
    local: str | None = None


@dataclass(frozen=True, slots=True)
class CalendarCreateDraftEventSaida:
    """Resultado de `calendar.create_draft_event` (output_schema do §4)."""

    caminho: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("inicio", "titulo", "duracao_min", "local"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("inicio", "titulo"))


def validar_entrada(bruto: dict[str, Any]) -> CalendarCreateDraftEventEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return CalendarCreateDraftEventEntrada(**bruto)


def executar(_entrada: CalendarCreateDraftEventEntrada) -> CalendarCreateDraftEventSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
