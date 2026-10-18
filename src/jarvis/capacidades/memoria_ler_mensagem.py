"""Stub gerado de `memoria.ler_mensagem` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/memoria.ler_mensagem.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: leitura · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: os turnos devolvidos são da mesma sessão, em ordem
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "memoria.ler_mensagem"
CAPABILITY: Final = "memoria.read.mensagem"
RISK_CLASS: Final = "leitura"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 300
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "os turnos devolvidos são da mesma sessão, em ordem"


@dataclass(frozen=True, slots=True)
class MemoriaLerMensagemEntrada:
    """Argumentos normalizados de `memoria.ler_mensagem` (input_schema do §4)."""

    episode_id: str
    vizinhos: int | None = None


@dataclass(frozen=True, slots=True)
class MemoriaLerMensagemSaida:
    """Resultado de `memoria.ler_mensagem` (output_schema do §4)."""

    turnos: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("episode_id", "vizinhos"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("episode_id",))


def validar_entrada(bruto: dict[str, Any]) -> MemoriaLerMensagemEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return MemoriaLerMensagemEntrada(**bruto)


def executar(_entrada: MemoriaLerMensagemEntrada) -> MemoriaLerMensagemSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
