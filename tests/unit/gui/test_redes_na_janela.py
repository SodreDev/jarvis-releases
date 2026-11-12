"""A aba «redes sociais» e o salvamento na hora (ADR-0060), **pela janela** (QML offscreen).

Pedido do dono (2026-11-12): toda troca de ajuste persiste no mesmo clique, sem botão de salvar —
inclusive o navegador preferido e cada rede. Nada aqui abre navegador nem conta: a aba só grava
`redes.toml` e mostra o estado que o monitor (fatia B) informar.
"""

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

from jarvis.gui.ponte import Ponte
from jarvis.social.config import ler as ler_redes
from jarvis.voz.config import ler
from tests.unit.gui.test_acesso_na_janela import (  # noqa: F401 — fixtures e auxiliares
    _aba,
    _capturar,
    _clicar,
    _esperar,
    _item,
    _procurar,
    maquina,
)
from tests.unit.gui.test_escolha_na_janela import GROQ_V3
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
) -> tuple[QQuickView, Any, Ponte]:
    ponte = Ponte(
        raiz=tmp_path / "sessao",
        caminho_da_configuracao=maquina["config"],
        ambiente={"CI": "1"},
        pastas_de_apps=(str(maquina["apps"]),),
        lar=maquina["lar"],
    )
    janela = abrir(ponte)
    janela.show()
    _esperar(aplicativo, 0.5)
    vista = cast(Any, ponte)
    vista.abrirPainel("configuracao")
    _esperar(aplicativo, 0.6)
    return janela, vista, ponte


def _redes(maquina: dict[str, Path]) -> Path:
    return maquina["config"].parent / "redes.toml"


def test_a_aba_abre_com_tudo_desligado_e_sem_arquivo(
    tela: tuple[QQuickView, Any, Ponte], aplicativo: QGuiApplication, maquina: dict[str, Path]
) -> None:
    janela, vista, _ = tela
    assert not _item(janela, "vistaRedes").isVisible()
    _aba(janela, aplicativo, "Redes")
    assert _item(janela, "vistaRedes").isVisible()
    assert not _item(janela, "vistaAcesso").isVisible()
    _capturar(janela, "redes-1-desligadas.png")
    linhas = vista.redes.redes
    assert [r["id"] for r in linhas] == ["whatsapp", "instagram", "facebook", "tiktok", "discord"]
    assert all(not r["monitorar"] and r["estado"] == "desligada" for r in linhas)
    assert not _redes(maquina).exists(), "abrir a aba não grava nada"


def test_ligar_o_monitor_com_o_mouse_grava_na_hora_com_0600(
    tela: tuple[QQuickView, Any, Ponte], aplicativo: QGuiApplication, maquina: dict[str, Path]
) -> None:
    janela, vista, _ = tela
    _aba(janela, aplicativo, "Redes")
    _clicar(janela, aplicativo, _item(janela, "monitorar-whatsapp"))
    assert vista.redes.frase == "WhatsApp: monitorando — salvo"
    assert ler_redes(_redes(maquina)).monitoradas() == ("whatsapp",)
    if os.name != "nt":
        assert stat.S_IMODE(_redes(maquina).stat().st_mode) == 0o600
    # o botão de avisar só aparece com o monitor ligado, e também grava na hora
    _esperar(aplicativo, 0.2, ate=lambda: _item(janela, "notificar-whatsapp").isVisible())
    _clicar(janela, aplicativo, _item(janela, "notificar-whatsapp"))
    assert not ler_redes(_redes(maquina)).ajuste("whatsapp").notificar
    _capturar(janela, "redes-2-whatsapp-ligado.png")
    _clicar(janela, aplicativo, _item(janela, "monitorar-whatsapp"))
    assert ler_redes(_redes(maquina)).monitoradas() == ()


