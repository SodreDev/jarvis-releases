"""Abrir app e site pelo que o dono pré-autorizou, de ponta a ponta na janela (2026-10-17).

Bug do dono: o Jarvis mostrava a faixa CONFIRMAR para abrir um app que ele já tinha marcado na
Configuração → Aplicativos. A política da fatia 6 diz o contrário: app marcado abre sem
perguntar, app não marcado é negado com sugestão, site fora da lista confirma.

Janela real (QML offscreen), laço real, política e executor reais montados **pela configuração**
(`Aplicativo._montar_ferramentas`), e um motor roteirizado no lugar do modelo (sem rede). O app é
marcado pela aba Aplicativos, com a conversa já aberta. Só duas peças são falsas: a pasta dos
`.desktop` (uma máquina de mentira) e o lançador/abridor — **nada abre de verdade**.
"""

# ruff: noqa: F811 — as fixtures vêm de `test_janela` e são parâmetros aqui
from __future__ import annotations

import json
import os
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui`")

from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView

from jarvis.executor.ferramentas import ExecutorDeFerramentas
from jarvis.executor.lancador import App, RegistroDeApps
from jarvis.gui.ponte import Ponte
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.voz import app as modulo_app
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao, escrever
from tests.unit.gui.test_janela import (  # noqa: F401 — fixtures
    abrir,
    aplicativo,
    sem_chaveiro,
    wav_longo,
)
from tests.unit.gui.test_janela_ferramentas import _esperar, _pendente, _resultado
from tests.unit.voz.test_app import MotorDeAsrFalso

CONFIGURACAO = Configuracao(
    asr="asr-whisper-local", tts="tts-parametrico", s2="eco", acesso="padrao"
)


class Maquina:
    """Uma máquina de mentira: três apps instalados, e o que foi aberto de mentira."""

    def __init__(self, tmp_path: Path) -> None:
        self.pasta = tmp_path / "applications"
        self.pasta.mkdir()
        for id_, nome in (
            ("discord", "Discord"),
            ("org.kde.kcalc", "Calculadora"),
            ("brave-browser", "Brave Web Browser"),
        ):
            (self.pasta / f"{id_}.desktop").write_text(
                f"[Desktop Entry]\nType=Application\nName={nome}\nExec={id_.split('.')[-1]}\n",
                "utf-8",
            )
        self.apps_abertos: list[str] = []
        self.sites_abertos: list[str] = []

    def lancar(self, app: App) -> int:
        self.apps_abertos.append(app.id)
        return 4242

    def abrir_site(self, url: str) -> None:
        self.sites_abertos.append(url)


def _proposta(tool_id: str, args: dict[str, Any], *, ok: str) -> Callable[[Contexto], Any]:
    def roteiro(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
        resultado = _resultado(contexto)
        if resultado is None:
            return ["Já vejo. ", PedidoDeTool(tool_id, args)]
        return [ok] if resultado["status"] == "ok" else [f"Não deu: {resultado['status']}."]

    return roteiro


def _montar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    maquina: Maquina,
    roteiro: Callable[[Contexto], Any],
    **configuracao: Any,
) -> tuple[Aplicativo, Ponte]:
    # A política e o registro saem de `_montar_ferramentas`, como no uso real; só a pasta dos
    # `.desktop` e o lançador/abridor são trocados.
    monkeypatch.setattr(
        modulo_app,
        "RegistroDeApps",
        SimpleNamespace(
            montar=lambda autorizados, extras=(): RegistroDeApps.montar(
                autorizados, pastas=[str(maquina.pasta)], extras=extras
            )
        ),
    )
    monkeypatch.setattr(
        modulo_app,
        "ExecutorDeFerramentas",
        partial(ExecutorDeFerramentas, lancar_app=maquina.lancar, abrir_site=maquina.abrir_site),
    )
    config = CONFIGURACAO.com(**configuracao)
    arquivo = tmp_path / "jarvis-voz.toml"
    escrever(config, arquivo)
    laco = Aplicativo(
        configuracao=config,
        raiz=tmp_path / "sessao",
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        caminho_de_entrada=wav_longo(tmp_path / "entrada.wav"),
        caminho_de_saida=tmp_path / "saida.wav",
        lar=tmp_path / "casa",
    )
    laco._asr = MotorDeAsrFalso()
    laco._motor = MotorRoteirizado(resposta=roteiro, atraso_entre_deltas_s=0.01)
    ponte = Ponte(
        raiz=tmp_path / "sessao",
        configuracao=config,
        caminho_da_configuracao=arquivo,
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        aplicativo=laco,
        pastas_de_apps=(str(maquina.pasta),),
    )
    return laco, ponte


def _pedir(
    app: QGuiApplication, ponte: Ponte, laco: Aplicativo, frase: str, *, marcar: str = ""
) -> Any:
    """Abre a conversa, marca o app **pela aba** (já com a conversa viva) e fala."""
    tela = cast(Any, ponte)
    tela.iniciarConversa()
    _esperar(app, 1.0, ate=lambda: laco.estado.value != "parado")
    if marcar:
        tela.acesso.marcarApp(marcar, True)
    tela.enviarTexto(frase)
    return tela


def _respostas(tela: Any) -> list[str]:
    return [linha["texto"] for linha in tela.transcricao if linha["texto"].startswith("Jarvis: ")]


def test_app_marcado_na_aba_abre_sem_faixa_de_confirmacao(
    aplicativo: QGuiApplication,
    abrir: Callable[[Ponte], QQuickView],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sem_chaveiro: None,
) -> None:
    maquina = Maquina(tmp_path)
    roteiro = _proposta("apps.launch", {"nome": "Discord"}, ok="Abri o Discord.")
    laco, ponte = _montar(tmp_path, monkeypatch, maquina, roteiro)
    abrir(ponte)
    tela = _pedir(aplicativo, ponte, laco, "abre o discord", marcar="discord")
    viu_a_faixa = False

    def terminou() -> bool:
        nonlocal viu_a_faixa
        viu_a_faixa = viu_a_faixa or _pendente(tela) is not None
        return bool(laco.turnos)

    _esperar(aplicativo, 6.0, ate=terminou)
    _esperar(aplicativo, 0.3)
    tela.pararConversa()
    _esperar(aplicativo, 0.8)

    assert not viu_a_faixa, "app que o dono marcou na Configuração pediu confirmação"
    assert maquina.apps_abertos == ["discord"]
    assert _respostas(tela) == ["Jarvis: Já vejo. Abri o Discord."]


def test_app_marcado_chamado_por_nome_parcial_tambem_abre_sem_faixa(
    aplicativo: QGuiApplication,
    abrir: Callable[[Ponte], QQuickView],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sem_chaveiro: None,
) -> None:
    """ "Brave" para o app "Brave Web Browser": o executor sempre resolveu, a política negava."""
    maquina = Maquina(tmp_path)
    roteiro = _proposta("apps.launch", {"nome": "brave"}, ok="Abri o Brave.")
    laco, ponte = _montar(tmp_path, monkeypatch, maquina, roteiro)
    abrir(ponte)
    tela = _pedir(aplicativo, ponte, laco, "abre o brave", marcar="brave-browser")
    viu_a_faixa = False

    def terminou() -> bool:
        nonlocal viu_a_faixa
        viu_a_faixa = viu_a_faixa or _pendente(tela) is not None
        return bool(laco.turnos)

    _esperar(aplicativo, 6.0, ate=terminou)
    _esperar(aplicativo, 0.3)
    tela.pararConversa()
    _esperar(aplicativo, 0.8)

    assert not viu_a_faixa
    assert maquina.apps_abertos == ["brave-browser"]


def test_o_modelo_ve_quais_apps_estao_autorizados(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maquina = Maquina(tmp_path)
    laco, _ponte = _montar(
        tmp_path, monkeypatch, maquina, lambda _c: ["oi"], apps_autorizados=("discord",)
    )
    laco.raiz.mkdir(parents=True, exist_ok=True)
    ferramentas = laco._montar_ferramentas()
    descricao = next(
        t["descricao"] for t in ferramentas.catalogo_para_o_modelo() if t["id"] == "apps.launch"
    )
    assert str(descricao).endswith("Autorizados agora: Discord.")


def test_app_nao_marcado_e_negado_com_sugestao_e_nao_abre(
    aplicativo: QGuiApplication,
    abrir: Callable[[Ponte], QQuickView],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sem_chaveiro: None,
) -> None:
    maquina = Maquina(tmp_path)
    vistos: list[dict[str, Any]] = []

    def roteiro(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
        resultado = _resultado(contexto)
        if resultado is None:
            return [PedidoDeTool("apps.launch", {"nome": "Calculadora"})]
        vistos.append(resultado)
        return ["Não abri."]

    laco, ponte = _montar(tmp_path, monkeypatch, maquina, roteiro)
    abrir(ponte)
    tela = _pedir(aplicativo, ponte, laco, "abre a calculadora", marcar="discord")
    viu_a_faixa = False

    def terminou() -> bool:
        nonlocal viu_a_faixa
        viu_a_faixa = viu_a_faixa or _pendente(tela) is not None
        return bool(laco.turnos)

    _esperar(aplicativo, 6.0, ate=terminou)
    tela.pararConversa()
    _esperar(aplicativo, 0.8)

    assert not viu_a_faixa, "negar não é perguntar"
    assert maquina.apps_abertos == []
    assert vistos and vistos[0]["status"] == "negado"
    assert "Parecidos: Discord" in vistos[0]["motivo"], json.dumps(vistos[0], ensure_ascii=False)


def test_site_fora_da_lista_confirma_e_o_dono_decide(
    aplicativo: QGuiApplication,
    abrir: Callable[[Ponte], QQuickView],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sem_chaveiro: None,
) -> None:
    maquina = Maquina(tmp_path)
    roteiro = _proposta("sites.open", {"url": "https://exemplo.com.br/a"}, ok="Abri o site.")
    laco, ponte = _montar(
        tmp_path, monkeypatch, maquina, roteiro, sites_sem_confirmar=("wikipedia.org",)
    )
    abrir(ponte)
    tela = _pedir(aplicativo, ponte, laco, "abre exemplo.com.br")
    _esperar(aplicativo, 5.0, ate=lambda: _pendente(tela) is not None)

    pedido = _pendente(tela)
    assert pedido is not None, "site fora da lista tem de pedir confirmação"
    assert maquina.sites_abertos == [], "nada abre antes do sim"
    tela.responderPendencia(pedido["id"], True)
    _esperar(aplicativo, 5.0, ate=lambda: bool(laco.turnos))
    tela.pararConversa()
    _esperar(aplicativo, 0.8)

    assert maquina.sites_abertos == ["https://exemplo.com.br/a"]
