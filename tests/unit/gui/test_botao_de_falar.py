"""O botão e a barra de espaço de falar, com mouse e teclado de verdade (QTest, offscreen).

Bug do dono (2026-10-17): apertar ou segurar o botão de falar "interrompia sozinho" — o aperto
virava a tecla de barge-in mesmo com o Jarvis calado, a conversa dizia `⟂ interrompido (tecla)`
e o dono nunca chegava a falar. Aqui o laço é o de verdade (WAV como microfone, arquivo como
alto-falante); só o ASR é de mentira.
"""

# ruff: noqa: F811 — as fixtures vêm de `test_janela` e são parâmetros aqui
from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui`")

from PySide6.QtCore import QEventLoop, QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest

from jarvis.gui import foco
from jarvis.gui.ponte import Ponte
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao
from tests.unit.gui.test_janela import (  # noqa: F401 — fixtures
    abrir,
    aplicativo,
    sem_chaveiro,
    wav_longo,
)
from tests.unit.voz.test_app import MotorDeAsrFalso

CONFIGURACAO = Configuracao(asr="asr-whisper-local", tts="tts-parametrico", s2="eco", escuta="ptt")


def _esperar(app: QGuiApplication, segundos: float, ate: Callable[[], bool] | None = None) -> None:
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        if ate is not None and ate():
            return
        time.sleep(0.005)


def _botao(janela: QQuickView) -> QQuickItem:
    raiz = janela.rootObject()
    achado = raiz.findChild(QQuickItem, "botaoFalar")
    assert achado is not None
    return achado


def _centro(janela: QQuickView, item: QQuickItem) -> QPoint:
    ponto = item.mapToScene(item.boundingRect().center())
    return QPoint(round(ponto.x()), round(ponto.y()))


@pytest.fixture
def conversa(
    aplicativo: QGuiApplication,
    abrir: Callable[[Ponte], QQuickView],
    tmp_path: Path,
    sem_chaveiro: None,
) -> Iterator[tuple[QQuickView, Any, Aplicativo]]:
    laco = Aplicativo(
        configuracao=CONFIGURACAO,
        raiz=tmp_path / "sessao",
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        caminho_de_entrada=wav_longo(tmp_path / "entrada.wav"),
        caminho_de_saida=tmp_path / "saida.wav",
    )
    laco._asr = MotorDeAsrFalso()
    ponte = Ponte(
        raiz=tmp_path / "sessao",
        configuracao=CONFIGURACAO,
        caminho_da_configuracao=tmp_path / "jarvis-voz.toml",
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        aplicativo=laco,
    )
    janela = abrir(ponte)
    foco.ligar(janela)
    janela.show()
    _esperar(aplicativo, 0.5)
    tela = cast(Any, ponte)
    tela.iniciarConversa()
    _esperar(aplicativo, 3.0, ate=lambda: laco.estado.value == "ouvindo")
    assert laco.estado.value == "ouvindo"
    yield janela, tela, laco
    # Sem isto o laço de áudio segue vivo no teste seguinte e a janela é destruída por baixo dele.
    tela.pararConversa()
    _esperar(aplicativo, 3.0, ate=lambda: not tela._sessao.viva)


def _linhas(tela: Any) -> list[str]:
    return [linha["texto"] for linha in tela.transcricao]


def test_segurar_o_botao_com_o_jarvis_calado_nao_interrompe_nada(
    conversa: tuple[QQuickView, Any, Aplicativo], aplicativo: QGuiApplication
) -> None:
    janela, tela, laco = conversa
    epoch = laco.epoch
    ponto = _centro(janela, _botao(janela))

    QTest.mousePress(janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
    _esperar(aplicativo, 0.8)

    assert laco.epoch == epoch, "o aperto do botão subiu o epoch: interrompeu sem ter o que calar"
    assert laco.estado.value == "ouvindo"
    assert not any("interrompido" in linha for linha in _linhas(tela)), _linhas(tela)
    assert tela.microfone["aberta"] is True, "o microfone fechou com o botão apertado"

    QTest.mouseRelease(janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
    _esperar(aplicativo, 5.0, ate=lambda: bool(laco.turnos))
    assert laco.turnos, "soltar o botão não fechou o turno"
    assert laco.turnos[0].falou == "bom dia, Jarvis"
    assert not any("interrompido" in linha for linha in _linhas(tela)), _linhas(tela)


def test_a_barra_de_espaco_tambem_nao_interrompe_o_jarvis_calado(
    conversa: tuple[QQuickView, Any, Aplicativo], aplicativo: QGuiApplication
) -> None:
    janela, tela, laco = conversa
    epoch = laco.epoch

    QTest.keyPress(janela, Qt.Key.Key_Space)
    _esperar(aplicativo, 0.6)
    assert laco.epoch == epoch
    QTest.keyRelease(janela, Qt.Key.Key_Space)
    _esperar(aplicativo, 5.0, ate=lambda: bool(laco.turnos))

    assert laco.turnos
    assert not any("interrompido" in linha for linha in _linhas(tela)), _linhas(tela)


def test_apertar_com_o_jarvis_falando_interrompe(
    conversa: tuple[QQuickView, Any, Aplicativo], aplicativo: QGuiApplication
) -> None:
    janela, tela, laco = conversa
    laco._motor = None  # remontado abaixo com uma resposta comprida
    from jarvis.s2.motor_roteirizado import MotorRoteirizado

    laco._motor = MotorRoteirizado(resposta="uma resposta bem comprida. " * 12)
    laco._cerebro = None
    laco.abrir()
    tela.enviarTexto("conta uma história")
    _esperar(aplicativo, 5.0, ate=lambda: laco.estado.value == "falando")
    assert laco.estado.value == "falando"
    epoch = laco.epoch

    ponto = _centro(janela, _botao(janela))
    QTest.mousePress(janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
    _esperar(aplicativo, 2.0, ate=lambda: laco.epoch > epoch)
    QTest.mouseRelease(janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)

    assert laco.epoch > epoch, "apertar com o Jarvis falando tem de calá-lo"
    assert any("interrompido" in linha for linha in _linhas(tela))
