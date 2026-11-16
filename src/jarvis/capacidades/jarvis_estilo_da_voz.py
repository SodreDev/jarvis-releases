"""Stub gerado de `jarvis.estilo_da_voz` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/jarvis.estilo_da_voz.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: transitorio_reversivel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o próximo trecho falado sai no estilo novo e a configuração
    do dono o guarda
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "jarvis.estilo_da_voz"
CAPABILITY: Final = "jarvis.estilo_da_voz"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 3000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "o próximo trecho falado sai no estilo novo e a configuração do dono o guarda"
)


@dataclass(frozen=True, slots=True)
class JarvisEstiloDaVozEntrada:
    """Argumentos normalizados de `jarvis.estilo_da_voz` (input_schema do §4)."""

    estilo: str


@dataclass(frozen=True, slots=True)
class JarvisEstiloDaVozSaida:
    """Resultado de `jarvis.estilo_da_voz` (output_schema do §4)."""

    estilo: str
    evento: str | None = None


PERMITIDOS: Final[frozenset[str]] = frozenset(("estilo",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("estilo",))


def validar_entrada(bruto: dict[str, Any]) -> JarvisEstiloDaVozEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return JarvisEstiloDaVozEntrada(**bruto)


def executar(_entrada: JarvisEstiloDaVozEntrada) -> JarvisEstiloDaVozSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
