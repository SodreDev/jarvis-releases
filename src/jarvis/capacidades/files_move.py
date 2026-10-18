"""Stub gerado de `files.move` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/files.move.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: escrita_recuperavel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: jarvis_root
  pós-condição verificada pelo executor: o item está no destino e saiu da origem, na mesma raiz
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "files.move"
CAPABILITY: Final = "files.move"
RISK_CLASS: Final = "escrita_recuperavel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 3000
ROOTS: Final[tuple[str, ...]] = ("jarvis_root",)
POSTCONDITION: Final = "o item está no destino e saiu da origem, na mesma raiz"


@dataclass(frozen=True, slots=True)
class FilesMoveEntrada:
    """Argumentos normalizados de `files.move` (input_schema do §4)."""

    destino: str
    origem: str


@dataclass(frozen=True, slots=True)
class FilesMoveSaida:
    """Resultado de `files.move` (output_schema do §4)."""

    de: Any
    para: Any
    nome: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("destino", "origem"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("destino", "origem"))


def validar_entrada(bruto: dict[str, Any]) -> FilesMoveEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return FilesMoveEntrada(**bruto)


def executar(_entrada: FilesMoveEntrada) -> FilesMoveSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
