"""Stub gerado de `files.move_to_trash` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/files.move_to_trash.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  risco: escrita_recuperavel · confirmação: once_per_batch · egress: none
  modo mínimo: padrao · elevação: False · raízes: workspace_root
  pós-condição verificada pelo executor: arquivo ausente no caminho original E presente na lixeira
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "files.move_to_trash"
CAPABILITY: Final = "files.write.trash"
RISK_CLASS: Final = "escrita_recuperavel"
CONFIRMATION: Final = "once_per_batch"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "padrao"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 3000
ROOTS: Final[tuple[str, ...]] = ("workspace_root",)
POSTCONDITION: Final = "arquivo ausente no caminho original E presente na lixeira"


@dataclass(frozen=True, slots=True)
class FilesMoveToTrashEntrada:
    """Argumentos normalizados de `files.move_to_trash` (input_schema do §4)."""

    path: str


@dataclass(frozen=True, slots=True)
class FilesMoveToTrashSaida:
    """Resultado de `files.move_to_trash` (output_schema do §4)."""

    trash_id: Any
    restored_path_hint: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("path",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("path",))


def validar_entrada(bruto: dict[str, Any]) -> FilesMoveToTrashEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return FilesMoveToTrashEntrada(**bruto)


def executar(_entrada: FilesMoveToTrashEntrada) -> FilesMoveToTrashSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