def test_navegador_preferido_grava_na_hora_e_volta_ao_reabrir(
    tela: tuple[QQuickView, Any, Ponte],
    aplicativo: QGuiApplication,
    maquina: dict[str, Path],
    tmp_path: Path,
) -> None:
    janela, vista, _ = tela
    _aba(janela, aplicativo, "Redes")
    nomes = [n["familia"] for n in vista.redes.navegadores]
    assert nomes == ["", "brave", "firefox"], "o principal primeiro, depois os detectados"
    _clicar(janela, aplicativo, _item(janela, "navegadorPreferido-firefox"))
    assert ler_redes(_redes(maquina)).navegador_preferido == "firefox"
    outra = cast(
        Any,
        Ponte(
            raiz=tmp_path / "sessao2",
            caminho_da_configuracao=maquina["config"],
            ambiente={"CI": "1"},
            pastas_de_apps=(str(maquina["apps"]),),
            lar=maquina["lar"],
        ),
    )
    assert outra.redes.navegadorPreferido == "firefox"
    vista.redes.definirNavegadorPreferido("")
    assert ler_redes(_redes(maquina)).navegador_preferido == ""


def test_arquivo_de_redes_quebrado_nao_e_regravado_ate_o_dono_mexer(
    abrir: Callable[[Ponte], QQuickView], maquina: dict[str, Path], tmp_path: Path
) -> None:
    _redes(maquina).write_text("[redes.orkut]\nmonitorar = true\n", "utf-8")
    ponte = cast(
        Any,
        Ponte(
            raiz=tmp_path / "sessao",
            caminho_da_configuracao=maquina["config"],
            ambiente={"CI": "1"},
            pastas_de_apps=(str(maquina["apps"]),),
        ),
    )
    assert ponte.redes.frase.startswith("não deu: redes.toml recusado")
    assert "orkut" in _redes(maquina).read_text("utf-8"), "abrir não apaga o arquivo do dono"
    assert ponte.redes.definirMonitorar("discord", True)
    assert ler_redes(_redes(maquina)).monitoradas() == ("discord",)


def test_rede_desconhecida_e_recusada_sem_gravar(
    tela: tuple[QQuickView, Any, Ponte], maquina: dict[str, Path]
) -> None:
    _, vista, _ = tela
    assert not vista.redes.definirMonitorar("orkut", True)
    assert vista.redes.frase.startswith("não deu")
    assert not _redes(maquina).exists()


def test_a_folha_de_voz_nao_tem_mais_botao_de_salvar(
    tela: tuple[QQuickView, Any, Ponte],
) -> None:
    janela, _, _ = tela
    assert _procurar(janela.rootObject(), "salvamentoAutomatico") is not None

    def textos(item: Any) -> list[str]:
        achados = [str(item.property("texto") or "")]
        for filho in item.childItems():
            achados += textos(filho)
        return achados

    assert "salvar configuração" not in textos(janela.rootObject())


def test_cada_troca_da_folha_de_voz_grava_na_hora(
    tela: tuple[QQuickView, Any, Ponte], maquina: dict[str, Path]
) -> None:
    _, vista, _ = tela
    vista.definirEscuta("palavra")
    assert ler(maquina["config"]).escuta == "palavra"
    assert vista.aviso == "escuta: palavra — salvo"
    vista.definirPalavra("sexta", "0,8")
    assert (ler(maquina["config"]).palavra, ler(maquina["config"]).limiar_palavra) == (
        "sexta",
        0.8,
    )
    vista.definirCampo("saida", "pipewire")
    assert ler(maquina["config"]).saida == "pipewire"
    vista.capturarAtalho(0x20, 0x04000000)  # Ctrl+Space
    assert ler(maquina["config"]).atalho == "Ctrl+Space"
    vista.limparAtalho()
    assert ler(maquina["config"]).atalho == ""
    vista.ligarNuvem(GROQ_V3, True)
    assert GROQ_V3 in ler(maquina["config"]).nuvem_ligada
    vista.ligarNuvem(GROQ_V3, False)
    assert GROQ_V3 not in ler(maquina["config"]).nuvem_ligada


def test_gravar_um_campo_nao_apaga_o_que_o_dono_escreveu_a_mao_noutro(
    tela: tuple[QQuickView, Any, Ponte], maquina: dict[str, Path]
) -> None:
    from jarvis.voz.config import escrever, validar

    _, vista, _ = tela
    escrever(validar(ler(maquina["config"]).com(saida="alsa")), maquina["config"])
    vista.definirEscuta("vad")
    no_disco = ler(maquina["config"])
    assert (no_disco.escuta, no_disco.saida) == ("vad", "alsa")


