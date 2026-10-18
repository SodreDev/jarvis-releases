"""Stub gerado de `web.buscar` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/web.buscar.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: consulta_publica · confirmação: never · egress: network:web
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: os resultados vêm de uma fonte pública e a consulta não
    tinha segredo
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "web.buscar"
CAPABILITY: Final = "web.buscar"
RISK_CLASS: Final = "consulta_publica"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "network:web"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 12000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "os resultados vêm de uma fonte pública e a consulta não tinha segredo"


@dataclass(frozen=True, slots=True)
class WebBuscarEntrada:
    """Argumentos normalizados de `web.buscar` (input_schema do §4)."""

    consulta: str


@dataclass(frozen=True, slots=True)
class WebBuscarSaida:
    """Resultado de `web.buscar` (output_schema do §4)."""

    resultados: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("consulta",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("consulta",))


def validar_entrada(bruto: dict[str, Any]) -> WebBuscarEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return WebBuscarEntrada(**bruto)


def executar(_entrada: WebBuscarEntrada) -> WebBuscarSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
