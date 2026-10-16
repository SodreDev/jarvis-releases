"""Qual backend de áudio usar, e a proibição de dispositivo real no CI (cartão F1-01).

`JARVIS_AUDIO_BACKEND` escolhe entre `arquivo`, `sintetico` e `dispositivo`. O padrão é
`sintetico`: quem não disse nada não vai abrir a placa de som do dono por acidente.

A proibição do dispositivo real quando `CI=1` mora aqui, no código de produção, e não só
numa fixture de teste — a fixture força `CI=1` na suíte inteira, mas é esta função que
recusa. Teste prova as duas pontas (`tests/unit/audio_io/test_backend.py`).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from jarvis.ambiente import (
    VALORES_VERDADEIROS,
    VARIAVEL_CI,
    ambiente_ou_os,
    em_ci,
)
from jarvis.audio_io.erros import DispositivoProibidoEmCI

__all__ = [
    "VALORES_VERDADEIROS",
    "VARIAVEL_BACKEND",
    "VARIAVEL_CI",
    "Backend",
    "backend_escolhido",
    "em_ci",
    "proibir_dispositivo_em_ci",
]

VARIAVEL_BACKEND: Final = "JARVIS_AUDIO_BACKEND"


class Backend(StrEnum):
    """As três implementações da §2 vistas de fora."""

    ARQUIVO = "arquivo"
    SINTETICO = "sintetico"
    DISPOSITIVO = "dispositivo"


def backend_escolhido(ambiente: Mapping[str, str] | None = None) -> Backend:
    """Backend pedido por `JARVIS_AUDIO_BACKEND`; valor desconhecido é erro, não padrão."""
    bruto = ambiente_ou_os(ambiente).get(VARIAVEL_BACKEND, "").strip().lower()
    if not bruto:
        return Backend.SINTETICO
    try:
        return Backend(bruto)
    except ValueError:
        validos = ", ".join(b.value for b in Backend)
        raise ValueError(f"{VARIAVEL_BACKEND}={bruto!r} não existe; use um de: {validos}") from None


def proibir_dispositivo_em_ci(ambiente: Mapping[str, str] | None = None) -> None:
    """Recusa abrir dispositivo real sob CI. Chamada antes de qualquer tentativa de abrir."""
    if em_ci(ambiente):
        raise DispositivoProibidoEmCI(
            f"{VARIAVEL_CI} está ligado: a suíte não abre dispositivo de áudio real "
            f"(use {VARIAVEL_BACKEND}=arquivo ou =sintetico)"
        )
