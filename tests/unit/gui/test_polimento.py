"""Rodada de polimento da janela: o que dá para cobrar sem olho humano.

O resto do polimento (tipografia, espaçamento, hierarquia) é julgado pelo dono nas capturas de
`/tmp/jarvis-telas/`. Aqui fica o que tem forma: o aviso de nuvem não empurra o botão para fora,
e o card de notificações desenha com os dados rotulados como demonstração.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui` (`uv sync --group gui`)")

from PySide6.QtCore import QEventLoop, QPointF
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem, QQuickView

from jarvis.gui.ponte import Ponte
from jarvis.voz.config import Configuracao, escrever
from tests.unit.gui.test_janela import abrir, aplicativo, sem_chaveiro  # noqa: F401 — fixtures


def assentar(app: QGuiApplication, milissegundos: int = 400) -> None:
    fim = time.monotonic() + milissegundos / 1000
    while time.monotonic() < fim:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)


def visiveis(janela: QQuickView, nome: str) -> list[QQuickItem]:
    """Pela árvore **visual** (`childItems`): o que Repeater e Loader criam não é filho QObject."""
    raiz = janela.rootObject()
    assert raiz is not None
    achados: list[QQuickItem] = []
    pilha = [raiz]
    while pilha:
        item = pilha.pop()
        if item.objectName() == nome and item.isVisible():
            achados.append(item)
        pilha.extend(item.childItems())
    return achados


def test_o_aviso_da_nuvem_tem_teto_e_o_botao_fica_logo_abaixo(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    caminho = tmp_path / "jarvis-voz.toml"
    escrever(Configuracao(tts="tts-elevenlabs"), caminho)
    ponte = Ponte(raiz=tmp_path / "sessao", caminho_da_configuracao=caminho)
    janela = abrir(ponte)
    janela.show()
    ponte.abrirPainel("configuracao")
    assentar(aplicativo, 900)

    caixas = visiveis(janela, "caixaDoAviso")
    assert len(caixas) == 1, "o aviso da ElevenLabs não apareceu"
    caixa = caixas[0]
    assert caixa.property("frases").property("length").toInt() > 2, "o aviso não virou frases"
    assert caixa.height() < 220, f"o aviso recolhido ocupa {caixa.height():.0f} px"

    botoes = visiveis(janela, "botaoDaNuvem")
    assert len(botoes) == 1
    fundo_da_caixa = caixa.mapToScene(QPointF(0, caixa.height())).y()
    topo_do_botao = botoes[0].mapToScene(QPointF(0, 0)).y()
    assert 0 <= topo_do_botao - fundo_da_caixa < 30, "o botão não está logo abaixo do aviso"

    caixa.setProperty("inteiro", True)
    assentar(aplicativo, 500)
    assert caixa.height() < 360, "aberto, o aviso ainda tem de ter teto (rola por dentro)"


def test_o_indicador_de_escuta_aparece_num_lugar_so(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    """Núcleo grande: o indicador mora nele. Núcleo encolhido: sobe para o cabeçalho."""
    ponte = Ponte(raiz=tmp_path / "sessao", caminho_da_configuracao=tmp_path / "jarvis-voz.toml")
    janela = abrir(ponte)
    janela.show()
    assentar(aplicativo, 700)
    assert len(visiveis(janela, "indicadorNoNucleo")) == 1
    assert visiveis(janela, "indicadorNoCabecalho") == []

    ponte.definirModo("pesquisa")
    assentar(aplicativo, 900)
    assert visiveis(janela, "indicadorNoNucleo") == []
    assert len(visiveis(janela, "indicadorNoCabecalho")) == 1


def test_a_linha_de_estado_nao_mexe_na_grade(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    """O Column do rodapé ignora item com opacidade 0: a frase que some não pode tirar a linha
    do layout, senão a grade inteira pula a cada aviso discreto."""
    ponte = Ponte(raiz=tmp_path / "sessao", caminho_da_configuracao=tmp_path / "jarvis-voz.toml")
    janela = abrir(ponte)
    janela.show()
    assentar(aplicativo, 600)
    (linha,) = visiveis(janela, "linhaDeEstado")
    assert linha.opacity() == 1.0 and linha.height() == 18
    topo_vazio = linha.mapToScene(QPointF(0, 0)).y()
    ponte.salvarConfiguracao()  # põe frase na linha
    assentar(aplicativo, 600)
    assert linha.mapToScene(QPointF(0, 0)).y() == topo_vazio
