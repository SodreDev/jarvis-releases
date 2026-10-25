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
from tests.unit.gui.test_janela_ferramentas import _esperar, _pendente
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


def _resultado_do_turno(contexto: Contexto) -> dict[str, Any] | None:
    """O resultado de ferramenta **deste** turno (depois da última fala do dono), se já veio."""
    for mensagem in reversed(contexto.mensagens):
        if mensagem.papel == "dono":
            return None
        if mensagem.papel == "ferramenta":
            return cast(dict[str, Any], json.loads(mensagem.texto.removesuffix(" …[truncado]")))
    return None


# frase do dono → o que o "modelo" propõe (a janela e a política são as de verdade)
PROPOSTAS: dict[str, tuple[str, dict[str, Any]]] = {
    "abre o discord": ("apps.launch", {"nome": "Discord"}),
    "abre o brave": ("apps.launch", {"nome": "brave"}),
    "abre a calculadora": ("apps.launch", {"nome": "Calculadora"}),
    "abre o exemplo": ("sites.open", {"url": "https://exemplo.com.br/a"}),
}


def roteiro(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
    resultado = _resultado_do_turno(contexto)
    if resultado is None:
        tool_id, args = PROPOSTAS[contexto.turno]
        return [PedidoDeTool(tool_id, args)]
    vistos.append((contexto.turno, resultado))
    return ["Feito." if resultado["status"] == "ok" else f"Não deu: {resultado['status']}."]


vistos: list[tuple[str, dict[str, Any]]] = []
"""O que cada turno viu como resultado da ferramenta (frase do dono → resultado)."""


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
            montar=lambda autorizados, extras=(), **_resto: RegistroDeApps.montar(
                autorizados, pastas=[str(maquina.pasta)], extras=extras
            )
        ),
    )
    monkeypatch.setattr(
        modulo_app,
        "ExecutorDeFerramentas",
        partial(ExecutorDeFerramentas, lancar_app=maquina.lancar, abrir_site=maquina.abrir_site),
    )
    # A máquina de mentira não tem navegador rodando: o app procura no `/proc` de verdade (um
    # navegador já aberto não ganha outra janela, 2026-10-21), e o Brave do dono não vale aqui.
    monkeypatch.setattr(modulo_app, "navegador_em_execucao", lambda _familia: None)
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


def _falar(
    app: QGuiApplication, tela: Any, laco: Aplicativo, frase: str, *, sim: bool | None = None
) -> bool:
    """Uma frase do dono, um turno inteiro. Devolve se a faixa de confirmação apareceu.

    `sim` responde à faixa quando ela aparece (o que o clique do dono faria)."""
    antes = len(laco.turnos)
    viu_a_faixa = False
    tela.enviarTexto(frase)

    def terminou() -> bool:
        nonlocal viu_a_faixa
        pendente = _pendente(tela)
        if pendente is not None:
            viu_a_faixa = True
            if sim is not None:
                tela.responderPendencia(pendente["id"], sim)
        return len(laco.turnos) > antes

    _esperar(app, 8.0, ate=terminou)
    _esperar(app, 0.3)
    return viu_a_faixa


def test_abrir_app_e_site_pelo_que_o_dono_pre_autorizou_ponta_a_ponta(
    aplicativo: QGuiApplication,
    abrir: Callable[[Ponte], QQuickView],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sem_chaveiro: None,
) -> None:
    """Uma conversa, quatro pedidos: marcado abre sem faixa (inclusive por nome parcial, e pelo
    caminho rápido, sem o motor), instalado e não marcado pergunta antes (ADR-0046) e sem o sim
    não abre, e site abre sem faixa (abrir site é livre desde 2026-10-18)."""
    vistos.clear()
    maquina = Maquina(tmp_path)
    laco, ponte = _montar(
        tmp_path, monkeypatch, maquina, roteiro, sites_sem_confirmar=("wikipedia.org",)
    )
    abrir(ponte)
    tela = cast(Any, ponte)
    tela.iniciarConversa()
    _esperar(aplicativo, 1.0, ate=lambda: laco.estado.value != "parado")
    tela.acesso.marcarApp("discord", True)  # pela aba, com a conversa já aberta
    tela.acesso.marcarApp("brave-browser", True)

    assert not _falar(aplicativo, tela, laco, "abre o discord"), "app marcado pediu confirmação"
    assert maquina.apps_abertos == ["discord"]

    assert not _falar(aplicativo, tela, laco, "abre o brave"), "nome parcial pediu confirmação"
    assert maquina.apps_abertos == ["discord", "brave-browser"]

    # Instalado e fora da lista: pergunta (ADR-0046) — e, com o "não" do dono, nada abre.
    assert _falar(aplicativo, tela, laco, "abre a calculadora", sim=False), "fora da lista pergunta"
    assert maquina.apps_abertos == ["discord", "brave-browser"], "app não marcado abriu"
    # O turno acaba na pergunta (ADR-0048), pelo caminho rápido; o "não" do clique a fecha.
    assert _pendente(tela) is None, "com o não do dono, a faixa some"

    assert maquina.sites_abertos == []
    assert not _falar(aplicativo, tela, laco, "abre o exemplo"), "abrir site é livre: sem faixa"
    assert maquina.sites_abertos == ["https://exemplo.com.br/a"]

    tela.pararConversa()
    _esperar(aplicativo, 0.8)
    # O caminho rápido (ADR-0045): «abre o discord» e «abre o brave» vão ao apps.launch pela regra
    # do código — pelo mesmo PDP —, e o motor nem é chamado; o que não cabe numa regra (o site que
    # não está na tabela, o app não marcado) continua com ele.
    assert [f for f, r in vistos if r["status"] == "ok"] == ["abre o exemplo"]
    assert "abre o discord" not in dict(vistos) and "abre o brave" not in dict(vistos)


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
