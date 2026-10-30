"""Os modos de ativação **pela janela** (ADR-0021): os slots que o QML chama, sem microfone.

Sob `CI=1` (o conftest liga): o portal do sistema não é consultado, e o atalho fica "só com a
janela em foco" — que é exatamente a frase que a tela tem de mostrar quando não há portal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

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


class PortalQueAceita:
    """No lugar do `AtalhoPortal`: o sistema "aceitou" a combinação, sem diálogo nenhum."""

    abertos: ClassVar[list[str]] = []

    def __init__(self, *, combinacao: str, ambiente: Any, ao_mudar: Any) -> None:
        self.combinacao = combinacao
        self.gatilho = combinacao

    def abrir(self) -> None:
        PortalQueAceita.abertos.append(self.combinacao)

    def fechar(self) -> None:
        return None


def test_atalho_global_salvo_volta_sozinho_ao_abrir_a_janela(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bug do dono (2026-10-16): o atalho global sumia a cada reinício — não era guardado."""
    import time

    from jarvis.gui import ponte as modulo

    if not isinstance(QGuiApplication.instance(), QGuiApplication):
        QGuiApplication([])
    monkeypatch.setattr(chaveiro, "_modulo", base.ChaveiroFalso)
    monkeypatch.setattr(modulo, "portal_disponivel", lambda **_: (True, "portal falso"))
    monkeypatch.setattr(modulo, "AtalhoPortal", PortalQueAceita)
    PortalQueAceita.abertos = []
    caminho = tmp_path / "jarvis-voz.toml"

    primeira = Ponte(raiz=tmp_path / "s1", caminho_da_configuracao=caminho)
    primeira.capturarAtalho(
        int(Qt.Key.Key_Space.value), int(Qt.KeyboardModifier.ControlModifier.value)
    )
    primeira.ativarAtalhoGlobal()
    limite = time.monotonic() + 5
    while not primeira.estado_da_escuta()["atalhoGlobal"] and time.monotonic() < limite:
        time.sleep(0.02)
    assert primeira.estado_da_escuta()["atalhoGlobal"] is True
    assert "salve a configuração" in lido(primeira, "portalFrase")
    primeira.salvarConfiguracao()
    assert ler(caminho).atalho_global is True

    segunda = Ponte(raiz=tmp_path / "s2", caminho_da_configuracao=caminho)
    limite = time.monotonic() + 5
    while not segunda.estado_da_escuta()["atalhoGlobal"] and time.monotonic() < limite:
        time.sleep(0.02)
    assert PortalQueAceita.abertos == ["Ctrl+Space", "Ctrl+Space"]
    assert "atalho global ligado pelo sistema" in lido(segunda, "portalFrase")


def test_trocar_a_combinacao_desliga_o_global_guardado(ponte: Ponte) -> None:
    ponte._configuracao = ponte._configuracao.com(atalho_global=True)
    ponte.capturarAtalho(int(Qt.Key.Key_J.value), int(Qt.KeyboardModifier.ControlModifier.value))
    assert ponte._configuracao.atalho_global is False


def test_o_tom_da_voz_aparece_ao_lado_do_estado(ponte: Ponte) -> None:
    """ADR-0058: o laço manda o tom curto do último turno; a janela mostra, e o neutro apaga."""
    assert lido(ponte, "tomDaVoz") == ""
    ponte._mudar_tom("entonação de pergunta · voz baixa")
    assert lido(ponte, "tomDaVoz") == "entonação de pergunta · voz baixa"
    ponte._mudar_tom("")
    assert lido(ponte, "tomDaVoz") == ""
