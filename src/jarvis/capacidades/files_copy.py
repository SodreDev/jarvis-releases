"""Stub gerado de `files.copy` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/files.copy.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: escrita_recuperavel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: jarvis_root
  pós-condição verificada pelo executor: o arquivo novo existe no destino com o mesmo conteúdo e a
    origem não mudou
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "files.copy"
CAPABILITY: Final = "files.copy"
RISK_CLASS: Final = "escrita_recuperavel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 10000
ROOTS: Final[tuple[str, ...]] = ("jarvis_root",)
POSTCONDITION: Final = "o arquivo novo existe no destino com o mesmo conteúdo e a origem não mudou"


@dataclass(frozen=True, slots=True)
class FilesCopyEntrada:
    """Argumentos normalizados de `files.copy` (input_schema do §4)."""

    destino: str
    origem: str


@dataclass(frozen=True, slots=True)
class FilesCopySaida:
    """Resultado de `files.copy` (output_schema do §4)."""

    caminho: Any
    nome: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("destino", "origem"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("destino", "origem"))


def validar_entrada(bruto: dict[str, Any]) -> FilesCopyEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return FilesCopyEntrada(**bruto)


def executar(_entrada: FilesCopyEntrada) -> FilesCopySaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
