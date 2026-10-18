"""Stub gerado de `files.create_dir` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/files.create_dir.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: escrita_recuperavel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: jarvis_root
  pós-condição verificada pelo executor: a pasta nova existe, vazia, dentro da raiz liberada
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "files.create_dir"
CAPABILITY: Final = "files.create_dir"
RISK_CLASS: Final = "escrita_recuperavel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 2000
ROOTS: Final[tuple[str, ...]] = ("jarvis_root",)
POSTCONDITION: Final = "a pasta nova existe, vazia, dentro da raiz liberada"


@dataclass(frozen=True, slots=True)
class FilesCreateDirEntrada:
    """Argumentos normalizados de `files.create_dir` (input_schema do §4)."""

    path: str


@dataclass(frozen=True, slots=True)
class FilesCreateDirSaida:
    """Resultado de `files.create_dir` (output_schema do §4)."""

    caminho: Any
    nome: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("path",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("path",))


def validar_entrada(bruto: dict[str, Any]) -> FilesCreateDirEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return FilesCreateDirEntrada(**bruto)


def executar(_entrada: FilesCreateDirEntrada) -> FilesCreateDirSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
