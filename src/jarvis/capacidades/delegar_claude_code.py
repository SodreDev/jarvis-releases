"""Stub gerado de `delegar.claude_code` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/delegar.claude_code.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: local
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o Claude Code rodou a tarefa sem permissões amplas, só com
    as ferramentas do navegador, e o que ele devolveu voltou como dado
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "delegar.claude_code"
CAPABILITY: Final = "delegar.claude_code"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "local"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 600000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "o Claude Code rodou a tarefa sem permissões amplas, só com as ferramentas do navegador, e o "
    "que ele devolveu voltou como dado"
)


@dataclass(frozen=True, slots=True)
class DelegarClaudeCodeEntrada:
    """Argumentos normalizados de `delegar.claude_code` (input_schema do §4)."""

    tarefa: str
    site: str | None = None


@dataclass(frozen=True, slots=True)
class DelegarClaudeCodeSaida:
    """Resultado de `delegar.claude_code` (output_schema do §4)."""

    feito: Any
    codigo: Any
    resultado_do_claude_code: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("tarefa", "site"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("tarefa",))


def validar_entrada(bruto: dict[str, Any]) -> DelegarClaudeCodeEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return DelegarClaudeCodeEntrada(**bruto)


def executar(_entrada: DelegarClaudeCodeEntrada) -> DelegarClaudeCodeSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
