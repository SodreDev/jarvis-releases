"""Stub gerado de `jarvis.encerrar` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/jarvis.encerrar.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o laço de voz para no fim do turno, com as tarefas
    canceladas, a entrada virtual solta, as abas soltas e a conversa guardada; a janela fecha
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "jarvis.encerrar"
CAPABILITY: Final = "jarvis.encerrar"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 3000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "o laço de voz para no fim do turno, com as tarefas canceladas, a entrada virtual solta, as "
    "abas soltas e a conversa guardada; a janela fecha"
)


@dataclass(frozen=True, slots=True)
class JarvisEncerrarEntrada:
    """Argumentos normalizados de `jarvis.encerrar` (input_schema do §4)."""

    pass


@dataclass(frozen=True, slots=True)
class JarvisEncerrarSaida:
    """Resultado de `jarvis.encerrar` (output_schema do §4)."""

    encerrando: bool
    tarefas_canceladas: int | None = None


PERMITIDOS: Final[frozenset[str]] = frozenset(())
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> JarvisEncerrarEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return JarvisEncerrarEntrada(**bruto)


def executar(_entrada: JarvisEncerrarEntrada) -> JarvisEncerrarSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
