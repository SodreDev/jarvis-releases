"""Stub gerado de `script.rodar` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/script.rodar.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  tier: moderado
  risco: transitorio_reversivel · confirmação: never · egress: local
  modo mínimo: jarvis · elevação: False · raízes: (nenhuma)
  pós-condição verificada pelo executor: o script rodou numa caixa sem rede nem os arquivos do dono,
    e o que ele imprimiu voltou como dado
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "script.rodar"
CAPABILITY: Final = "script.rodar"
RISK_CLASS: Final = "transitorio_reversivel"
CONFIRMATION: Final = "never"
TIER: Final = "moderado"
DATA_EGRESS: Final = "local"
ACCESS_LEVEL_MIN: Final = "jarvis"
REQUIRES_ELEVATION: Final = False
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 20000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = (
    "o script rodou numa caixa sem rede nem os arquivos do dono, e o que ele imprimiu voltou como "
    "dado"
)


@dataclass(frozen=True, slots=True)
class ScriptRodarEntrada:
    """Argumentos normalizados de `script.rodar` (input_schema do §4)."""

    codigo: str
    linguagem: str
    entrada: str | None = None
    rede: bool | None = None


@dataclass(frozen=True, slots=True)
class ScriptRodarSaida:
    """Resultado de `script.rodar` (output_schema do §4)."""

    saida: Any
    erro: Any
    codigo_de_saida: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("codigo", "linguagem", "entrada", "rede"))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("codigo", "linguagem"))


def validar_entrada(bruto: dict[str, Any]) -> ScriptRodarEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return ScriptRodarEntrada(**bruto)


def executar(_entrada: ScriptRodarEntrada) -> ScriptRodarSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
