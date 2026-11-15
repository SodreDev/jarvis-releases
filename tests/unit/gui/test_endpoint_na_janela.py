"""O endpoint HTTP de TTS **pela janela** (ADR-0068): o clique chega ao arquivo e a tela desenha.

Os cliques são os slots que o QML chama; o servidor é falso, em 127.0.0.1, porta efêmera; o arquivo
de endpoints do dono mora numa pasta temporária (`XDG_CONFIG_HOME` do ambiente da ponte).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui` (`uv sync --group gui`)")

from PySide6.QtCore import QEventLoop
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView

from jarvis.gui import principal
from jarvis.gui.ponte import Ponte
from jarvis.voz import endpoint as ep
from jarvis.voz.config import Configuracao, escrever, ler
from tests.unit.gui.test_escolha_na_janela import app_qt, chaveiro_vazio, janela_de
from tests.unit.gui.test_polimento import visiveis
from tests.unit.voz.endpoint_falso import EndpointFalso, Rota

__all__ = ["app_qt", "chaveiro_vazio", "janela_de"]  # as fixtures vêm de lá

MOTOR = "tts-endpoint"


def _ponte(tmp_path: Path, configuracao: Configuracao | None = None) -> Ponte:
    arquivo = tmp_path / "jarvis-voz.toml"
    if configuracao is not None:
        escrever(configuracao, arquivo)
    return Ponte(
        raiz=tmp_path / "sessao",
        caminho_da_configuracao=arquivo,
        ambiente={"CI": "1", "XDG_CONFIG_HOME": str(tmp_path / "xdg")},
    )


def _esperar(app_qt: QGuiApplication, condicao: Callable[[], bool], limite_s: float = 5.0) -> None:
    fim = time.monotonic() + limite_s
    while not condicao() and time.monotonic() < fim:
        app_qt.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(0.01)


def test_escolher_o_endpoint_guarda_a_voz_de_antes_como_reserva_e_nao_liga(
    tmp_path: Path, chaveiro_vazio: None
) -> None:
    tela = cast(Any, _ponte(tmp_path, Configuracao(tts="tts-parametrico")))
    endpoint = next(p for p in tela.provedoresTts if p["nome"] == "Endpoint HTTP")
    tela.escolherProvedor("tts", endpoint["chave"])
    gravada = ler(tmp_path / "jarvis-voz.toml")
    assert gravada.tts == MOTOR
    assert gravada.reserva_do_endpoint == "tts-parametrico"
    assert gravada.nuvem_ligada == (), "escolher não liga"
    dados = tela.endpointTts
    assert dados["ativo"]["nome"] == "JARVIS-BR (phonon-web)"
    assert dados["voz"] == "jarvis-br" and dados["estilo"] == "cordial"
    assert dados["estilos"] == ["cordial", "calmo", "urgente", "ironico", "seco"]


def test_campo_do_endpoint_vai_ao_arquivo_do_dono_e_o_errado_e_recusado(
    tmp_path: Path, chaveiro_vazio: None
) -> None:
    tela = cast(Any, _ponte(tmp_path))
    tela.definirNoEndpoint("base", "http://127.0.0.1:20202")
    assert tela.endpointFrase == "base: salvo"
    arquivo = tmp_path / "xdg" / "jarvis" / ep.NOME_DO_ARQUIVO
    assert ep.escolher("", arquivo=arquivo).base == "http://127.0.0.1:20202"
    tela.definirNoEndpoint("caminho", "//outro.host/x")
    assert "recusado" in tela.endpointFrase
    assert ep.escolher("", arquivo=arquivo).caminho == "/api/tts"
    assert tela.endpointTts["ativo"]["base"] == "http://127.0.0.1:20202"


def test_voz_e_estilo_escolhidos_e_a_lista_editavel(tmp_path: Path, chaveiro_vazio: None) -> None:
    tela = cast(Any, _ponte(tmp_path))
    tela.escolherNoEndpoint("estilo", "calmo")
    assert ler(tmp_path / "jarvis-voz.toml").estilo_endpoint == "calmo"
    tela.guardarNoEndpoint("estilos", "narrador")
    assert "narrador" in tela.endpointTts["estilos"]
    assert ler(tmp_path / "jarvis-voz.toml").estilo_endpoint == "narrador"
    tela.tirarDoEndpoint("estilos", "narrador")
    assert "narrador" not in tela.endpointTts["estilos"]
    assert ler(tmp_path / "jarvis-voz.toml").estilo_endpoint == ""
    tela.escolherNoEndpoint("voz", 'a"spas')
    assert "recusado" in tela.endpointFrase


def test_buscar_vozes_do_servidor_preenche_as_fichas(
    app_qt: QGuiApplication, tmp_path: Path, chaveiro_vazio: None
) -> None:
    with EndpointFalso() as servidor:
        servidor.rotas["/api/voices"] = Rota(
            corpo=json.dumps(
                [{"id": "jarvis-br", "styles": ["cordial", "sussurro"]}, {"id": "outra"}]
            ).encode(),
            tipo="application/json",
        )
        tela = cast(Any, _ponte(tmp_path))
        tela.definirNoEndpoint("base", servidor.base)
        tela.buscarVozesDoEndpoint()
        _esperar(app_qt, lambda: "voz(es)" in tela.endpointFrase)
    dados = tela.endpointTts
    assert "outra" in dados["vozes"] and "sussurro" in dados["estilos"]
    assert all(p.metodo == "GET" and not p.corpo for p in servidor.pedidos)


def test_o_painel_do_endpoint_abre_sem_erro_de_qml(
    app_qt: QGuiApplication,
    janela_de: Callable[[Ponte], QQuickView],
    tmp_path: Path,
    chaveiro_vazio: None,
) -> None:
    ponte = _ponte(tmp_path, Configuracao(tts=MOTOR, estilo_endpoint="calmo"))
    janela = janela_de(ponte)
    janela.show()
    cast(Any, ponte).abrirPainel("configuracao")
    principal._esperar(app_qt, principal.ESPERA_DA_ANIMACAO_MS)
    assert [str(erro) for erro in janela.errors()] == []
    assert len(visiveis(janela, "painelDoEndpoint")) == 1
    (campo,) = visiveis(janela, "campoDoEndpoint_base")
    assert campo.property("text") == "http://192.168.15.9:20202"
