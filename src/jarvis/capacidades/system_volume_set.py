"""Stub gerado de `system.volume.set` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/system.volume.set.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: transitorio_reversivel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o volume da saída padrão passou ao valor pedido e a
    resposta traz o valor lido
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "system.volume.set"
CAPABILITY: Final = "system.volume.set"
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
    "o volume da saída padrão passou ao valor pedido e a resposta traz o valor lido"
)


@dataclass(frozen=True, slots=True)
class SystemVolumeSetEntrada:
    """Argumentos normalizados de `system.volume.set` (input_schema do §4)."""

    delta: int | None = None
    mudo: bool | None = None
    nivel: int | None = None


@dataclass(frozen=True, slots=True)
class SystemVolumeSetSaida:
    """Resultado de `system.volume.set` (output_schema do §4)."""

    volume_pct: Any
    mudo: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("delta", "mudo", "nivel"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> SystemVolumeSetEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return SystemVolumeSetEntrada(**bruto)


def executar(_entrada: SystemVolumeSetEntrada) -> SystemVolumeSetSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
