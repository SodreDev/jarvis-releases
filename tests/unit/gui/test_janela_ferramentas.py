"""Fatia 6: ferramentas pela janela — o modelo propõe, a política manda confirmar, o dono decide.

Desde 2026-10-18 só o tier **perigoso** pergunta (rascunho e abrir app/site rodam sem perguntar):
a faixa de confirmação é exercida aqui com `memoria.apagar`, que é perigoso e tem corpo.

Janela real (QML offscreen), laço real, executor real sobre uma casa de mentira em `tmp_path`, e
um motor roteirizado no lugar do modelo (sem rede). As capturas saem em `/tmp/jarvis-telas/fatia6/`.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui`")

from PySide6.QtCore import QEventLoop
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView

from jarvis.gui.ponte import Ponte
from jarvis.memoryd.cofre import CofreFernet, nova_chave
from jarvis.memoryd.conversa import ConversaPersistente, abrir_conversa
from jarvis.memoryd.indice import IndiceEmMemoria
from jarvis.politica.memoria import Estado
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

TELAS = Path(os.environ.get("JARVIS_TELAS_FATIA6", "/tmp/jarvis-telas/fatia6"))  # noqa: S108
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


def _resultado(contexto: Contexto) -> dict[str, Any] | None:
    textos = [m.texto for m in contexto.mensagens if m.papel == "ferramenta"]
    return json.loads(textos[-1].removesuffix(" …[truncado]")) if textos else None


def _apagar_a(alvo: str) -> Callable[[Contexto], Sequence[str | PedidoDeTool]]:
    def roteiro(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
        resultado = _resultado(contexto)
        if resultado is None:
            return [
                "Vou apagar. ",
                PedidoDeTool("memoria.apagar", {"alvo_id": alvo, "escopo": "memoria"}),
            ]
        return ["Apaguei."] if resultado["status"] == "ok" else ["Não apaguei."]

    return roteiro


def _listar(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
    resultado = _resultado(contexto)
    if resultado is None:
        return ["Deixa eu ver. ", PedidoDeTool("files.list_dir", {"path": "~/Documentos"})]
    nomes = [e["nome"] for e in resultado["dados"]["entradas"]]
    return [f"Na sua pasta Documentos tem {' e '.join(nomes)}."]


def _memoria_do_dono(tmp_path: Path) -> tuple[ConversaPersistente, str]:
    """Um histórico aberto com uma memória ativa, que o teste manda apagar."""
    conversa = abrir_conversa(
        tmp_path / "sessao",
        cofre=lambda: CofreFernet(nova_chave()),
        indice=IndiceEmMemoria(),
    )
    assert conversa.livro is not None
    origem = conversa.livro.gravar_turno(
        session_id=conversa.conversa_id,
        papel="dono",
        texto="o café acabou, comprar café",
        trust="user_voice",
    )
    feita = conversa.livro.lembrar(
        "comprar café", estado=Estado.ATIVA, fonte=origem, extrator="teste"
    )
    return conversa, str(feita["assertion_id"])


def _montar(
    tmp_path: Path,
    roteiro: Callable[[Contexto], Sequence[str | PedidoDeTool]],
    conversa: ConversaPersistente | None = None,
) -> tuple[Aplicativo, Ponte]:
    casa = tmp_path / "casa"
    (casa / "Documentos").mkdir(parents=True)
    (casa / "Documentos" / "notas.txt").write_text("comprar café\n", "utf-8")
    (casa / "Documentos" / "orcamento.ods").write_bytes(b"PK")
    laco = Aplicativo(
        configuracao=CONFIGURACAO,
        raiz=tmp_path / "sessao",
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        caminho_de_entrada=wav_longo(tmp_path / "entrada.wav"),
        caminho_de_saida=tmp_path / "saida.wav",
        lar=casa,
        conversa=conversa,
    )
    laco._asr = MotorDeAsrFalso()
    laco._motor = MotorRoteirizado(resposta=roteiro, atraso_entre_deltas_s=0.01)
    ponte = Ponte(
        raiz=tmp_path / "sessao",
        configuracao=CONFIGURACAO,
        caminho_da_configuracao=tmp_path / "jarvis-voz.toml",
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        aplicativo=laco,
    )
    return laco, ponte


def _pendente(tela: Any) -> dict[str, str] | None:
    return next((p for p in tela.pendentes if p["id"].startswith("ferramenta:")), None)


def _memoria_viva(conversa: ConversaPersistente, alvo: str) -> bool:
    assert conversa.livro is not None
    return bool(
        conversa.livro.con.execute("SELECT 1 FROM assertion WHERE id = ?", (alvo,)).fetchone()
    )


def _capturar(janela: QQuickView, nome: str) -> None:
    TELAS.mkdir(parents=True, exist_ok=True)
    assert janela.grabWindow().save(str(TELAS / nome))


def test_o_dono_aprova_na_janela_e_so_entao_a_memoria_e_apagada(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    conversa, alvo = _memoria_do_dono(tmp_path)
    laco, ponte = _montar(tmp_path, _apagar_a(alvo), conversa)
    janela = abrir(ponte)
    janela.rootObject().setProperty("semPonteiro", True)
    janela.show()
    tela = cast(Any, ponte)
    tela.iniciarConversa()
    _esperar(aplicativo, 1.0, ate=lambda: laco.estado.value != "parado")
    tela.enviarTexto("apaga aquela anotação do café")
    _esperar(aplicativo, 5.0, ate=lambda: _pendente(tela) is not None)

    pedido = _pendente(tela)
    assert pedido is not None, "a política manda confirmar e a janela não perguntou"
    assert "apagar de vez" in pedido["motivo"] and "sem resposta, eu não faço" in pedido["motivo"]
    assert _memoria_viva(conversa, alvo), "nada é apagado antes do sim"
    _capturar(janela, "confirmar-apagar.png")

    tela.responderPendencia(pedido["id"], True)
    _esperar(aplicativo, 5.0, ate=lambda: bool(laco.turnos))
    _esperar(aplicativo, 0.5)
    _capturar(janela, "memoria-apagada.png")
    tela.pararConversa()
    _esperar(aplicativo, 0.8)

    assert not _memoria_viva(conversa, alvo), "com o sim do dono, apagou"
    assert _pendente(tela) is None
    respostas = [
        linha["texto"] for linha in tela.transcricao if linha["texto"].startswith("Jarvis: ")
    ]
    assert respostas == ["Jarvis: Vou apagar. Apaguei."]


def test_sem_resposta_no_prazo_e_nao_e_a_faixa_some(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    conversa, alvo = _memoria_do_dono(tmp_path)
    laco, ponte = _montar(tmp_path, _apagar_a(alvo), conversa)
    laco.raiz.mkdir(parents=True, exist_ok=True)
    laco.ferramentas = laco._montar_ferramentas()
    laco.ferramentas.prazo_de_confirmacao_s = 0.6
    abrir(ponte)
    tela = cast(Any, ponte)
    tela.iniciarConversa()
    _esperar(aplicativo, 1.0, ate=lambda: laco.estado.value != "parado")
    tela.enviarTexto("apaga aquela anotação do café")
    _esperar(aplicativo, 5.0, ate=lambda: _pendente(tela) is not None)
    assert _pendente(tela) is not None
    _esperar(aplicativo, 5.0, ate=lambda: bool(laco.turnos))
    _esperar(aplicativo, 0.3)
    tela.pararConversa()
    _esperar(aplicativo, 0.8)

    assert _memoria_viva(conversa, alvo), "sem resposta no prazo, não apaga"
    assert _pendente(tela) is None, "pedido vencido continuou na tela"
    assert any(linha["texto"] == "Jarvis: Vou apagar. Não apaguei." for linha in tela.transcricao)


def test_interromper_com_a_confirmacao_aberta_e_nao(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    conversa, alvo = _memoria_do_dono(tmp_path)
    laco, ponte = _montar(tmp_path, _apagar_a(alvo), conversa)
    abrir(ponte)
    tela = cast(Any, ponte)
    tela.iniciarConversa()
    _esperar(aplicativo, 1.0, ate=lambda: laco.estado.value != "parado")
    tela.enviarTexto("apaga aquela anotação do café")
    _esperar(aplicativo, 5.0, ate=lambda: _pendente(tela) is not None)
    comeco = time.monotonic()
    tela.interromper()
    _esperar(aplicativo, 3.0, ate=lambda: bool(laco.turnos))
    levou = time.monotonic() - comeco
    tela.pararConversa()
    _esperar(aplicativo, 0.8)

    assert levou < 1.5, f"a confirmação segurou o turno {levou:.1f} s depois do interromper"
    assert _memoria_viva(conversa, alvo)
    assert _pendente(tela) is None


def test_listar_a_pasta_e_responder_em_voz(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    laco, ponte = _montar(tmp_path, _listar)
    janela = abrir(ponte)
    janela.rootObject().setProperty("semPonteiro", True)
    janela.show()
    tela = cast(Any, ponte)
    tela.iniciarConversa()
    _esperar(aplicativo, 1.0, ate=lambda: laco.estado.value != "parado")
    tela.enviarTexto("o que tem na minha pasta Documentos?")
    _esperar(aplicativo, 6.0, ate=lambda: bool(laco.turnos))
    _esperar(aplicativo, 0.5)
    _capturar(janela, "pasta-listada.png")
    tela.pararConversa()
    _esperar(aplicativo, 0.8)

    respostas = [
        linha["texto"] for linha in tela.transcricao if linha["texto"].startswith("Jarvis: ")
    ]
    assert respostas == [
        "Jarvis: Deixa eu ver. Na sua pasta Documentos tem notas.txt e orcamento.ods."
    ]
    assert _pendente(tela) is None, "leitura não pede confirmação"
