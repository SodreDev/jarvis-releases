"""Stub gerado de `files.search_in_roots` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/files.search_in_roots.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: leitura · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: todo achado está dentro de uma raiz do modo e fora da lista
    de negação
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "files.search_in_roots"
CAPABILITY: Final = "files.read.search"
RISK_CLASS: Final = "leitura"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 2000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "todo achado está dentro de uma raiz do modo e fora da lista de negação"


@dataclass(frozen=True, slots=True)
class FilesSearchInRootsEntrada:
    """Argumentos normalizados de `files.search_in_roots` (input_schema do §4)."""

    consulta: str


@dataclass(frozen=True, slots=True)
class FilesSearchInRootsSaida:
    """Resultado de `files.search_in_roots` (output_schema do §4)."""

    achados: Any
    truncado: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("consulta",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("consulta",))


def validar_entrada(bruto: dict[str, Any]) -> FilesSearchInRootsEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return FilesSearchInRootsEntrada(**bruto)


def executar(_entrada: FilesSearchInRootsEntrada) -> FilesSearchInRootsSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
