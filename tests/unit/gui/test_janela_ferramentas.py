"""Fatia 6: ferramentas pela janela — o modelo propõe, a política manda confirmar, o dono decide.

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


def _anotar(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
    resultado = _resultado(contexto)
    if resultado is None:
        return [
            "Vou anotar. ",
            PedidoDeTool("files.write_draft", {"nome": "compras", "texto": "comprar café"}),
        ]
    return ["Anotei na pasta de rascunhos."] if resultado["status"] == "ok" else ["Não anotei."]


def _listar(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
    resultado = _resultado(contexto)
    if resultado is None:
        return ["Deixa eu ver. ", PedidoDeTool("files.list_dir", {"path": "~/Documentos"})]
    nomes = [e["nome"] for e in resultado["dados"]["entradas"]]
    return [f"Na sua pasta Documentos tem {' e '.join(nomes)}."]


def _montar(
    tmp_path: Path, roteiro: Callable[[Contexto], Sequence[str | PedidoDeTool]]
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


def _rascunhos(laco: Aplicativo) -> list[str]:
    pasta = laco.raiz / "area" / "rascunhos"
    return sorted(p.name for p in pasta.glob("*.md"))


def _capturar(janela: QQuickView, nome: str) -> None:
    TELAS.mkdir(parents=True, exist_ok=True)
    assert janela.grabWindow().save(str(TELAS / nome))


def test_o_dono_aprova_na_janela_e_o_rascunho_e_gravado(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    laco, ponte = _montar(tmp_path, _anotar)
    janela = abrir(ponte)
    janela.rootObject().setProperty("semPonteiro", True)
    janela.show()
    tela = cast(Any, ponte)
    tela.iniciarConversa()
    _esperar(aplicativo, 1.0, ate=lambda: laco.estado.value != "parado")
    tela.enviarTexto("anota aí: comprar café")
    _esperar(aplicativo, 5.0, ate=lambda: _pendente(tela) is not None)

    pedido = _pendente(tela)
    assert pedido is not None, "a política manda confirmar e a janela não perguntou"
    assert "«compras»" in pedido["motivo"] and "sem resposta, eu não faço" in pedido["motivo"]
    assert _rascunhos(laco) == [], "nada é gravado antes do sim"
    _capturar(janela, "confirmar-rascunho.png")

    tela.responderPendencia(pedido["id"], True)
    _esperar(aplicativo, 5.0, ate=lambda: bool(laco.turnos))
    _esperar(aplicativo, 0.5)
    _capturar(janela, "rascunho-gravado.png")
    tela.pararConversa()
    _esperar(aplicativo, 0.8)

    assert _rascunhos(laco) == ["compras.md"]
    assert (laco.raiz / "area" / "rascunhos" / "compras.md").read_text("utf-8") == "comprar café"
    assert _pendente(tela) is None
    respostas = [
        linha["texto"] for linha in tela.transcricao if linha["texto"].startswith("Jarvis: ")
    ]
    assert respostas == ["Jarvis: Vou anotar. Anotei na pasta de rascunhos."]


def test_sem_resposta_no_prazo_e_nao_e_a_faixa_some(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    laco, ponte = _montar(tmp_path, _anotar)
    laco.raiz.mkdir(parents=True, exist_ok=True)
    laco.ferramentas = laco._montar_ferramentas()
    laco.ferramentas.prazo_de_confirmacao_s = 0.6
    abrir(ponte)
    tela = cast(Any, ponte)
    tela.iniciarConversa()
    _esperar(aplicativo, 1.0, ate=lambda: laco.estado.value != "parado")
    tela.enviarTexto("anota aí: comprar café")
    _esperar(aplicativo, 5.0, ate=lambda: _pendente(tela) is not None)
    assert _pendente(tela) is not None
    _esperar(aplicativo, 5.0, ate=lambda: bool(laco.turnos))
    _esperar(aplicativo, 0.3)
    tela.pararConversa()
    _esperar(aplicativo, 0.8)

    assert _rascunhos(laco) == []
    assert _pendente(tela) is None, "pedido vencido continuou na tela"
    assert any(linha["texto"] == "Jarvis: Vou anotar. Não anotei." for linha in tela.transcricao)


def test_interromper_com_a_confirmacao_aberta_e_nao(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    laco, ponte = _montar(tmp_path, _anotar)
    abrir(ponte)
    tela = cast(Any, ponte)
    tela.iniciarConversa()
    _esperar(aplicativo, 1.0, ate=lambda: laco.estado.value != "parado")
    tela.enviarTexto("anota aí: comprar café")
    _esperar(aplicativo, 5.0, ate=lambda: _pendente(tela) is not None)
    comeco = time.monotonic()
    tela.interromper()
    _esperar(aplicativo, 3.0, ate=lambda: bool(laco.turnos))
    levou = time.monotonic() - comeco
    tela.pararConversa()
    _esperar(aplicativo, 0.8)

    assert levou < 1.5, f"a confirmação segurou o turno {levou:.1f} s depois do interromper"
    assert _rascunhos(laco) == []
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
