"""Stub gerado de `modelo.preset` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/modelo.preset.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: escrita_recuperavel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o preset nomeado é o ativo do papel dele em presets.toml e
    vale no pedido seguinte
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "modelo.preset"
CAPABILITY: Final = "modelo.write.preset"
RISK_CLASS: Final = "escrita_recuperavel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "none"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 500
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "o preset nomeado é o ativo do papel dele em presets.toml e vale no pedido seguinte"
)


@dataclass(frozen=True, slots=True)
class ModeloPresetEntrada:
    """Argumentos normalizados de `modelo.preset` (input_schema do §4)."""

    nome: str


@dataclass(frozen=True, slots=True)
class ModeloPresetSaida:
    """Resultado de `modelo.preset` (output_schema do §4)."""

    papel: str
    preset: str
    desfazer: str | None = None
    modelo: str | None = None
    provedor: str | None = None


PERMITIDOS: Final[frozenset[str]] = frozenset(("nome",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("nome",))


def validar_entrada(bruto: dict[str, Any]) -> ModeloPresetEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return ModeloPresetEntrada(**bruto)


def executar(_entrada: ModeloPresetEntrada) -> ModeloPresetSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
