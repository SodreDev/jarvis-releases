"""A aba «chamadas» (ADR-0074, decisão do dono 2026-11-17): o TOTP configurável pelo app.

Pela janela (QML offscreen): gerar o segredo mostra a URI e a chave UMA vez; «já cadastrei» (ou
sair da aba) esconde e não volta; conferir o código gasta o código (anti-reuso); os limites
gravam `chamada.toml` (0600) na hora. A guarda do segredo é em memória — nenhum chaveiro real."""

# ruff: noqa: F811 — as fixtures vêm de `test_janela` e são parâmetros aqui
from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui`")

from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView

from jarvis.chamada.config import ler as ler_chamada
from jarvis.chamada.totp import GuardaEmMemoria, totp
from jarvis.gui.ponte import Ponte
from tests.unit.gui.test_acesso_na_janela import (  # noqa: F401 — fixtures e auxiliares
    _aba,
    _clicar,
    _esperar,
    _item,
    maquina,
)
from tests.unit.gui.test_janela import (  # noqa: F401 — fixtures
    abrir,
    aplicativo,
    sem_chaveiro,
)


@pytest.fixture
def tela(
    abrir: Callable[[Ponte], QQuickView],
    aplicativo: QGuiApplication,
    maquina: dict[str, Path],
    tmp_path: Path,
    sem_chaveiro: None,
) -> tuple[QQuickView, Any, GuardaEmMemoria]:
    guarda = GuardaEmMemoria()
    ponte = Ponte(
        raiz=tmp_path / "sessao",
        caminho_da_configuracao=maquina["config"],
        ambiente={"CI": "1"},
        pastas_de_apps=(str(maquina["apps"]),),
        lar=maquina["lar"],
        guarda_do_totp=guarda,
    )
    janela = abrir(ponte)
    janela.show()
    _esperar(aplicativo, 0.5)
    vista = cast(Any, ponte)
    vista.abrirPainel("configuracao")
    _esperar(aplicativo, 0.6)
    return janela, vista, guarda


def test_gerar_mostra_o_segredo_uma_vez_e_esconde_para_sempre(
    tela: tuple[QQuickView, Any, GuardaEmMemoria], aplicativo: QGuiApplication
) -> None:
    janela, vista, guarda = tela
    _aba(janela, aplicativo, "Chamadas")
    assert _item(janela, "vistaChamada").isVisible()
    assert not vista.chamada.configurado
    assert not _item(janela, "segredoUmaVez").isVisible()

    _clicar(janela, aplicativo, _item(janela, "gerarSegredo"))
    segredo = guarda.ler()
    assert segredo and vista.chamada.configurado
    assert segredo in vista.chamada.uri and vista.chamada.uri.startswith("otpauth://totp/")
    assert vista.chamada.chave.replace(" ", "") == segredo
    assert segredo not in vista.chamada.frase, "o segredo não vai à frase de estado"
    _esperar(aplicativo, 0.3, ate=lambda: _item(janela, "segredoUmaVez").isVisible())
    assert _item(janela, "segredoUmaVez").isVisible()

    _clicar(janela, aplicativo, _item(janela, "jaCadastrei"))
    assert (vista.chamada.uri, vista.chamada.chave) == ("", "")
    assert not _item(janela, "segredoUmaVez").isVisible()


def test_sair_da_aba_esconde_o_segredo(
    tela: tuple[QQuickView, Any, GuardaEmMemoria], aplicativo: QGuiApplication
) -> None:
    janela, vista, _ = tela
    _aba(janela, aplicativo, "Chamadas")
    _clicar(janela, aplicativo, _item(janela, "gerarSegredo"))
    assert vista.chamada.uri
    _aba(janela, aplicativo, "Redes")
    assert vista.chamada.uri == ""


def test_conferir_codigo_aceita_uma_vez(
    tela: tuple[QQuickView, Any, GuardaEmMemoria], aplicativo: QGuiApplication
) -> None:
    import time

    _, vista, guarda = tela
    vista.chamada.gerarSegredo()
    segredo = guarda.ler()
    assert segredo
    codigo = totp(segredo, time.time())
    vista.chamada.conferirCodigo(codigo)
    assert vista.chamada.frase.startswith("código aceito")
    vista.chamada.conferirCodigo(codigo)
    assert "já foi usado" in vista.chamada.frase


def test_limites_gravam_na_hora_com_0600(
    tela: tuple[QQuickView, Any, GuardaEmMemoria], maquina: dict[str, Path]
) -> None:
    _, vista, _ = tela
    caminho = maquina["config"].parent / "chamada.toml"
    vista.chamada.definir("turnos", "12")
    vista.chamada.definir("fone", "sim")
    vista.chamada.definir("pode_dizer", "que ele retorna à tarde")
    vista.chamada.definir("contato_do_dono_whatsapp", " Você ")
    vista.chamada.definir("acao_expira_min", "15")
    c = ler_chamada(caminho)
    assert (c.turnos, c.fone, c.pode_dizer) == (12, "sim", "que ele retorna à tarde")
    assert (c.contato_do_dono_whatsapp, c.acao_expira_min) == ("Você", 15)
    assert vista.chamada.ajustes["canal_do_dono_ligado"] is True
    vista.chamada.definir("fone", "talvez")
    assert vista.chamada.frase.startswith("não deu") and ler_chamada(caminho).fone == "sim"
    if os.name != "nt":
        assert stat.S_IMODE(caminho.stat().st_mode) == 0o600
    vista.chamada.definir("turnos", "0")
    assert vista.chamada.frase.startswith("não deu")
    assert ler_chamada(caminho).turnos == 12, "valor fora da faixa não grava"
    # A palavra de coação ficou fora da aba (decisão do dono, 2026-11-17): só o gancho no arquivo.
    vista.chamada.definir("palavra_de_coacao", "girassol")
    assert vista.chamada.frase.startswith("não deu")
    assert ler_chamada(caminho).palavra_de_coacao == ""
    assert "coacao_ligada" not in vista.chamada.ajustes


def test_sem_chaveiro_diz_e_nao_grava_noutro_lugar(
    abrir: Callable[[Ponte], QQuickView],
    aplicativo: QGuiApplication,
    maquina: dict[str, Path],
    tmp_path: Path,
    sem_chaveiro: None,
) -> None:
    ponte = cast(
        Any,
        Ponte(
            raiz=tmp_path / "sessao",
            caminho_da_configuracao=maquina["config"],
            ambiente={"CI": "1"},
            pastas_de_apps=(str(maquina["apps"]),),
            lar=maquina["lar"],
        ),
    )
    ponte.chamada.gerarSegredo()
    assert ponte.chamada.frase.startswith("não deu")
    assert ponte.chamada.uri == "" and not ponte.chamada.configurado
    assert not list(maquina["config"].parent.glob("*totp*")), "nada vai ao disco"


def test_o_qr_aparece_com_a_uri_e_some_junto(
    tela: tuple[QQuickView, Any, GuardaEmMemoria], aplicativo: QGuiApplication
) -> None:
    import base64

    janela, vista, guarda = tela
    _aba(janela, aplicativo, "Chamadas")
    _clicar(janela, aplicativo, _item(janela, "gerarSegredo"))
    qr = vista.chamada.qr
    assert qr.startswith("data:image/png;base64,")
    assert base64.b64decode(qr.split(",", 1)[1])[:8] == b"\x89PNG\r\n\x1a\n"
    segredo = guarda.ler()
    assert segredo and segredo not in qr, "o segredo não aparece cru: está no desenho"
    imagem = _item(janela, "qrDoSegredo")
    _esperar(aplicativo, 1.0, ate=lambda: float(imagem.property("implicitWidth")) > 0)
    assert float(imagem.property("implicitWidth")) > 0, "o Qt decodificou o PNG"
    assert imagem.isVisible()
    _clicar(janela, aplicativo, _item(janela, "jaCadastrei"))
    assert vista.chamada.qr == ""
