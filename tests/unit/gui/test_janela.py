"""A janela de verdade, desenhada sem tela: QML carrega, os três modos saem em PNG e a
interface **não** congela enquanto o laço de voz roda (ADR-0019).

`QT_QPA_PLATFORM=offscreen` com o renderizador de software desenha tudo em memória — é o que
deixa este teste rodar em CI, em contêiner e nesta máquina sem abrir janela nenhuma. As
capturas vão para `/tmp/jarvis-telas/`, fora do repositório: elas são para o dono olhar, não
para versionar.
"""

from __future__ import annotations

import os
import time
import wave
from collections.abc import Callable, Iterator
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui` (`uv sync --group gui`)")

from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtQuick import QQuickView

from jarvis.audio_io.quadro import TAXA_PADRAO, de_int16
from jarvis.gui import chaveiro, principal
from jarvis.gui.ponte import ModeloDeModulos, Ponte
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao
from jarvis.voz.estado import Estado
from tests.unit.voz.test_app import MotorDeAsrFalso

PRESAS: list[tuple[QQuickView, Ponte]] = []
"""Janelas já usadas, seguradas até o fim do processo (ver o desmonte da fixture `abrir`)."""

TELAS = Path(os.environ.get("JARVIS_TELAS", "/tmp/jarvis-telas/teste"))  # noqa: S108
"""Onde as capturas do **teste** saem: uma subpasta, para não sobrescrever as telas que o dono
pediu em `/tmp/jarvis-telas/` — as dele saem de `jarvis --capturar`, com a configuração dele.
`JARVIS_TELAS` aponta para outro lugar sem tocar no teste."""
CONFIGURACAO = Configuracao(asr="asr-whisper-local", tts="tts-parametrico", s2="eco")


class ChaveiroFalso:
    """Nenhum teste conversa com o chaveiro do dono."""

    def get_keyring(self) -> object:
        return self

    def get_password(self, servico: str, conta: str) -> str | None:
        return None


@pytest.fixture(scope="module")
def aplicativo() -> Iterator[QGuiApplication]:
    existente = QGuiApplication.instance()
    app = existente if isinstance(existente, QGuiApplication) else QGuiApplication([])
    yield app


@pytest.fixture
def sem_chaveiro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chaveiro, "_modulo", ChaveiroFalso)


def wav_longo(caminho: Path, segundos: float = 30.0) -> Path:
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(TAXA_PADRAO)
        arquivo.writeframes(de_int16([300] * int(TAXA_PADRAO * segundos)))
    return caminho


@pytest.fixture
def abrir(aplicativo: QGuiApplication) -> Iterator[Callable[[Ponte], QQuickView]]:
    """Abre a janela e **desmonta** no fim.

    Desmontar não é zelo: o QML fica com ligações para a ponte, e deixar a janela viva depois
    de o teste soltar a ponte derruba o processo inteiro no próximo tique do Qt — foi o que
    aconteceu na primeira versão deste arquivo, com um despejo de núcleo em vez de uma falha.
    """
    vivas: list[tuple[QQuickView, Ponte]] = []

    def _abrir(ponte: Ponte) -> QQuickView:
        janela = QQuickView()
        janela.rootContext().setContextProperty("ponte", ponte)
        qml = Path(principal.__file__).resolve().parent / "qml"
        janela.engine().addImportPath(str(qml))
        janela.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        janela.setSource(QUrl.fromLocalFile(str(qml / "JarvisUI" / "Principal.qml")))
        janela.resize(*principal.TAMANHO)
        vivas.append((janela, ponte))
        return janela

    yield _abrir

    for janela, _ponte in vivas:
        janela.close()
    aplicativo.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    # A janela e a ponte ficam **vivas** até o fim do processo, de propósito: destruir o
    # QQuickView aqui derruba o interpretador (o motor QML ainda tem ligações para a ponte, e
    # o coletor do Python desmonta os dois em ordem arbitrária). Num teste, segurar as duas
    # referências custa memória; soltar custa um despejo de núcleo.
    PRESAS.extend(vivas)
    vivas.clear()


def test_o_qml_carrega_sem_um_erro_sequer(
    abrir: Callable[[Ponte], QQuickView], tmp_path: Path, sem_chaveiro: None
) -> None:
    ponte = Ponte(raiz=tmp_path / "sessao", caminho_da_configuracao=tmp_path / "jarvis-voz.toml")

    janela = abrir(ponte)

    assert [str(erro) for erro in janela.errors()] == []
    assert janela.status() is QQuickView.Status.Ready
    assert janela.rootObject() is not None


def test_as_capturas_dos_modos_e_dos_paineis_saem_desenhadas(
    aplicativo: QGuiApplication,
    abrir: Callable[[Ponte], QQuickView],
    tmp_path: Path,
    sem_chaveiro: None,
) -> None:
    """O aceite que o dono pediu: um PNG por modo, para ele julgar o acabamento."""
    ponte = Ponte(raiz=tmp_path / "sessao", caminho_da_configuracao=tmp_path / "jarvis-voz.toml")
    janela = abrir(ponte)

    salvos = principal.capturar(aplicativo, janela, ponte, TELAS, com_diagnostico=False)

    assert {caminho.name for caminho in salvos} >= {
        "jarvis-assistente.png",
        "jarvis-pesquisa.png",
        "jarvis-execucao.png",
        "jarvis-configuracao.png",
        "jarvis-diagnostico.png",
    }
    for caminho in salvos:
        assert caminho.exists() and caminho.stat().st_size > 10_000, caminho
        imagem = QImage(str(caminho))
        assert imagem.width() == principal.TAMANHO[0]
        cores = {
            imagem.pixel(x, y)
            for x in range(0, imagem.width(), 23)
            for y in range(0, imagem.height(), 19)
        }
        assert len(cores) > 12, f"{caminho.name} saiu quase vazia: nada foi desenhado"


def test_trocar_de_modo_muda_a_composicao(
    abrir: Callable[[Ponte], QQuickView], tmp_path: Path, sem_chaveiro: None
) -> None:
    ponte = Ponte(raiz=tmp_path / "sessao", caminho_da_configuracao=tmp_path / "jarvis-voz.toml")
    abrir(ponte)
    # As propriedades existem para o QML, não para o verificador de tipos: `Property` é um
    # descritor do PySide6, e o mypy só vê o descritor. O `cast` é a maneira honesta de dizer
    # "aqui eu estou olhando a tela como o QML olha".
    tela = cast(Any, ponte)

    tela.definirModo("assistente")
    nucleo_assistente = dict(tela.nucleo)
    modulos_assistente = tela.modulos.rowCount()
    tela.definirModo("pesquisa")

    assert tela.modo == "pesquisa"
    assert dict(tela.nucleo) != nucleo_assistente, "o núcleo não encolheu no modo de pesquisa"
    assert modulos_assistente > 0 and tela.modulos.rowCount() > 0


def test_o_painel_de_provedores_abre_maximizado_sem_derrubar_nada(
    abrir: Callable[[Ponte], QQuickView], tmp_path: Path, sem_chaveiro: None
) -> None:
    ponte = Ponte(raiz=tmp_path / "sessao", caminho_da_configuracao=tmp_path / "jarvis-voz.toml")
    abrir(ponte)
    tela = cast(Any, ponte)
    modelo = tela.modulos
    antes = modelo.rowCount()

    tela.abrirPainel("configuracao")

    assert modelo.rowCount() == antes + 1
    maximizados = [
        linha
        for linha in range(modelo.rowCount())
        if modelo.data(modelo.index(linha, 0), ModeloDeModulos.PAPEL_BASE + 12)
    ]
    assert len(maximizados) == 1, "o painel do dono tem de abrir ocupando a tela"


def test_a_interface_nao_congela_enquanto_o_laco_de_voz_roda(
    aplicativo: QGuiApplication,
    abrir: Callable[[Ponte], QQuickView],
    tmp_path: Path,
    sem_chaveiro: None,
) -> None:
    """O aceite do dono: nada de trabalho pesado na thread da interface.

    A medida é direta: um cronômetro do Qt que deveria bater a cada 20 ms. Se o laço de voz
    estivesse rodando na thread da interface, o intervalo entre batidas seria o tempo de um
    turno inteiro (ASR, resposta, síntese) — centenas de milissegundos, ou segundos.
    """
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
    abrir(ponte)

    batidas: list[float] = []
    cronometro = QTimer()
    cronometro.setInterval(20)
    cronometro.timeout.connect(lambda: batidas.append(time.monotonic()))
    cronometro.start()

    tela = cast(Any, ponte)
    tela.iniciarConversa()
    tela.enviarTexto("bom dia")
    fim = time.monotonic() + 3.0
    while time.monotonic() < fim:
        aplicativo.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        time.sleep(0.004)
    cronometro.stop()
    tela.pararConversa()

    assert len(batidas) > 40, "o cronômetro da interface quase não bateu"
    maior_intervalo = max(b - a for a, b in pairwise(batidas))
    assert maior_intervalo < 0.25, f"a interface travou {maior_intervalo * 1000:.0f} ms"
    assert laco.turnos, "o laço não chegou a fechar um turno (o teste não provou nada)"
    assert laco.estado in set(Estado), "o estado publicado saiu do vocabulário"
