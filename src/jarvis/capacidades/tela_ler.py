"""Stub gerado de `tela.ler` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/tela.ler.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: leitura · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: a resposta traz o HTML limpo da exibição pedida, sem o tema
    do Jarvis
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "tela.ler"
CAPABILITY: Final = "tela.ler"
RISK_CLASS: Final = "leitura"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 500
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "a resposta traz o HTML limpo da exibição pedida, sem o tema do Jarvis"


@dataclass(frozen=True, slots=True)
class TelaLerEntrada:
    """Argumentos normalizados de `tela.ler` (input_schema do §4)."""

    id: str | None = None


@dataclass(frozen=True, slots=True)
class TelaLerSaida:
    """Resultado de `tela.ler` (output_schema do §4)."""

    html: str
    id: str
    titulo: str | None = None


PERMITIDOS: Final[frozenset[str]] = frozenset(("id",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> TelaLerEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return TelaLerEntrada(**bruto)


def executar(_entrada: TelaLerEntrada) -> TelaLerSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
