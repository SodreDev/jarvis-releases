"""Os modos de ativação **pela janela** (ADR-0021): os slots que o QML chama, sem microfone.

Sob `CI=1` (o conftest liga): o portal do sistema não é consultado, e o atalho fica "só com a
janela em foco" — que é exatamente a frase que a tela tem de mostrar quando não há portal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui` (`uv sync --group gui`)")

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from jarvis.gui import chaveiro
from jarvis.gui.ponte import Ponte
from jarvis.voz.config import Configuracao, escrever, ler
from jarvis.voz.escuta import ModoDeEscuta
from tests.unit.gui import test_janela as base


def lido(ponte: Ponte, nome: str) -> Any:
    """Uma propriedade do QML lida do Python (o stub a tipa como `Property`)."""
    return getattr(ponte, nome)


@pytest.fixture
def ponte(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Ponte:
    if not isinstance(QGuiApplication.instance(), QGuiApplication):
        QGuiApplication([])
    monkeypatch.setattr(chaveiro, "_modulo", base.ChaveiroFalso)
    caminho = tmp_path / "jarvis-voz.toml"
    escrever(Configuracao(escuta="palavra", palavra="sexta"), caminho)
    return Ponte(raiz=tmp_path / "sessao", caminho_da_configuracao=caminho)


def test_a_janela_comeca_no_modo_do_arquivo(ponte: Ponte) -> None:
    escuta = ponte.estado_da_escuta()
    assert escuta["modo"] == "palavra"
    assert escuta["palavra"] == "sexta"
    assert "“sexta”" in escuta["frase"]


def test_trocar_o_modo_vale_no_estado_vivo_e_vai_para_o_arquivo(ponte: Ponte) -> None:
    ponte.definirEscuta("vad")
    assert ponte.estado_da_escuta()["modo"] == "vad"
    ponte.salvarConfiguracao()
    assert ler(Path(lido(ponte, "configuracao")["caminho"])).escuta == "vad"


def test_palavra_e_limiar_pela_janela(ponte: Ponte) -> None:
    ponte.definirPalavra("Jarvis", "0,9")
    escuta = ponte.estado_da_escuta()
    assert (escuta["palavra"], escuta["limiar"]) == ("jarvis", 0.9)

    ponte.definirPalavra("ô jarvis", "")
    assert ponte.estado_da_escuta()["palavra"] == "jarvis", "palavra inválida trocou a boa"
    assert "palavra recusada" in lido(ponte, "aviso")


def test_capturar_a_combinacao_apertada(ponte: Ponte) -> None:
    modificadores = int(Qt.KeyboardModifier.ControlModifier.value) | int(
        Qt.KeyboardModifier.ShiftModifier.value
    )
    ponte.capturarAtalho(int(Qt.Key.Key_J.value), modificadores)
    assert ponte.estado_da_escuta()["atalho"] == "Ctrl+Shift+J"
    assert lido(ponte, "atalhoTecla") == int(Qt.Key.Key_J.value)
    assert lido(ponte, "atalhoModificadores") == modificadores
    assert ponte.estado_da_escuta()["atalhoGlobal"] is False

    ponte.capturarAtalho(int(Qt.Key.Key_K.value), 0)
    assert ponte.estado_da_escuta()["atalho"] == "Ctrl+Shift+J", "letra sozinha passou"
    assert "atalho recusado" in lido(ponte, "aviso")

    ponte.limparAtalho()
    assert ponte.estado_da_escuta()["atalho"] == ""
    assert lido(ponte, "atalhoTecla") == 0


def test_sem_portal_a_tela_diz_que_vale_so_em_foco(ponte: Ponte) -> None:
    assert lido(ponte, "portalDisponivel") is False
    ponte.definirEscuta("ptt")
    assert "com a janela em foco" in ponte.estado_da_escuta()["frase"]


def test_o_indicador_diz_o_modo_ao_lado_do_microfone(ponte: Ponte) -> None:
    microfone = lido(ponte, "microfone")
    assert microfone["aberta"] is False
    assert microfone["modoFrase"] == "palavra de ativação"
    assert "“sexta”" in microfone["escuta"]


def test_o_modelo_pedindo_escuta_continua_vira_pendencia_na_janela(ponte: Ponte) -> None:
    ponte._espaco.propor({"tipo": "definirModoDeEscuta", "escuta": "vad", "motivo": "ditado longo"})
    pendentes = ponte.pendencias_abertas()
    assert [p["titulo"] for p in pendentes] == ["escuta: escuta contínua"]
    assert ponte.estado_da_escuta()["modo"] == "palavra"

    ponte.responderPendencia(pendentes[0]["id"], True)
    assert ponte.estado_da_escuta()["modo"] == "vad"
    assert ponte._escuta.modo is ModoDeEscuta.CONTINUA
