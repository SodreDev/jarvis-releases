"""Stub gerado de `memoria.criar_no` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/memoria.criar_no.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  risco: escrita_recuperavel · confirmação: once_per_batch · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: entidade e apelidos resolvíveis por entity_resolution
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "memoria.criar_no"
CAPABILITY: Final = "memoria.write.entidade"
RISK_CLASS: Final = "escrita_recuperavel"
CONFIRMATION: Final = "once_per_batch"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 500
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "entidade e apelidos resolvíveis por entity_resolution"


@dataclass(frozen=True, slots=True)
class MemoriaCriarNoEntrada:
    """Argumentos normalizados de `memoria.criar_no` (input_schema do §4)."""

    nome: str
    tipo: Any
    apelidos: list[Any] | None = None


@dataclass(frozen=True, slots=True)
class MemoriaCriarNoSaida:
    """Resultado de `memoria.criar_no` (output_schema do §4)."""

    entity_id: Any
    estado: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("nome", "tipo", "apelidos"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("nome", "tipo"))


def validar_entrada(bruto: dict[str, Any]) -> MemoriaCriarNoEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return MemoriaCriarNoEntrada(**bruto)


def executar(_entrada: MemoriaCriarNoEntrada) -> MemoriaCriarNoSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
