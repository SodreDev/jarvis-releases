"""Tarefas em segundo plano pela janela (ADR-0022; dono, 2026-10-18).

Janela real (QML offscreen), laço real, executor real sobre uma casa de mentira e um motor
roteirizado no lugar do modelo. O comando "longo" é a busca em pastas, que o teste segura:

- o Jarvis responde "vou procurar em segundo plano" e **continua conversando** com a tarefa rodando;
- o card `tarefas` nasce com os dados reais (sem selo de demonstração): nome, estado, progresso e o
  botão "parar";
- parar cancela a tarefa e o aviso entra pela fila (card `notificacoes`);
- terminar sozinha também avisa.

As capturas saem em `/tmp/jarvis-telas/tarefas/`.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterator, Sequence
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

from jarvis.executor import arquivos
from jarvis.gui.ponte import Ponte
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao
from tests.unit.gui.test_janela import (  # noqa: F401 — fixtures
    abrir,
    aplicativo,
    sem_chaveiro,
    wav_longo,
)
from tests.unit.voz.test_app import MotorDeAsrFalso

TELAS = Path(os.environ.get("JARVIS_TELAS_TAREFAS", "/tmp/jarvis-telas/tarefas"))  # noqa: S108
CONFIGURACAO = Configuracao(
    asr="asr-whisper-local", tts="tts-parametrico", s2="eco", acesso="padrao"
)


def _esperar(app: QGuiApplication, segundos: float, ate: Callable[[], bool] | None = None) -> None:
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        if ate is not None and ate():
            return
        time.sleep(0.005)


def _roteiro(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
    if "procura" in contexto.turno:
        if not any(m.papel == "ferramenta" for m in contexto.mensagens):
            return [
                "Vou procurar em segundo plano. ",
                PedidoDeTool(
                    "tarefa.iniciar",
                    {
                        "descricao": "achar o orçamento nas pastas",
                        "tool": "files.search_in_roots",
                        "parametros": {"consulta": "orcamento"},
                    },
                ),
            ]
        return ["Pode falar, eu aviso."]
    return ["Estou aqui, conversando."]


@pytest.fixture
def busca_travada(monkeypatch: pytest.MonkeyPatch) -> Iterator[threading.Event]:
    solta = threading.Event()
    original = arquivos.procurar

    def lenta(raizes: Any, consulta: str, **kw: Any) -> Any:
        while not solta.wait(0.01):
            if kw["cancelado"]():
                raise arquivos.Cancelada("o dono interrompeu a busca")
        return original(raizes, consulta, **kw)

    monkeypatch.setattr(arquivos, "procurar", lenta)
    yield solta
    solta.set()


def _montar(tmp_path: Path) -> tuple[Aplicativo, Ponte]:
    casa = tmp_path / "casa"
    (casa / "Documentos").mkdir(parents=True)
    (casa / "Documentos" / "orcamento.ods").write_bytes(b"PK")
    laco = Aplicativo(
        configuracao=CONFIGURACAO,
        raiz=tmp_path / "sessao",
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        caminho_de_entrada=wav_longo(tmp_path / "entrada.wav"),
        caminho_de_saida=tmp_path / "saida.wav",
        lar=casa,
    )
    laco._asr = MotorDeAsrFalso()
    laco._motor = MotorRoteirizado(resposta=_roteiro, atraso_entre_deltas_s=0.005)
    ponte = Ponte(
        raiz=tmp_path / "sessao",
        configuracao=CONFIGURACAO,
        caminho_da_configuracao=tmp_path / "jarvis-voz.toml",
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        aplicativo=laco,
    )
    return laco, ponte


def _card(ponte: Ponte) -> Any:
    return next(
        (
            w
            for w in ponte._espaco.widgets.values()
            if w.componente == "tarefas" and not w.demonstracao
        ),
        None,
    )


def _avisos(ponte: Ponte) -> list[dict[str, str]]:
    avisos: list[dict[str, str]] = cast(Any, ponte)._sessao.dados_dos_avisos()["avisos"]
    return avisos


def _capturar(janela: QQuickView, nome: str) -> None:
    TELAS.mkdir(parents=True, exist_ok=True)
    assert janela.grabWindow().save(str(TELAS / nome))


def _itens_da_tela(raiz: QQuickItem, nome: str) -> list[QQuickItem]:
    """Os itens QML de um `objectName` — os visuais não são filhos QObject, então se anda por
    `childItems()` (dentro de um ListView, pelos itens do conteúdo)."""
    achados: list[QQuickItem] = []
    pilha = [raiz]
    while pilha:
        atual = pilha.pop()
        if atual.objectName() == nome:
            achados.append(atual)
        pilha.extend(atual.childItems())
    return achados


def _item(card: Any) -> dict[str, str]:
    return dict(card.dados["itens"][0])


def test_a_tarefa_roda_enquanto_o_jarvis_conversa_e_o_dono_para_pelo_card(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    busca_travada: threading.Event,
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    laco, ponte = _montar(tmp_path)
    janela = abrir(ponte)
    janela.rootObject().setProperty("semPonteiro", True)
    janela.show()
    tela = cast(Any, ponte)
    tela.iniciarConversa()
    _esperar(aplicativo, 1.0, ate=lambda: laco.estado.value != "parado")

    tela.enviarTexto("procura o orçamento nas pastas")
    _esperar(aplicativo, 6.0, ate=lambda: _card(ponte) is not None)

    card = _card(ponte)
    assert card is not None, "a tarefa começou e o card não apareceu"
    item = _item(card)
    assert (item["estado"], item["titulo"]) == ("executando", "achar o orçamento nas pastas")
    assert item["id"].startswith("t-") and item["progresso"].isdigit()
    assert not card.demonstracao, "dado real: sem selo de demonstração"
    _esperar(aplicativo, 1.0, ate=lambda: len(laco.turnos) >= 1)
    _esperar(aplicativo, 0.5)
    _capturar(janela, "tarefa-rodando.png")

    # A conversa segue com a tarefa ainda rodando.
    tela.enviarTexto("e aí, tudo bem?")
    _esperar(
        aplicativo,
        6.0,
        ate=lambda: any("conversando" in linha["texto"] for linha in tela.transcricao),
    )
    falas = [linha["texto"] for linha in tela.transcricao if linha["texto"].startswith("Jarvis: ")]
    assert any("Estou aqui, conversando." in f for f in falas), falas
    assert _item(_card(ponte))["estado"] == "executando", "a tarefa não parou por causa da conversa"

    botoes = [b for b in _itens_da_tela(janela.rootObject(), "pararTarefa") if b.isVisible()]
    assert len(botoes) == 1, "o botão 'parar' da tarefa em andamento aparece"
    centro = botoes[0].mapToScene(botoes[0].boundingRect().center()).toPoint()
    # O clique de verdade, no botão, pelo mesmo caminho do mouse do dono.
    QTest.mouseClick(
        janela,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(centro.x(), centro.y()),
    )
    _esperar(aplicativo, 3.0, ate=lambda: _item(_card(ponte))["estado"] == "cancelada")
    _esperar(aplicativo, 0.5)
    _capturar(janela, "tarefa-cancelada.png")

    assert _item(_card(ponte))["estado"] == "cancelada"
    avisos = _avisos(ponte)
    assert any("cancelada" in a["resumo"] and a["tipo"] == "evento" for a in avisos), avisos
    tela.pararConversa()
    _esperar(aplicativo, 0.8)


def test_a_tarefa_que_termina_sozinha_avisa_pela_fila_e_o_card_mostra_pronta(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    busca_travada: threading.Event,
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    laco, ponte = _montar(tmp_path)
    janela = abrir(ponte)
    janela.show()
    tela = cast(Any, ponte)
    tela.iniciarConversa()
    _esperar(aplicativo, 1.0, ate=lambda: laco.estado.value != "parado")
    tela.enviarTexto("procura o orçamento nas pastas")
    _esperar(aplicativo, 6.0, ate=lambda: _card(ponte) is not None)
    _esperar(aplicativo, 1.0, ate=lambda: len(laco.turnos) >= 1)

    busca_travada.set()
    _esperar(aplicativo, 4.0, ate=lambda: _item(_card(ponte))["estado"] == "resultado")
    _esperar(aplicativo, 0.5)
    _capturar(janela, "tarefa-pronta.png")

    item = _item(_card(ponte))
    assert (item["estado"], item["progresso"]) == ("resultado", "100")
    avisos = _avisos(ponte)
    assert any(a["tipo"] == "concluida" and "terminou" in a["resumo"] for a in avisos), avisos
    tela.pararConversa()
    _esperar(aplicativo, 0.8)
