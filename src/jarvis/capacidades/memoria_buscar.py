"""Stub gerado de `memoria.buscar` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/memoria.buscar.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: leitura · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: todo achado traz memory_unit_id e o caminho
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "memoria.buscar"
CAPABILITY: Final = "memoria.read.memoria"
RISK_CLASS: Final = "leitura"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 300
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "todo achado traz memory_unit_id e o caminho"


@dataclass(frozen=True, slots=True)
class MemoriaBuscarEntrada:
    """Argumentos normalizados de `memoria.buscar` (input_schema do §4)."""

    consulta: str
    instante: str | None = None


@dataclass(frozen=True, slots=True)
class MemoriaBuscarSaida:
    """Resultado de `memoria.buscar` (output_schema do §4)."""

    achados: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("consulta", "instante"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("consulta",))


def validar_entrada(bruto: dict[str, Any]) -> MemoriaBuscarEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return MemoriaBuscarEntrada(**bruto)


def executar(_entrada: MemoriaBuscarEntrada) -> MemoriaBuscarSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
