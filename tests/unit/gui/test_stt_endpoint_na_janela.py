"""O STT por endpoint HTTP **pela janela** (pedido do dono, 2026-11-14): escolher o motor não liga
nada, o campo chega ao arquivo do dono (numa pasta temporária) e o painel da aba de STT desenha sem
erro de QML. O STT local continua o padrão."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui` (`uv sync --group gui`)")

from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView

from jarvis.gui import principal
from jarvis.gui.ponte import Ponte
from jarvis.voz import stt_endpoint
from jarvis.voz.config import ASR_ENDPOINT, Configuracao, escrever, ler
from tests.unit.gui.test_escolha_na_janela import app_qt, chaveiro_vazio, janela_de
from tests.unit.gui.test_polimento import visiveis

__all__ = ["app_qt", "chaveiro_vazio", "janela_de"]  # as fixtures vêm de lá


def _ponte(tmp_path: Path, configuracao: Configuracao | None = None) -> Ponte:
    arquivo = tmp_path / "jarvis-voz.toml"
    if configuracao is not None:
        escrever(configuracao, arquivo)
    return Ponte(
        raiz=tmp_path / "sessao",
        caminho_da_configuracao=arquivo,
        ambiente={"CI": "1", "XDG_CONFIG_HOME": str(tmp_path / "xdg")},
    )


def test_escolher_o_stt_por_endpoint_nao_liga_e_o_local_segue_o_padrao(
    tmp_path: Path, chaveiro_vazio: None
) -> None:
    tela = cast(Any, _ponte(tmp_path))
    endpoint = next(p for p in tela.provedoresAsr if p["nome"].startswith("Endpoint HTTP de STT"))
    tela.escolherProvedor("asr", endpoint["chave"])

    gravada = ler(tmp_path / "jarvis-voz.toml")
    assert gravada.asr == ASR_ENDPOINT
    assert ASR_ENDPOINT not in gravada.nuvem_ligada, "escolher não liga"
    assert tela.endpointStt["ativo"]["nome"].startswith("Whisper local")


def test_campo_do_stt_vai_ao_arquivo_do_dono_e_o_errado_e_recusado(
    tmp_path: Path, chaveiro_vazio: None
) -> None:
    tela = cast(Any, _ponte(tmp_path))
    tela.definirNoEndpointStt("base", "http://10.0.0.5:9000")
    assert tela.endpointStt["frase"] == "base: salvo"
    arquivo = tmp_path / "xdg" / "jarvis" / stt_endpoint.NOME_DO_ARQUIVO
    assert stt_endpoint.escolher("", arquivo=arquivo).base == "http://10.0.0.5:9000"

    tela.definirNoEndpointStt("envio", "telepatia")
    assert "não salvei" in tela.endpointStt["frase"]
    tela.definirNoEndpointStt("campo_do_texto", "results.0.transcript")
    assert stt_endpoint.escolher("", arquivo=arquivo).campo_do_texto == "results.0.transcript"


def test_o_painel_do_stt_abre_sem_erro_de_qml(
    app_qt: QGuiApplication,
    janela_de: Callable[[Ponte], QQuickView],
    tmp_path: Path,
    chaveiro_vazio: None,
) -> None:
    ponte = _ponte(tmp_path, Configuracao(asr=ASR_ENDPOINT))
    janela = janela_de(ponte)
    janela.show()
    cast(Any, ponte).abrirPainel("configuracao")
    principal._esperar(app_qt, principal.ESPERA_DA_ANIMACAO_MS)
    assert [str(erro) for erro in janela.errors()] == []
    assert len(visiveis(janela, "painelDoEndpointStt")) == 1
    assert len(visiveis(janela, "painelDoEndpoint")) == 0, "o painel do TTS não aparece no STT"
