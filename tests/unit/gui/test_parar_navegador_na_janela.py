"""O PARAR do navegador na janela do Jarvis (ADR-0027 regra 4; dono, 2026-10-21).

Enquanto o Jarvis controla uma aba, a barra da conversa mostra «parar o navegador»; o aviso vem
da linha que agiu (não da janela), e o clique solta as abas e cancela o turno e as tarefas que
estavam nelas — pelo mesmo caminho do PARAR da faixa da página.
"""

# ruff: noqa: F811 — as fixtures vêm de `test_janela` e são parâmetros aqui
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui`")

from PySide6.QtCore import QEventLoop, QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest

from jarvis.gui.ponte import Ponte
from jarvis.voz.config import Configuracao
from tests.unit.gui.test_janela import (  # noqa: F401 — fixtures
    abrir,
    aplicativo,
    sem_chaveiro,
)

PRAZO_S = 30.0
"""Teto das esperas pela janela. Generoso: sob carga o QML leva segundos para desenhar, e a espera
sai assim que a condição vale."""


class SessaoFalsa:
    viva = True

    def __init__(self) -> None:
        self.paradas = 0

    def parar_navegador(self) -> None:
        self.paradas += 1


def _esperar(app: QGuiApplication, segundos: float, ate: Callable[[], bool]) -> bool:
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        if ate():
            return True
        time.sleep(0.005)
    return ate()


def _botao(janela: QQuickView) -> QQuickItem:
    achado = janela.rootObject().findChild(QQuickItem, "botaoPararNavegador")
    assert achado is not None
    return achado


def test_o_parar_do_navegador_aparece_so_com_aba_no_controle_e_o_clique_para(
    tmp_path: Path,
    aplicativo: QGuiApplication,
    abrir: Callable[[Ponte], QQuickView],
    sem_chaveiro: None,
) -> None:
    ponte = Ponte(raiz=tmp_path, configuracao=Configuracao(s2="eco"))
    janela = abrir(ponte)
    janela.show()
    sessao = SessaoFalsa()
    ponte._sessao = sessao  # type: ignore[assignment]
    botao = _botao(janela)
    assert not botao.isVisible(), "sem aba no controle, sem botão"

    # O aviso vem da linha que agiu no navegador, não da janela.
    threading.Thread(target=ponte.navegadorMudou.emit, args=(True,)).start()

    def no_controle() -> bool:
        return bool(ponte.property("navegadorNoControle"))

    assert _esperar(aplicativo, PRAZO_S, lambda: no_controle() and botao.isVisible())

    ponto = botao.mapToScene(botao.boundingRect().center())
    QTest.mouseClick(
        janela,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(round(ponto.x()), round(ponto.y())),
    )

    assert _esperar(aplicativo, PRAZO_S, lambda: sessao.paradas == 1 and not botao.isVisible())
    assert not no_controle()
