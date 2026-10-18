"""Stub gerado de `files.list_dir` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/files.list_dir.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: leitura · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: entradas são filhas diretas da pasta pedida, sem as negadas
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "files.list_dir"
CAPABILITY: Final = "files.read.list"
RISK_CLASS: Final = "leitura"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 2000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "entradas são filhas diretas da pasta pedida, sem as negadas"


@dataclass(frozen=True, slots=True)
class FilesListDirEntrada:
    """Argumentos normalizados de `files.list_dir` (input_schema do §4)."""

    path: str


@dataclass(frozen=True, slots=True)
class FilesListDirSaida:
    """Resultado de `files.list_dir` (output_schema do §4)."""

    entradas: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("path",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("path",))


def validar_entrada(bruto: dict[str, Any]) -> FilesListDirEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return FilesListDirEntrada(**bruto)


def executar(_entrada: FilesListDirEntrada) -> FilesListDirSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
