"""Stub gerado de `memoria.lembrar` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/memoria.lembrar.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: escrita_recuperavel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: assertiva gravada com source_episode_id do turno corrente
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "memoria.lembrar"
CAPABILITY: Final = "memoria.write.memoria"
RISK_CLASS: Final = "escrita_recuperavel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 500
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "assertiva gravada com source_episode_id do turno corrente"


@dataclass(frozen=True, slots=True)
class MemoriaLembrarEntrada:
    """Argumentos normalizados de `memoria.lembrar` (input_schema do §4)."""

    texto: str
    predicado: str | None = None
    sujeito: str | None = None


@dataclass(frozen=True, slots=True)
class MemoriaLembrarSaida:
    """Resultado de `memoria.lembrar` (output_schema do §4)."""

    assertion_id: Any
    estado: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("texto", "predicado", "sujeito"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("texto",))


def validar_entrada(bruto: dict[str, Any]) -> MemoriaLembrarEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return MemoriaLembrarEntrada(**bruto)


def executar(_entrada: MemoriaLembrarEntrada) -> MemoriaLembrarSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
