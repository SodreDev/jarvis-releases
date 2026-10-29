"""Stub gerado de `tela.mostrar` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/tela.mostrar.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: transitorio_reversivel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: a exibição está na janela com o HTML limpo pela allowlist,
    e o que saiu está em `removidos`
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "tela.mostrar"
CAPABILITY: Final = "tela.mostrar"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 2000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "a exibição está na janela com o HTML limpo pela allowlist, e o que saiu está em `removidos`"
)


@dataclass(frozen=True, slots=True)
class TelaMostrarEntrada:
    """Argumentos normalizados de `tela.mostrar` (input_schema do §4)."""

    html: str
    id: str | None = None
    titulo: str | None = None


@dataclass(frozen=True, slots=True)
class TelaMostrarSaida:
    """Resultado de `tela.mostrar` (output_schema do §4)."""

    caracteres: int
    id: str
    removidos: list[Any]
    fundo: str | None = None
    titulo: str | None = None


PERMITIDOS: Final[frozenset[str]] = frozenset(("html", "id", "titulo"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("html",))


def validar_entrada(bruto: dict[str, Any]) -> TelaMostrarEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return TelaMostrarEntrada(**bruto)


def executar(_entrada: TelaMostrarEntrada) -> TelaMostrarSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
