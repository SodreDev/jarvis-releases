"""Stub gerado de `vocabulario.aprender` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/vocabulario.aprender.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: escrita_recuperavel · confirmação: never · egress: none
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o termo está em vocabulario-aprendido.toml e vale já na
    dica do ASR, na correção da transcrição e na pronúncia do TTS
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "vocabulario.aprender"
CAPABILITY: Final = "voz.write.vocabulario"
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
    "o termo está em vocabulario-aprendido.toml e vale já na dica do ASR, na correção da "
    "transcrição e na pronúncia do TTS"
)


@dataclass(frozen=True, slots=True)
class VocabularioAprenderEntrada:
    """Argumentos normalizados de `vocabulario.aprender` (input_schema do §4)."""

    escrita: str
    fala: str | None = None
    ouvido: list[Any] | None = None
    tipo: str | None = None


@dataclass(frozen=True, slots=True)
class VocabularioAprenderSaida:
    """Resultado de `vocabulario.aprender` (output_schema do §4)."""

    escrita: str
    termo_id: str
    fala: str | None = None
    ouvido: list[Any] | None = None


PERMITIDOS: Final[frozenset[str]] = frozenset(("escrita", "fala", "ouvido", "tipo"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("escrita",))


def validar_entrada(bruto: dict[str, Any]) -> VocabularioAprenderEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return VocabularioAprenderEntrada(**bruto)


def executar(_entrada: VocabularioAprenderEntrada) -> VocabularioAprenderSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
