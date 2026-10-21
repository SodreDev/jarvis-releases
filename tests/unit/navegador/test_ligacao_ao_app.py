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
        if pedido["method"] == "windows.focused":  # a lista diz qual aba está à vista
            foco = {"janelaId": 1, "abaAtivaId": 5, "janelaDoJarvisId": None, "janelaDoDonoId": 1}
            return {"id": pedido["id"], "ok": True, "result": foco}
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
    assert abas.dados["abas"][0]["estado"] == "à vista"
    assert [p["method"] for p in navegador.recebidos] == ["tabs.list", "windows.focused"]


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
        metodo = pedido["method"]
        if metodo == "tabs.current":
            return {"id": pedido["id"], "ok": True, "result": {"aba": aba}}
        if metodo == "tabs.list":  # há aba que já tem o site? (2026-10-21) — não há
            return {"id": pedido["id"], "ok": True, "result": {"abas": [aba]}}
        if metodo == "tabs.show":
            return {"id": pedido["id"], "ok": True, "result": {"visivel": True, "janela": "dono"}}
        if metodo.startswith("controle."):
            return {"id": pedido["id"], "ok": True, "result": {}}
        assert metodo == "tabs.navigate", pedido
        url = pedido["params"]["url"]
        nova = aba | {"url": url}
        conferido = {"comecou": True, "carregou": True, "pagina": {"url": url, "titulo": "D"}}
        return {
            "id": pedido["id"],
            "ok": True,
            "result": {"aba": nova, "janela": "dono", "visivel": False} | conferido,
        }

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
        for controle in app._navegadores_de_outra_familia.values():
            controle.controle.fechar()
    finally:
        navegador.fechar()

    assert aberto.status == "ok", aberto.motivo
    assert aberto.dados["reutilizou_aba"] is True
    # Conferido e à vista (auditoria de 2026-10-21): quem abre um site quer ver o site.
    metodos = [p["method"] for p in navegador.recebidos if not p["method"].startswith("controle.")]
    assert metodos == ["tabs.current", "tabs.list", "tabs.navigate", "tabs.show"]
    navegou = next(p for p in navegador.recebidos if p["method"] == "tabs.navigate")
    assert {k: v for k, v in navegou["params"].items() if k != "controle"} == {
        "tabId": 5,
        "url": "https://exemplo.org/depois",
    }


# --- o PARAR e o sites.open pela extensão (ADR-0027 regra 4; dono, 2026-10-21) --------------------
class _GestorFalso:
    def __init__(self, *tarefas: Any) -> None:
        self.tarefas = {t.id: t for t in tarefas}
        self.canceladas: list[str] = []

    def cancelar(self, tarefa_id: str) -> Any:
        self.canceladas.append(tarefa_id)
        return self.tarefas[tarefa_id]


def _tarefa(identificador: str, objetivo: Any) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        id=identificador,
        estado=SimpleNamespace(final=False),
        contaminacao=SimpleNamespace(objetivo=objetivo),
    )


def test_o_navegador_do_app_nasce_com_o_parar_e_o_aviso_da_janela_ligados(tmp_path: Path) -> None:
    app = _app(tmp_path, navegador_controlado=True, navegador_principal="brave")
    avisos: list[bool] = []
    app.ao_mudar_navegador = avisos.append

    corpos = app._corpos_do_navegador()

    assert corpos is not None and corpos.cliente.navegador == "chromium"
    assert corpos.ao_parar == app._parar_pelo_navegador
    assert corpos.ao_mudar is not None
    corpos.ao_mudar(True)
    assert avisos == [True]


def test_o_parar_cancela_as_tarefas_daquele_pedido_e_interrompe_o_turno_no_ar(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from jarvis.politica.objetivo import Objetivo
    from jarvis.voz.estado import Estado

    app = _app(tmp_path, navegador_controlado=True)
    linhas: list[str] = []
    app.escrever_na_tela = linhas.append
    parado, outro = Objetivo.do_pedido("abre o youtube"), Objetivo.do_pedido("lê o g1")
    gestor = _GestorFalso(_tarefa("t-1", parado), _tarefa("t-2", outro))
    app.ferramentas = SimpleNamespace(tarefas=gestor, objetivo=parado)  # type: ignore[assignment]
    app.estado = Estado.PENSANDO
    antes = app.epoch

    app._parar_pelo_navegador([parado])

    assert gestor.canceladas == ["t-1"], "só a tarefa do pedido parado"
    assert app.epoch == antes + 1, "o turno no ar é interrompido (epoch)"
    assert any("parar no navegador" in linha for linha in linhas)

    app.estado = Estado.OUVINDO
    app._parar_pelo_navegador([outro])
    assert app.epoch == antes + 1, "sem turno no ar, só a tarefa"
    assert gestor.canceladas == ["t-1", "t-2"]


def test_sites_open_vai_pela_extensao_reaproveita_a_aba_e_termina_a_vista(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Host real com a "extensão" falsa por pipes: o g1 já estava aberto numa aba de trás."""
    curto = tmp_path_factory.mktemp("s")
    abas = [
        {"id": 5, "janelaId": 1, "ativa": True, "url": "https://exemplo.org/", "titulo": "Ex"},
        {"id": 6, "janelaId": 1, "ativa": False, "url": "https://g1.globo.com/", "titulo": "g1"},
    ]

    def extensao(pedido: dict[str, Any]) -> dict[str, Any]:
        metodo, p = pedido["method"], pedido["params"]
        if metodo == "tabs.current":
            achada = next((a for a in abas if a["id"] == p.get("tabId", 5)), abas[0])
            resultado: dict[str, Any] = {"aba": achada}
        elif metodo == "tabs.list":
            resultado = {"abas": abas}
        elif metodo == "tabs.show":
            for aba in abas:
                aba["ativa"] = aba["id"] == p["tabId"]
            resultado = {"aba": abas[1], "janela": "dono", "visivel": True}
        else:  # controle.soltar / controle.manter da vigia
            resultado = {}
        return {"id": pedido["id"], "ok": True, "result": resultado}

    navegador = Navegador(curto, extensao)
    navegador.abrir()
    try:
        raiz = curto / "sessao"
        raiz.mkdir()
        app = Aplicativo(
            configuracao=BASE.com(
                navegador_controlado=True,
                navegadores=("brave=/usr/bin/brave-browser",),
                navegador_principal="brave",
            ),
            raiz=raiz,
            ambiente={"JARVIS_AUDIO_BACKEND": "arquivo", "XDG_RUNTIME_DIR": str(curto)},
            lar=curto / "casa",
        )
        ferramentas = app._montar_ferramentas()
        app.ferramentas = ferramentas
        ferramentas.novo_turno("abre o g1")

        aberto = ferramentas.executar(
            "sites.open", {"url": "https://g1.globo.com/"}, cancelado=lambda: False
        )
        assert ferramentas.navegador is not None
        ferramentas.navegador.controle.fechar()
    finally:
        navegador.fechar()

    assert aberto.status == "ok", aberto.motivo
    assert aberto.dados["reutilizou_aba"] is True
    metodos = [p["method"] for p in navegador.recebidos]
    assert "tabs.show" in metodos and "tabs.navigate" not in metodos, "ativou a aba que já tinha"
    mostrar = next(p for p in navegador.recebidos if p["method"] == "tabs.show")
    assert mostrar["params"]["tabId"] == 6 and len(mostrar["params"]["controle"]) == 16
