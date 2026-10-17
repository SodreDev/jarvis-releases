"""Stub gerado de `system.install_package` — NÃO EDITE À MÃO.

Gerado por `jarvis.manifesto.codegen` a partir de
`catalogo/system.install_package.yaml` (SPEC §4).
Para mudar a assinatura, mude o manifesto e gere de novo:

    uv run --frozen python tools/manifesto.py codegen

Política desta capacidade (decidida no repositório, nunca pelo modelo):
  risco: mudanca_de_sistema · confirmação: per_action · egress: network:repositorio-da-distro
  modo mínimo: total · elevação: True · raízes: (nenhuma)
  pós-condição verificada pelo executor: pacote presente na versão informada
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

ID: Final = "system.install_package"
CAPABILITY: Final = "system.write.packages"
RISK_CLASS: Final = "mudanca_de_sistema"
CONFIRMATION: Final = "per_action"
DATA_EGRESS: Final = "network:repositorio-da-distro"
ACCESS_LEVEL_MIN: Final = "total"
REQUIRES_ELEVATION: Final = True
IDEMPOTENCY: Final = "required"
TIMEOUT_MS: Final = 120000
ROOTS: Final[tuple[str, ...]] = ()
POSTCONDITION: Final = "pacote presente na versão informada"


@dataclass(frozen=True, slots=True)
class SystemInstallPackageEntrada:
    """Argumentos normalizados de `system.install_package` (input_schema do §4)."""

    package_id: str


@dataclass(frozen=True, slots=True)
class SystemInstallPackageSaida:
    """Resultado de `system.install_package` (output_schema do §4)."""

    package_id: Any
    version: Any


PERMITIDOS: Final[frozenset[str]] = frozenset(("package_id",))
OBRIGATORIOS: Final[frozenset[str]] = frozenset(("package_id",))


def validar_entrada(bruto: dict[str, Any]) -> SystemInstallPackageEntrada:
    """Recusa argumento fora do contrato antes de qualquer efeito (§2, executor)."""
    extras = set(bruto) - PERMITIDOS
    if extras:
        raise ValueError(f"{ID}: argumento fora do contrato: {sorted(extras)}")
    faltando = OBRIGATORIOS - set(bruto)
    if faltando:
        raise ValueError(f"{ID}: argumento obrigatório ausente: {sorted(faltando)}")
    return SystemInstallPackageEntrada(**bruto)


def executar(_entrada: SystemInstallPackageEntrada) -> SystemInstallPackageSaida:
    """Corpo da capacidade: implementado pelo executor na fase que a entregar.

    O stub existe para o contrato ser verificável antes da implementação; chamar isto
    agora é erro de programação, não de uso.
    """
    raise NotImplementedError(
        f"{ID} ainda não foi implementada: o stub vem do manifesto, a execução vem do executor"
    )
