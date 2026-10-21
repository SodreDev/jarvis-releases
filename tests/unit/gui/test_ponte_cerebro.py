"""Fatia 5 do roteiro da F2: a janela ligada ao cérebro em stream e à fila de avisos de verdade.

Três coisas, todas pela janela real (QML offscreen) e pelo laço real, com motor e TTS de teste:

- o card `notificacoes` mostra a fila do laço, pelo `updateWidget`, sem o selo de demonstração —
  e os módulos que continuam de demonstração continuam com ele;
- a caixa de texto chega ao cérebro, a resposta aparece **crescendo** na conversa e o estado do
  núcleo (pensando → falando → repouso) vem do laço;
- o "parar" da janela cancela a geração: o turno acaba sem esperar o motor.

As capturas saem em `/tmp/jarvis-telas/fatia5/` para o dono olhar.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui`")

from PySide6.QtCore import QEventLoop
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView

from jarvis.agentd.fila_de_avisos import notificacao
from jarvis.gui.ponte import Ponte
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.voz.app import Aplicativo
from tests.unit.gui.test_janela import (  # noqa: F401 — fixtures
    CONFIGURACAO,
    abrir,
    aplicativo,
    sem_chaveiro,
    wav_longo,
)
from tests.unit.voz.test_app import MotorDeAsrFalso

TELAS = Path(os.environ.get("JARVIS_TELAS_FATIA5", "/tmp/jarvis-telas/fatia5"))  # noqa: S108
RESPOSTA = (
    "Amanhã cedo vai fazer frio, perto de doze graus, e à tarde o sol abre. "
    "Se for sair, leve um casaco leve e deixe o guarda-chuva em casa."
)


def _esperar(app: QGuiApplication, segundos: float, ate: Callable[[], bool] | None = None) -> None:
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        if ate is not None and ate():
            return
        time.sleep(0.005)


def _laco(tmp_path: Path, motor: MotorRoteirizado) -> Aplicativo:
    laco = Aplicativo(
        configuracao=CONFIGURACAO,
        raiz=tmp_path / "sessao",
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        caminho_de_entrada=wav_longo(tmp_path / "entrada.wav"),
        caminho_de_saida=tmp_path / "saida.wav",
    )
    laco._asr = MotorDeAsrFalso()
    laco._motor = motor
    return laco


def _ponte(tmp_path: Path, laco: Aplicativo | None = None) -> Ponte:
    return Ponte(
        raiz=tmp_path / "sessao",
        configuracao=CONFIGURACAO,
        caminho_da_configuracao=tmp_path / "jarvis-voz.toml",
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        aplicativo=laco,
    )


def _card(ponte: Ponte) -> Any:
    espaco = ponte._espaco
    return next(w for w in espaco.widgets.values() if w.componente == "notificacoes")


def _capturar(janela: QQuickView, nome: str) -> Path:
    TELAS.mkdir(parents=True, exist_ok=True)
    destino = TELAS / nome
    assert janela.grabWindow().save(str(destino)), destino
    return destino


# --- (b) o card de avisos com dados reais ---------------------------------------------------
def test_o_card_mostra_a_fila_real_sem_selo_e_o_resto_continua_demonstracao(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    laco = _laco(tmp_path, MotorRoteirizado(resposta="Certo."))
    ponte = _ponte(tmp_path, laco)
    janela = abrir(ponte)
    janela.rootObject().setProperty("semPonteiro", True)
    janela.show()
    _esperar(aplicativo, 0.6)

    card = _card(ponte)
    assert card.dados == {"avisos": []}
    assert not card.demonstracao, "a fila é real: o selo de demonstração tem de sair"
    demonstracoes = [w for w in ponte._espaco.widgets.values() if w.demonstracao]
    assert demonstracoes, "os módulos que ainda são roteiro continuam com o selo"
    _capturar(janela, "assistente-avisos-vazio.png")

    tela = cast(Any, ponte)
    tela.iniciarConversa()
    _esperar(aplicativo, 1.0, ate=lambda: laco.estado.value != "parado")
    laco.receber_aviso(
        notificacao(
            laco.session_id,
            "n-1",
            tipo="precisa_decisao",
            origem="tarefa · empacotar",
            resumo="O .rpm está pronto; publicar exige a sua ordem",
        )
    )
    laco.receber_aviso(
        notificacao(
            laco.session_id,
            "n-2",
            tipo="concluida",
            origem="tarefa · baixar voz",
            resumo="pt_BR-faber-medium baixada e conferida",
        )
    )
    _esperar(aplicativo, 1.0, ate=lambda: len(_card(ponte).dados["avisos"]) == 2)
    _esperar(
        aplicativo,
        5.0,
        ate=lambda: any(a["entrega"] == "falado" for a in _card(ponte).dados["avisos"]),
    )
    tela.pararConversa()
    _esperar(aplicativo, 0.8)

    avisos = _card(ponte).dados["avisos"]
    assert [a["resumo"] for a in avisos] == [
        "pt_BR-faber-medium baixada e conferida",
        "O .rpm está pronto; publicar exige a sua ordem",
    ]
    # Com o piso livre a fila vai à voz (ADR-0025, ligada no laço pela ADR-0038): um aviso
    # espontâneo por vez, o pedido de decisão primeiro — o outro espera o teto do D22 na fila.
    entregas = {a["resumo"]: a["entrega"] for a in avisos}
    assert entregas["pt_BR-faber-medium baixada e conferida"] == "na_fila"
    assert entregas["O .rpm está pronto; publicar exige a sua ordem"] == "falado"
    _capturar(janela, "assistente-avisos-reais.png")


# --- (c) a caixa de texto no cérebro, em stream ------------------------------------------
def test_a_resposta_aparece_crescendo_e_o_estado_vem_do_laco(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    motor = MotorRoteirizado(resposta=RESPOSTA, atraso_entre_deltas_s=0.04)
    laco = _laco(tmp_path, motor)
    ponte = _ponte(tmp_path, laco)
    janela = abrir(ponte)
    janela.rootObject().setProperty("semPonteiro", True)
    janela.show()
    tela = cast(Any, ponte)
    estados: list[str] = []
    parciais: list[str] = []

    def observar() -> None:
        ultima = tela.transcricao[-1] if tela.transcricao else {}
        if ultima.get("parcial"):
            parciais.append(ultima["texto"])

    ponte.conversaMudou.connect(observar)
    tela.iniciarConversa()
    _esperar(aplicativo, 1.0, ate=lambda: laco.estado.value != "parado")
    # O estado é lido **na porta do laço**, na hora em que muda: o sinal chega à janela depois,
    # e sob carga a janela pode ler já o estado seguinte (pensando → falando num tique só).
    porta = laco.ao_mudar_estado
    assert porta is not None

    def registrar(estado: Any) -> None:
        estados.append(str(estado))
        porta(estado)

    laco.ao_mudar_estado = registrar
    tela.enviarTexto("como vai estar o tempo amanhã?")
    _esperar(aplicativo, 4.0, ate=lambda: len(parciais) >= 4)
    _capturar(janela, "conversa-em-stream.png")
    _esperar(aplicativo, 8.0, ate=lambda: bool(laco.turnos))
    tela.pararConversa()
    _esperar(aplicativo, 0.8)

    assert motor.pedidos, "a caixa de texto não chegou ao cérebro"
    assert len(set(parciais)) >= 3, "a resposta não apareceu em pedaços"
    assert all(b.startswith(a) for a, b in pairwise(parciais))
    linhas = [linha["texto"] for linha in tela.transcricao if linha["quem"] == "jarvis"]
    respostas = [linha for linha in linhas if linha.startswith("Jarvis: ")]
    assert respostas == [f"Jarvis: {' '.join(RESPOSTA.split())}"], "a resposta saiu duplicada"
    perguntas = [linha["texto"] for linha in tela.transcricao if "tempo amanhã" in linha["texto"]]
    assert perguntas == ["como vai estar o tempo amanhã?"], "a pergunta saiu duplicada"
    assert "pensando" in estados and "falando" in estados
    assert estados.index("pensando") < estados.index("falando")
    _capturar(janela, "conversa-respondida.png")


def test_parar_na_janela_cancela_a_geracao_sem_esperar_o_motor(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    motor = MotorRoteirizado(resposta=RESPOSTA, primeiro_atraso_s=6.0)
    laco = _laco(tmp_path, motor)
    ponte = _ponte(tmp_path, laco)
    abrir(ponte)
    tela = cast(Any, ponte)
    tela.iniciarConversa()
    _esperar(aplicativo, 1.0, ate=lambda: laco.estado.value != "parado")
    tela.enviarTexto("conta uma história longa")
    _esperar(aplicativo, 2.0, ate=lambda: tela.estado == "pensando")
    assert tela.estado == "pensando"

    comeco = time.monotonic()
    tela.interromper()
    _esperar(aplicativo, 2.0, ate=lambda: bool(laco.turnos))
    levou = time.monotonic() - comeco
    tela.pararConversa()
    _esperar(aplicativo, 0.8)

    assert laco.turnos and laco.turnos[-1].cancelado
    assert laco.turnos[-1].respondeu == ""
    assert levou < 1.0, f"o cancelamento esperou o motor ({levou:.1f} s)"
    assert not any(linha["texto"].startswith("Jarvis: ") for linha in tela.transcricao)


def test_o_motor_padrao_e_o_eco_e_a_tela_diz_onde_roda(tmp_path: Path) -> None:
    """D18: o `claude -p` é escolha do dono, nunca padrão silencioso."""
    linhas: list[str] = []
    laco = Aplicativo(
        configuracao=CONFIGURACAO, raiz=tmp_path / "s", escrever_na_tela=linhas.append
    )
    laco.rodar_texto([])
    assert any(linha.startswith("respondendo com: eco") and "[local]" in linha for linha in linhas)
