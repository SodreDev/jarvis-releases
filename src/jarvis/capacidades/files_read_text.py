"""Stub gerado de `files.read_text` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/files.read_text.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  risco: leitura · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: texto é o conteúdo do arquivo aberto sob a raiz do grant
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "files.read_text"
CAPABILITY: Final = "files.read.text"
RISK_CLASS: Final = "leitura"
CONFIRMATION: Final = "never"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 2000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "texto é o conteúdo do arquivo aberto sob a raiz do grant"


@dataclass(frozen=True, slots=True)
class FilesReadTextEntrada:
    """Argumentos normalizados de `files.read_text` (input_schema do §4)."""

    path: str


@dataclass(frozen=True, slots=True)
class FilesReadTextSaida:
    """Resultado de `files.read_text` (output_schema do §4)."""

    texto: Any
    truncado: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("path",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("path",))


def validar_entrada(bruto: dict[str, Any]) -> FilesReadTextEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return FilesReadTextEntrada(**bruto)


def executar(_entrada: FilesReadTextEntrada) -> FilesReadTextSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
