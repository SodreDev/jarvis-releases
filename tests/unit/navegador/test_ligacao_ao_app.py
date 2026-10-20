"""A ligação das `browser.*` ao laço de voz: opt-in do dono, sem navegador nem socket reais."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from jarvis.navegador.cliente import familia_do_host
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao, escrever, ler
from tests.unit.navegador.test_host import Navegador

BASE = Configuracao(asr="asr-whisper-local", tts="tts-parametrico", s2="eco", acesso="padrao")


def _app(tmp_path: Path, **mudancas: object) -> Aplicativo:
    raiz = tmp_path / "sessao"
    raiz.mkdir(parents=True, exist_ok=True)
    return Aplicativo(
        configuracao=BASE.com(**mudancas),
        raiz=raiz,
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo", "XDG_RUNTIME_DIR": str(tmp_path / "rt")},
        lar=tmp_path / "casa",
    )


def test_o_padrao_e_desligado_e_as_tools_do_navegador_nao_aparecem(tmp_path: Path) -> None:
    assert BASE.navegador_controlado is False
    ids = {t["id"] for t in _app(tmp_path)._montar_ferramentas().catalogo_para_o_modelo()}
    assert {i for i in ids if i.startswith("browser.")} == {"browser.launch", "browser.estado"}


def test_desligado_o_modelo_ainda_ve_o_estado_e_nao_nega_a_extensao(tmp_path: Path) -> None:
    """Pedido do dono (2026-10-19): perguntado sobre a extensão, o Jarvis negava ter qualquer
    coisa. Agora a `browser.estado` existe sempre e diz que está desligado — e o que fazer."""
    ferramentas = _app(tmp_path)._montar_ferramentas()
    descricao = next(
        t["descricao"] for t in ferramentas.catalogo_para_o_modelo() if t["id"] == "browser.estado"
    )
    assert "DESLIGADO" in descricao

    resultado = ferramentas.executar("browser.estado", {}, cancelado=lambda: False)

    assert resultado.status == "ok", resultado.motivo
    assert resultado.dados["situacao"] == "desligado"
    assert "navegador_controlado" in " ".join(resultado.dados["o_que_fazer"])
    assert not ferramentas.contaminado  # estado local, não é conteúdo de terceiros


def test_ligado_pelo_dono_o_modelo_ve_as_seis_tools_e_sem_navegador_o_erro_e_claro(
    tmp_path: Path,
) -> None:
    ferramentas = _app(tmp_path, navegador_controlado=True)._montar_ferramentas()
    ids = {t["id"] for t in ferramentas.catalogo_para_o_modelo()}
    assert {"browser.tabs", "browser.read", "browser.click", "browser.type"} <= ids
    assert "browser.acao_sensivel" not in ids
    resultado = ferramentas.executar("browser.tabs", {}, cancelado=lambda: False)
    assert resultado.status == "erro"
    assert "nenhum navegador" in resultado.motivo


def test_ligado_as_tools_falam_com_o_host_do_ambiente_do_app_e_nao_com_o_do_dono(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Host real (`host.principal`) com a "extensão" falsa por pipes, na pasta do `ambiente` do
    app. Antes o transporte lia o `os.environ` real: o teste falaria com o navegador do dono."""
    curto = tmp_path_factory.mktemp("a")
    aba = {"id": 5, "janelaId": 1, "ativa": True, "url": "https://exemplo.org/", "titulo": "Ex"}

    def extensao(pedido: dict[str, Any]) -> dict[str, Any]:
        assert pedido["method"] == "tabs.list"
        return {"id": pedido["id"], "ok": True, "result": {"abas": [aba]}}

    navegador = Navegador(curto, extensao)
    navegador.abrir()
    try:
        raiz = curto / "sessao"
        raiz.mkdir()
        app = Aplicativo(
            configuracao=BASE.com(navegador_controlado=True),
            raiz=raiz,
            ambiente={"JARVIS_AUDIO_BACKEND": "arquivo", "XDG_RUNTIME_DIR": str(curto)},
            lar=curto / "casa",
        )
        ferramentas = app._montar_ferramentas()

        abas = ferramentas.executar("browser.tabs", {}, cancelado=lambda: False)
        estado = ferramentas.executar("browser.estado", {}, cancelado=lambda: False)
    finally:
        navegador.fechar()

    assert abas.status == "ok", abas.motivo
    assert abas.dados["abas"][0]["dominio"] == "exemplo.org"
    assert estado.dados["situacao"] == "conectado"
    assert [p["method"] for p in navegador.recebidos] == ["tabs.list"]


