"""Toda `Ponte` criada num teste da janela fica parada e viva até o fim do processo.

Causa raiz de um segfault intermitente da suíte (2026-10-17, gdb: `QTimerInfoList::
activateTimers` → `QCoreApplication::notifyInternal2` num objeto destruído): uma `Ponte` criada
**sem janela** não ia para `PRESAS`; ao fim do teste o coletor do Python a destruía — às vezes
noutra linha de execução —, e o relógio de 1 s dela continuava registrado no laço de eventos
da thread principal. O próximo tique entregava o evento a um objeto morto. Cada teste novo que
criava uma ponte solta aumentava a chance; com duas a mais a suíte passou a cair quase sempre.

Aqui, na thread principal e no fim de cada teste: a conversa para (com teto), o relógio desliga
e a referência fica guardada — nada é destruído no meio da suíte.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest

SEGURADAS: list[Any] = []
"""Pontes de todos os testes, vivas até o fim do processo (soltá-las é o que derrubava)."""


@pytest.fixture(autouse=True)
def pontes_seguras(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    try:
        from PySide6.QtCore import QCoreApplication, QEventLoop

        from jarvis.gui.ponte import Ponte
    except ImportError:  # sem o grupo `gui`, os testes daqui são pulados
        yield
        return
    criadas: list[Any] = []
    original = Ponte.__init__

    def registrar(self: Any, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        criadas.append(self)

    monkeypatch.setattr(Ponte, "__init__", registrar)
    yield
    app = QCoreApplication.instance()
    for ponte in criadas:
        sessao = ponte._sessao
        if hasattr(sessao, "parar"):  # alguns testes põem uma sessão falsa, sem laço
            ponte.pararConversa()
        fim = time.monotonic() + 5.0
        while getattr(sessao, "viva", False) is True and time.monotonic() < fim:
            if app is not None:
                app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
            time.sleep(0.01)
        ponte._tique.stop()
    SEGURADAS.extend(criadas)
