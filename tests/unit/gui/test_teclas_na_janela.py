"""O atalho de falar com a janela em foco, com tecla de verdade (QTest, offscreen).

Bug do dono (2026-10-16): um clique no campo de texto prendia o foco nele, e a barra de espaço
passava a digitar — o aperto se perdia e só o soltar chegava ao laço.
"""

# ruff: noqa: F811 — as fixtures vêm de `test_janela` e são parâmetros aqui
from __future__ import annotations

import os
import time
from pathlib import Path

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
from jarvis.microfone import ler_estado
from jarvis.voz.config import Configuracao
from tests.unit.gui.test_janela import (  # noqa: F401 — fixtures
    abrir,
    aplicativo,
    sem_chaveiro,
)


class SessaoQueAnota:
    """No lugar do laço: só anota o que a janela pediu."""

    viva = True

    def __init__(self, raiz: Path) -> None:
        self.pedidos: list[str] = []
        self.raiz = raiz

    def estado_do_microfone(self) -> object:
        return ler_estado(self.raiz)

    def segurar(self) -> None:
        self.pedidos.append("segurar")

    def soltar(self) -> None:
        self.pedidos.append("soltar")

    def interromper(self) -> None:
        self.pedidos.append("interromper")

    def parar(self) -> None:
        self.pedidos.append("parar")

    def digitar(self, texto: str) -> None:
        self.pedidos.append(f"digitar:{texto}")

    def dados_dos_avisos(self) -> dict[str, list[dict[str, str]]]:
        return {"avisos": []}


def _esperar(app: QGuiApplication, ms: int = 150) -> None:
    fim = time.monotonic() + ms / 1000
    while time.monotonic() < fim:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)


def _campo(janela: QQuickView) -> QQuickItem:
    raiz = janela.rootObject()
    assert raiz is not None
    achado = raiz.findChild(QQuickItem, "campoDaConversa")
    assert achado is not None
    return achado


def _digitar(janela: QQuickView, texto: str) -> None:
    for letra in texto:
        QTest.keyClick(janela, Qt.Key(ord(letra.upper())), Qt.KeyboardModifier.NoModifier)


def _espaco(janela: QQuickView, app: QGuiApplication) -> None:
    QTest.keyPress(janela, Qt.Key.Key_Space)
    _esperar(app, 60)
    QTest.keyRelease(janela, Qt.Key.Key_Space)
    _esperar(app)


@pytest.fixture
def janela_e_sessao(
    abrir: object, aplicativo: QGuiApplication, tmp_path: Path, sem_chaveiro: None
) -> tuple[QQuickView, SessaoQueAnota]:
    ponte = Ponte(
        raiz=tmp_path,
        configuracao=Configuracao(asr="asr-whisper-local", tts="tts-parametrico", s2="eco"),
        caminho_da_configuracao=tmp_path / "jarvis-voz.toml",
        ambiente={"CI": "1"},
    )
    sessao = SessaoQueAnota(tmp_path)
    ponte._sessao = sessao  # type: ignore[assignment]
    janela = abrir(ponte)  # type: ignore[operator]
    foco.ligar(janela)  # o mesmo que `principal.main` liga
    janela.show()
    _esperar(aplicativo, 400)
    return janela, sessao


def test_espaco_segura_e_solta_na_janela_recem_aberta(
    janela_e_sessao: tuple[QQuickView, SessaoQueAnota], aplicativo: QGuiApplication
) -> None:
    janela, sessao = janela_e_sessao
    _espaco(janela, aplicativo)
    assert sessao.pedidos == ["segurar", "soltar"]


def test_com_o_campo_vazio_focado_o_espaco_ainda_e_o_atalho(
    janela_e_sessao: tuple[QQuickView, SessaoQueAnota], aplicativo: QGuiApplication
) -> None:
    janela, sessao = janela_e_sessao
    campo = _campo(janela)
    campo.forceActiveFocus()
    _esperar(aplicativo)
    assert campo.hasActiveFocus()

    _espaco(janela, aplicativo)
    assert sessao.pedidos == ["segurar", "soltar"]


def test_com_texto_no_campo_o_espaco_digita(
    janela_e_sessao: tuple[QQuickView, SessaoQueAnota], aplicativo: QGuiApplication
) -> None:
    janela, sessao = janela_e_sessao
    campo = _campo(janela)
    campo.forceActiveFocus()
    _digitar(janela, "oi")
    _espaco(janela, aplicativo)
    assert campo.property("text") == "oi "
    assert "segurar" not in sessao.pedidos


def test_clique_fora_do_campo_devolve_o_foco_a_tela(
    janela_e_sessao: tuple[QQuickView, SessaoQueAnota], aplicativo: QGuiApplication
) -> None:
    janela, sessao = janela_e_sessao
    campo = _campo(janela)
    campo.forceActiveFocus()
    _digitar(janela, "rascunho")
    QTest.mouseClick(
        janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(60, 300)
    )
    _esperar(aplicativo)
    assert not campo.hasActiveFocus()

    _espaco(janela, aplicativo)
    assert sessao.pedidos == ["segurar", "soltar"]


def test_esc_no_campo_devolve_o_foco_e_o_espaco_volta_a_falar(
    janela_e_sessao: tuple[QQuickView, SessaoQueAnota], aplicativo: QGuiApplication
) -> None:
    janela, sessao = janela_e_sessao
    campo = _campo(janela)
    campo.forceActiveFocus()
    _digitar(janela, "abc")
    QTest.keyClick(janela, Qt.Key.Key_Escape)
    _esperar(aplicativo)
    assert not campo.hasActiveFocus()
    _espaco(janela, aplicativo)
    assert sessao.pedidos[-2:] == ["segurar", "soltar"]
