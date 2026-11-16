"""Stub gerado de `jarvis.permissao` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/jarvis.permissao.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o PDP vivo usa o modo novo e a configuração do dono o
    guarda
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "jarvis.permissao"
CAPABILITY: Final = "jarvis.permissao"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 3000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "o PDP vivo usa o modo novo e a configuração do dono o guarda"


@dataclass(frozen=True, slots=True)
class JarvisPermissaoEntrada:
    """Argumentos normalizados de `jarvis.permissao` (input_schema do §4)."""

    modo: str


@dataclass(frozen=True, slots=True)
class JarvisPermissaoSaida:
    """Resultado de `jarvis.permissao` (output_schema do §4)."""

    modo: str
    evento: str | None = None


PERMITIDOS: Final[frozenset[str]] = frozenset(("modo",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("modo",))


def validar_entrada(bruto: dict[str, Any]) -> JarvisPermissaoEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return JarvisPermissaoEntrada(**bruto)


def executar(_entrada: JarvisPermissaoEntrada) -> JarvisPermissaoSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