def test_o_que_o_dono_grava_volta_igual(tmp_path: Path) -> None:
    arquivo = tmp_path / "jarvis-voz.toml"
    escrever(BASE.com(navegador_controlado=True), arquivo)
    assert ler(arquivo).navegador_controlado is True
    assert "navegador_controlado = true" in arquivo.read_text("utf-8")


def test_a_familia_do_host_vem_do_navegador_principal() -> None:
    assert familia_do_host("") == ""
    assert familia_do_host("firefox") == "firefox"
    assert {familia_do_host(n) for n in ("brave", "chrome", "chromium", "vivaldi")} == {"chromium"}


def test_ligar_o_navegador_com_a_conversa_aberta_nao_some_com_memoria_tarefas_e_alarmes(
    tmp_path: Path,
) -> None:
    """A chave da janela chama `atualizar_acesso`, que trocava o executor por um sem memória,
    sem gestor de tarefas e sem agenda: as memoria.*, tarefa.* e timer.* sumiam até reiniciar, e o
    "sim" de uma pendência respondia que não havia gestor (revisão de bf9102c, 2026-10-19)."""
    app = _app(tmp_path)
    app.abrir(com_asr=False)
    antes = app.ferramentas
    assert antes is not None and antes.tarefas is not None
    livro: Any = object()
    antes.memoria = livro
    ids_antes = {t["id"] for t in antes.catalogo_para_o_modelo()}

    app.atualizar_acesso(app.configuracao.com(navegador_controlado=True))

    depois = app.ferramentas
    assert depois is not None and depois is not antes and depois.navegador is not None
    assert depois.tarefas is antes.tarefas and depois.tarefas.executor is depois
    assert depois.memoria is livro and depois.nativas is antes.nativas
    assert depois.turno is antes.turno and depois.desfazeres is antes.desfazeres
    ids_depois = {t["id"] for t in depois.catalogo_para_o_modelo()}
    assert (ids_antes - ids_depois) == set(), "nada que existia sumiu"
    assert {"browser.read", "browser.click"} <= ids_depois


def test_sites_open_troca_a_url_da_aba_atual_pela_extensao_e_nao_abre_o_navegador(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Dono, 2026-10-20: cada link abria uma aba nova. Com a extensão conectada, `sites.open` leva
    a aba atual ao endereço; o binário configurado (inofensivo aqui) nem é chamado."""
    curto = tmp_path_factory.mktemp("s")
    aba = {"id": 5, "janelaId": 1, "ativa": True, "url": "https://antes.example/", "titulo": "A"}

    def extensao(pedido: dict[str, Any]) -> dict[str, Any]:
        if pedido["method"] == "tabs.current":
            return {"id": pedido["id"], "ok": True, "result": {"aba": aba}}
        assert pedido["method"] == "tabs.navigate", pedido
        nova = aba | {"url": pedido["params"]["url"]}
        return {"id": pedido["id"], "ok": True, "result": {"aba": nova}}

    navegador = Navegador(curto, extensao)
    navegador.abrir()
    try:
        raiz = curto / "sessao"
        raiz.mkdir()
        app = Aplicativo(
            configuracao=BASE.com(
                navegador_controlado=True,
                navegadores=("teste=/usr/bin/true",),
                navegador_principal="teste",
            ),
            raiz=raiz,
            ambiente={"JARVIS_AUDIO_BACKEND": "arquivo", "XDG_RUNTIME_DIR": str(curto)},
            lar=curto / "casa",
        )
        ferramentas = app._montar_ferramentas()
        aberto = ferramentas.executar(
            "sites.open", {"url": "https://exemplo.org/depois"}, cancelado=lambda: False
        )
    finally:
        navegador.fechar()

    assert aberto.status == "ok", aberto.motivo
    assert aberto.dados["reutilizou_aba"] is True
    assert [p["method"] for p in navegador.recebidos] == ["tabs.current", "tabs.navigate"]
    assert navegador.recebidos[1]["params"] == {"tabId": 5, "url": "https://exemplo.org/depois"}
