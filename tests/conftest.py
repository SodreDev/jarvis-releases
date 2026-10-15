"""Fixtures comuns a todos os testes."""

from __future__ import annotations

import pytest

from jarvis.audio_io import VARIAVEL_CI
from jarvis.barramento import uuid7


@pytest.fixture
def sessao() -> str:
    """Identificador de sessão válido (uuid v7, §3.1)."""
    return uuid7()


@pytest.fixture(autouse=True)
def ci_ligado(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aceite (a) do F1-01: a suíte inteira roda como se fosse CI.

    Com `CI=1`, `proibir_dispositivo_em_ci` recusa abrir placa de som — então nenhum teste,
    nem um futuro, abre o microfone do dono por acidente. Quem precisa provar o caminho de
    fora do CI apaga a variável explicitamente (`monkeypatch.delenv`), e isso aparece no
    teste.
    """
    monkeypatch.setenv(VARIAVEL_CI, "1")
