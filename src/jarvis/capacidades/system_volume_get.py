"""Stub gerado de `system.volume.get` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/system.volume.get.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: livre
  risco: leitura · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o volume devolvido é o do dispositivo de saída padrão no
    instante da chamada
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "system.volume.get"
CAPABILITY: Final = "system.volume.get"
RISK_CLASS: Final = "leitura"
CONFIRMATION: Final = "never"
TIER: Final = "livre"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "not_required"
TIMEOUT_MS: Final = 3000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "o volume devolvido é o do dispositivo de saída padrão no instante da chamada"
)


@dataclass(frozen=True, slots=True)
class SystemVolumeGetEntrada:
    """Argumentos normalizados de `system.volume.get` (input_schema do §4)."""

    pass


@dataclass(frozen=True, slots=True)
class SystemVolumeGetSaida:
    """Resultado de `system.volume.get` (output_schema do §4)."""

    volume_pct: Any
    mudo: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(())
OBRIGATORIOS: Final[frozenset[str]] = frozenset(())


def validar_entrada(bruto: dict[str, Any]) -> SystemVolumeGetEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return SystemVolumeGetEntrada(**bruto)


def executar(_entrada: SystemVolumeGetEntrada) -> SystemVolumeGetSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
