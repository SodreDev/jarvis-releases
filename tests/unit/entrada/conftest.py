"""Rede de proteção: nenhum teste desta pasta toca a entrada, o portal ou a tela do dono.

Um backend de verdade só se alcança por engano — por exemplo, montando `EntradaPorPortal` no
barramento `SESSION` ou `Dispositivo` em `/dev/uinput`. Estas travas transformam o engano em falha.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from jarvis.entrada import portal_remoto, uinput


@pytest.fixture(autouse=True)
def _sem_entrada_real(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    abrir_portal = portal_remoto.EntradaPorPortal.abrir

    def portal(self: Any) -> None:
        if self._endereco == "SESSION":
            raise AssertionError("teste tentou abrir o portal da sessão REAL do dono")
        abrir_portal(self)

    def disco(self: Any) -> None:
        raise AssertionError("teste tentou abrir o /dev/uinput real")

    monkeypatch.setattr(portal_remoto.EntradaPorPortal, "abrir", portal)
    monkeypatch.setattr(uinput.Dispositivo, "abrir", disco)
    yield
