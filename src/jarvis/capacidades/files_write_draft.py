"""Stub gerado de `files.write_draft` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/files.write_draft.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  risco: escrita_recuperavel · confirmação: per_action · egress: none
  modo mínimo: jarvis · elevação: False · raízes: jarvis_root
  pós-condição verificada pelo executor: arquivo novo existe na pasta de rascunhos com o texto
    pedido
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "files.write_draft"
CAPABILITY: Final = "files.write.draft"
RISK_CLASS: Final = "escrita_recuperavel"
CONFIRMATION: Final = "per_action"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 2000
ROOTS: Final[tuple[str, ...]] = ("jarvis_root",)
POSTCONDITION: Final = "arquivo novo existe na pasta de rascunhos com o texto pedido"


@dataclass(frozen=True, slots=True)
class FilesWriteDraftEntrada:
    """Argumentos normalizados de `files.write_draft` (input_schema do §4)."""

    nome: str
    texto: str


@dataclass(frozen=True, slots=True)
class FilesWriteDraftSaida:
    """Resultado de `files.write_draft` (output_schema do §4)."""

    caminho: Any
    bytes: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("nome", "texto"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("nome", "texto"))


def validar_entrada(bruto: dict[str, Any]) -> FilesWriteDraftEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return FilesWriteDraftEntrada(**bruto)


def executar(_entrada: FilesWriteDraftEntrada) -> FilesWriteDraftSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
