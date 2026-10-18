"""Stub gerado de `acao.desfazer` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/acao.desfazer.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: jarvis_root
  pós-condição verificada pelo executor: a ação sai do registro; o arquivo vai à lixeira ou a
    memória é retratada
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "acao.desfazer"
CAPABILITY: Final = "acao.desfazer"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 2000
ROOTS: Final[tuple[str, ...]] = ("jarvis_root",)
POSTCONDITION: Final = "a ação sai do registro; o arquivo vai à lixeira ou a memória é retratada"


@dataclass(frozen=True, slots=True)
class AcaoDesfazerEntrada:
    """Argumentos normalizados de `acao.desfazer` (input_schema do §4)."""

    acao_id: str | None = None


@dataclass(frozen=True, slots=True)
class AcaoDesfazerSaida:
    """Resultado de `acao.desfazer` (output_schema do §4)."""

    desfeito: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("acao_id",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> AcaoDesfazerEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return AcaoDesfazerEntrada(**bruto)


def executar(_entrada: AcaoDesfazerEntrada) -> AcaoDesfazerSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