def test_campo_invalido_e_recusado_sem_ir_ao_arquivo(
    tela: tuple[QQuickView, Any, Ponte], maquina: dict[str, Path]
) -> None:
    _, vista, _ = tela
    antes = maquina["config"].read_text("utf-8") if maquina["config"].exists() else ""
    vista.definirCampo("escuta", "telepatia")
    assert "recusado" in vista.aviso
    depois = maquina["config"].read_text("utf-8") if maquina["config"].exists() else ""
    assert antes == depois


# --- fatia B: o monitor ligado à janela, com uma ponte de navegador FALSA ---------------------
def test_monitor_na_janela_abre_a_aba_de_fundo_e_mostra_a_notificacao_no_cartao(
    abrir: Callable[[Ponte], QQuickView],
    aplicativo: QGuiApplication,
    maquina: dict[str, Path],
    tmp_path: Path,
) -> None:
    from tests.unit.social.test_monitor import PonteFalsa
    from tests.unit.social.test_monitor import _esperar as esperar_fio

    falsa = PonteFalsa()
    ponte = Ponte(
        raiz=tmp_path / "sessao",
        caminho_da_configuracao=maquina["config"],
        ambiente={"CI": "1"},
        pastas_de_apps=(str(maquina["apps"]),),
        lar=maquina["lar"],
        ponte_das_redes=falsa,
    )
    vista = cast(Any, ponte)
    try:
        janela = abrir(ponte)
        janela.show()
        vista.abrirPainel("configuracao")
        _esperar(aplicativo, 0.5)
        _aba(janela, aplicativo, "Redes")
        assert falsa.pedidos == [], "nada ligado: o monitor não pede nada"
        _clicar(janela, aplicativo, _item(janela, "monitorar-whatsapp"))
        assert esperar_fio(lambda: any(p[0] == "social.abrir" for p in falsa.pedidos))
        assert falsa.pedidos[0][2] == {"rede": "whatsapp"}
        falsa.fila.append(
            {
                "evento": "social",
                "rede": "whatsapp",
                "logado": True,
                "naoLidas": 2,
                "conversas": [{"nome": "Ana", "naoLidas": 2}],
                "formato": "conhecido",
                "alerta": "",
            }
        )

        def chegou() -> bool:
            linha = vista.redes.redes[0]
            return bool(linha["notificacoes"])

        _esperar(aplicativo, 3.0, ate=chegou)
        linha = vista.redes.redes[0]
        assert linha["estado"] == "conectada" and linha["naoLidas"] == 2
        assert linha["notificacoes"][0]["texto"] == "WhatsApp: 2 mensagens novas — Ana (2)"
        _capturar(janela, "redes-3-whatsapp-notificacao.png")
        assert {p[0] for p in falsa.pedidos} <= {"social.abrir", "social.estado"}
    finally:
        ponte.parar_o_monitor_das_redes()


def test_notificacao_da_rede_vai_a_fila_da_conversa_pelo_laco(
    maquina: dict[str, Path], tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from tests.unit.social.test_monitor import PonteFalsa

    recebidos: list[tuple[str, str]] = []
    ponte = Ponte(
        raiz=tmp_path / "sessao",
        caminho_da_configuracao=maquina["config"],
        ambiente={"CI": "1"},
        pastas_de_apps=(str(maquina["apps"]),),
        ponte_das_redes=PonteFalsa(),
    )
    try:
        cast(Any, ponte)._sessao = SimpleNamespace(
            viva=True,
            aplicativo=SimpleNamespace(aviso_de_rede=lambda o, r: recebidos.append((o, r))),
        )
        ponte._avisar_da_rede("discord", "Discord: 1 mensagem nova — edu (1)")
        assert recebidos == [("Discord", "Discord: 1 mensagem nova — edu (1)")]
    finally:
        ponte.parar_o_monitor_das_redes()
