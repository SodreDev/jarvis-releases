"""Recuperar de falha em vez de desistir (dono, 2026-10-30; emenda da ADR-0038).

O relato: «não consegui executar o passo» e a tarefa parava — qualquer erro virava desistência.
Aqui, com uma extensão falsa que falha de propósito (prazo, erro permanente, página vazia, extensão
que não responde) e um motor roteirizado que reage à nota de replanejar, prova-se que:

- o erro chega ao motor **estruturado** (ferramenta, causa, tentativa, o que já foi tentado) e ele
  troca de caminho até concluir;
- a mesma ação idêntica que já falhou **não roda de novo** (a passageira tem uma segunda chance);
- o PDP decide **cada** tentativa que roda (a auditoria tem uma decisão por tentativa);
- a rodada do motor que cai é tentada de novo, e a tarefa não morre por ela;
- esgotado o orçamento, a tarefa para com honestidade: diz o que tentou, nunca "abri";
- o replanejamento aparece na tela, nunca na voz.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Generator, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.executor.ferramentas import ExecutorDeFerramentas
from jarvis.navegador.cliente import ClienteDoNavegador, SemResposta
from jarvis.navegador.ferramentas import CorposDoNavegador
from jarvis.navegador.protocolo import PedidoDaPonte
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo as ModoDeAcesso
from jarvis.politica.pdp import Pdp
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import Contexto, Delta, Fim, Modo, MotivoDoFim, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.s2.recuperacao import Recuperacao, Tentativa, assinatura, codigo_da_falha
from jarvis.tarefas.gestor import EstadoDaTarefa, GestorDeTarefas, Tarefa
from jarvis.voz.interface import Cancelado, Onde

URL = "https://www.exemplo.org/inicio"
OUTRA = "https://www.exemplo.org/artigo"
TITULO = "Artigo do Exemplo"
PEDIDO = "abre o artigo do exemplo.org e me diz o título"


class ExtensaoQueFalha:
    """A extensão falsa com estado e um roteiro de falhas por método: cada chamada consome o
    próximo comportamento da lista (`ok`, `vazia`, `calada` ou o código de erro da extensão)."""

    def __init__(self, falhas: Mapping[str, Sequence[str]] | None = None) -> None:
        self.abas: dict[int, str] = {7: "https://www.exemplo.org/"}  # o mesmo site: navega na aba
        self.ativa = 7
        self.metodos: list[str] = []
        self._falhas = {m: list(v) for m, v in (falhas or {}).items()}

    def _aba(self, tab_id: object = None) -> dict[str, Any]:
        identificador = tab_id if isinstance(tab_id, int) and tab_id in self.abas else self.ativa
        url = self.abas[identificador]
        titulo = TITULO if url == OUTRA else "Exemplo"
        return {"id": identificador, "janelaId": 1, "ativa": True, "url": url, "titulo": titulo}

    def _foi(self, tab_id: int) -> dict[str, Any]:
        aba = self._aba(tab_id)
        pagina = {"url": aba["url"], "titulo": aba["titulo"]}
        return {"aba": aba, "comecou": True, "carregou": True, "pagina": pagina} | {
            "janela": "dono",
            "visivel": True,
        }

    def chamar(self, pedido: PedidoDaPonte, navegador: str = "") -> dict[str, Any]:
        self.metodos.append(pedido.method)
        roteiro = self._falhas.get(pedido.method) or []
        comportamento = roteiro.pop(0) if roteiro else "ok"
        if comportamento == "calada":
            raise SemResposta(f"a extensão não respondeu a {pedido.method} em 8 s")
        ok = {"id": pedido.id, "ok": True}
        if comportamento not in ("ok", "vazia"):
            erro = {"codigo": comportamento, "mensagem": "a página não mudou"}
            return {"id": pedido.id, "ok": False, "error": erro}
        p = pedido.params
        match pedido.method:
            case "tabs.list":
                return ok | {"result": {"abas": [self._aba(i) for i in self.abas]}}
            case "tabs.current":
                return ok | {"result": {"aba": self._aba(p.get("tabId"))}}
            case "windows.focused":
                foco = {"janelaId": 1, "abaAtivaId": self.ativa, "janelaDoJarvisId": None}
                return ok | {"result": foco}
            case "tabs.navigate":
                tab_id = int(p["tabId"]) if p.get("tabId") in self.abas else self.ativa
                self.abas[tab_id] = str(p["url"])
                return ok | {"result": self._foi(tab_id)}
            case "tabs.open":
                tab_id = max(self.abas) + 1
                self.abas[tab_id] = str(p["url"])
                self.ativa = tab_id
                return ok | {"result": self._foi(tab_id)}
            case "tabs.show":
                return ok | {"result": {"visivel": True, "janela": "dono"}}
            case "page.scroll":
                return ok | {"result": {"rolou": True, "y": 800}}
            case "page.read":
                aba = self._aba(p.get("tabId"))
                texto = "" if comportamento == "vazia" else f"{aba['titulo']} — texto do artigo"
                pagina = {"url": aba["url"], "titulo": aba["titulo"], "textoVisivel": texto}
                return ok | {"result": pagina | {"links": [], "datas": []}}
        raise AssertionError(pedido.method)


@pytest.fixture
def auditoria(tmp_path: Path) -> Iterator[LogDeAuditoria]:
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as log:
        yield log


def _executor(
    tmp_path: Path, auditoria: LogDeAuditoria, extensao: ExtensaoQueFalha
) -> ExecutorDeFerramentas:
    lar = tmp_path / "casa"
    lar.mkdir(exist_ok=True)
    pdp = Pdp(
        catalogo=carregar_catalogo(),
        lar=lar,
        auditoria=auditoria,
        modo=ModoDeAcesso.PADRAO,
        pasta_do_jarvis=tmp_path / "area",
    )
    executor = ExecutorDeFerramentas(
        pdp=pdp,
        lar=lar,
        abrir_site=lambda _url: None,
        navegador=CorposDoNavegador(ClienteDoNavegador(extensao)),
    )
    executor.preparar()
    executor.tarefas = GestorDeTarefas(executor=executor, confirmar=lambda _p, _c: False)
    return executor


def _resultados(contexto: Contexto) -> list[dict[str, Any]]:
    """O que o motor viu das ferramentas: `tool_id` e `status` de cada resultado, em ordem."""
    vistos: list[dict[str, Any]] = []
    for mensagem in contexto.mensagens:
        if mensagem.papel != "ferramenta":
            continue
        try:
            vistos.append(json.loads(mensagem.texto.split(" …[truncado]")[0]))
        except json.JSONDecodeError:
            vistos.append({"tool_id": "?", "status": "?"})
    return vistos


def _rodar(
    tmp_path: Path,
    auditoria: LogDeAuditoria,
    extensao: ExtensaoQueFalha,
    roteiro: Callable[[Contexto], Sequence[Parte]],
    motor: Any = None,
) -> tuple[Tarefa, list[str], MotorRoteirizado]:
    executor = _executor(tmp_path, auditoria, extensao)
    roteirizado = MotorRoteirizado(resposta=roteiro)
    tela: list[str] = []
    cerebro = Cerebro(
        motor=motor(roteirizado) if motor is not None else roteirizado,
        ferramentas=executor,
        delegar_em_tarefa=True,
        ao_raciocinio=tela.append,
    )
    publicados: list[dict[str, Any]] = []
    try:
        resposta = cerebro.responder(PEDIDO, epoch=0, publicar=publicados.append)
        assert resposta.tarefa_id, "o pedido de navegador vira tarefa (ADR-0038)"
        assert executor.tarefas is not None
        assert executor.tarefas.esperar(resposta.tarefa_id, 15.0), "a tarefa não terminou"
        tarefa = executor.tarefas.tarefas[resposta.tarefa_id]
    finally:
        assert executor.tarefas is not None
        executor.tarefas.encerrar()
    falado = " ".join(str(p["text"]) for p in publicados if p["text"])
    assert "↻" not in falado and "REPLANEJE" not in falado, "replanejar não vai à voz"
    return tarefa, tela, roteirizado


def _decisoes(auditoria: LogDeAuditoria, tool_id: str) -> int:
    return sum(1 for r in auditoria.decisoes() if r.tool_id == tool_id)


# --- passageira: a mesma ação, uma vez mais -------------------------------------------------
def _roteiro_passageiro(contexto: Contexto) -> Sequence[Parte]:
    vistos = _resultados(contexto)
    if not vistos:
        return ["Vou abrir. ", PedidoDeTool("browser.navigate", {"url": URL})]
    ultimo = vistos[-1]
    if ultimo["tool_id"] == "browser.navigate" and len(vistos) == 1:
        return [PedidoDeTool("browser.navigate", {"url": OUTRA})]
    if ultimo["tool_id"] == "browser.navigate" and ultimo["status"] == "erro":
        assert "REPLANEJE" in contexto.sistema and "tempo_esgotado" in contexto.sistema
        return [PedidoDeTool("browser.navigate", {"url": OUTRA})]  # idêntica: passageira pode
    if ultimo["tool_id"] == "browser.navigate":
        return [PedidoDeTool("browser.read", {})]
    return [f"O título é «{TITULO}»."]


def test_falha_passageira_tenta_a_mesma_acao_mais_uma_vez_e_conclui(
    tmp_path: Path, auditoria: LogDeAuditoria
) -> None:
    extensao = ExtensaoQueFalha({"tabs.navigate": ["ok", "tempo_esgotado"]})

    tarefa, tela, _motor = _rodar(tmp_path, auditoria, extensao, _roteiro_passageiro)

    assert tarefa.estado is EstadoDaTarefa.CONCLUIDA, tarefa.motivo
    assert tarefa.resposta == f"O título é «{TITULO}»."
    assert extensao.metodos.count("tabs.navigate") == 3  # a passageira rodou de novo
    assert any("tempo_esgotado" in linha for linha in tela), tela
    # cada tentativa que rodou passou pelo PDP
    assert _decisoes(auditoria, "browser.navigate") == 3


# --- permanente: a idêntica é recusada, o motor troca de caminho -----------------------------
def _roteiro_permanente(contexto: Contexto) -> Sequence[Parte]:
    vistos = _resultados(contexto)
    if not vistos:
        return ["Vou abrir. ", PedidoDeTool("browser.navigate", {"url": URL})]
    ultimo = vistos[-1]
    if len(vistos) == 1:
        return [PedidoDeTool("browser.navigate", {"url": OUTRA})]
    if ultimo["status"] == "erro" and '"causa": "repetida"' not in contexto.sistema:
        assert '"causa": "aba_nao_mudou"' in contexto.sistema
        assert "outros_caminhos" in contexto.sistema and "sites.open" in contexto.sistema
        return [PedidoDeTool("browser.navigate", {"url": OUTRA})]  # idêntica: recusada
    if ultimo["status"] == "erro":
        return [PedidoDeTool("browser.navigate", {"url": OUTRA, "nova_aba": True})]
    if ultimo["tool_id"] == "browser.navigate":
        return [PedidoDeTool("browser.read", {})]
    return [f"Abri numa aba nova: «{TITULO}»."]


def test_erro_permanente_nao_repete_a_acao_identica_e_troca_de_caminho(
    tmp_path: Path, auditoria: LogDeAuditoria
) -> None:
    extensao = ExtensaoQueFalha({"tabs.navigate": ["ok", "aba_nao_mudou"]})

    tarefa, tela, motor = _rodar(tmp_path, auditoria, extensao, _roteiro_permanente)

    assert tarefa.estado is EstadoDaTarefa.CONCLUIDA, tarefa.motivo
    assert tarefa.resposta == f"Abri numa aba nova: «{TITULO}»."
    # a idêntica não chegou à extensão nem ao PDP: só duas navegações e a aba nova
    assert extensao.metodos.count("tabs.navigate") == 2
    assert extensao.metodos.count("tabs.open") == 1
    assert _decisoes(auditoria, "browser.navigate") == 3
    assert any('"causa": "repetida"' in c.sistema for c in motor.pedidos)
    assert any("repetida" in linha for linha in tela), tela


# --- vazio: não confirma o objetivo -----------------------------------------------------------
def _roteiro_vazio(contexto: Contexto) -> Sequence[Parte]:
    vistos = _resultados(contexto)
    if not vistos:
        return ["Vou abrir. ", PedidoDeTool("browser.navigate", {"url": OUTRA})]
    ultimo = vistos[-1]
    if ultimo["tool_id"] == "browser.navigate":
        return [PedidoDeTool("browser.read", {})]
    if ultimo["tool_id"] == "browser.read" and '"causa": "resultado_vazio"' in contexto.sistema:
        return [PedidoDeTool("browser.scroll", {"pixels": 800})]
    if ultimo["tool_id"] == "browser.scroll":
        return [PedidoDeTool("browser.read", {})]
    return [f"O título é «{TITULO}»."]


def test_pagina_vazia_e_falha_e_o_motor_rola_e_le_de_novo(
    tmp_path: Path, auditoria: LogDeAuditoria
) -> None:
    extensao = ExtensaoQueFalha({"page.read": ["vazia"]})

    tarefa, tela, _motor = _rodar(tmp_path, auditoria, extensao, _roteiro_vazio)

    assert tarefa.estado is EstadoDaTarefa.CONCLUIDA, tarefa.motivo
    assert extensao.metodos.count("page.read") == 2 and "page.scroll" in extensao.metodos
    assert any("resultado_vazio" in linha for linha in tela), tela


# --- prazo em todas: esgota e para com honestidade -------------------------------------------
def _roteiro_teimoso(contexto: Contexto) -> Sequence[Parte]:
    vistos = _resultados(contexto)
    if not vistos:
        return ["Vou abrir. ", PedidoDeTool("browser.navigate", {"url": OUTRA})]
    falhas = sum(1 for v in vistos if v["status"] == "erro")
    if falhas < 2 and '"causa": "repetida"' not in contexto.sistema:
        return [PedidoDeTool("browser.read", {})]  # a passageira, de novo
    if '"causa": "repetida"' in contexto.sistema and falhas < 3:
        return [PedidoDeTool("browser.scroll", {"pixels": 600})]
    return [PedidoDeTool("browser.read", {})]


def test_quando_tudo_falha_a_tarefa_para_e_diz_o_que_tentou_sem_fingir(
    tmp_path: Path, auditoria: LogDeAuditoria
) -> None:
    extensao = ExtensaoQueFalha({"page.read": ["calada"] * 6, "page.scroll": ["calada"] * 6})

    tarefa, tela, _motor = _rodar(tmp_path, auditoria, extensao, _roteiro_teimoso)

    assert tarefa.estado is EstadoDaTarefa.FALHOU
    assert tarefa.resposta.startswith("Não consegui."), tarefa.resposta
    assert "ler a página" in tarefa.resposta and "rolar a página" in tarefa.resposta
    for proibido in ("browser.", "abri", "Pronto", "{"):
        assert proibido not in tarefa.resposta, proibido
    # o orçamento: no máximo 4 falhas seguidas; a idêntica passageira rodou só uma vez a mais
    assert extensao.metodos.count("page.read") == 2
    assert any("desisti" in linha for linha in tela), tela


# --- o motor que cai numa rodada --------------------------------------------------------------
class _CaiUmaVez:
    """O motor de verdade (a CLI) que sai com erro numa rodada da tarefa e depois volta."""

    def __init__(self, motor: MotorRoteirizado) -> None:
        self._motor = motor
        self.caiu = False
        self.nome = "roteirizado que cai"

    @property
    def onde(self) -> Onde:
        return Onde.LOCAL

    def gerar(self, contexto: Contexto, modo: Modo, cancelado: Cancelado) -> Generator[Delta]:
        if _resultados(contexto) and not self.caiu:
            self.caiu = True
            yield Fim(MotivoDoFim.ERRO, "código 1: overloaded")
            return
        yield from self._motor.gerar(contexto, modo, cancelado)


def test_a_rodada_do_motor_que_cai_e_tentada_de_novo_e_a_tarefa_conclui(
    tmp_path: Path, auditoria: LogDeAuditoria
) -> None:
    extensao = ExtensaoQueFalha()

    tarefa, tela, _motor = _rodar(tmp_path, auditoria, extensao, _roteiro_vazio, motor=_CaiUmaVez)

    assert tarefa.estado is EstadoDaTarefa.CONCLUIDA, tarefa.motivo
    assert tarefa.resposta == f"O título é «{TITULO}»."
    assert any("o motor não respondeu" in linha for linha in tela), tela


# --- as peças, sem laço ----------------------------------------------------------------------
def test_a_passageira_tem_uma_segunda_chance_e_a_permanente_nenhuma() -> None:
    recuperacao = Recuperacao()
    navegar = PedidoDeTool("browser.navigate", {"url": OUTRA})
    marca = assinatura(navegar.tool_id, navegar.args)
    recuperacao.registrar_falha(Tentativa("browser.navigate", marca, "tempo_esgotado", ""))
    assert recuperacao.repetida(navegar) is None
    recuperacao.registrar_falha(Tentativa("browser.navigate", marca, "tempo_esgotado", ""))
    assert recuperacao.repetida(navegar) is not None
    outra = Recuperacao()
    outra.registrar_falha(Tentativa("browser.navigate", marca, "aba_nao_mudou", ""))
    assert outra.repetida(navegar) is not None
    assert outra.repetida(PedidoDeTool("browser.navigate", {"url": URL})) is None


def test_o_orcamento_por_passo_e_por_tarefa() -> None:
    recuperacao = Recuperacao()
    for indice in range(3):
        recuperacao.registrar_falha(Tentativa("browser.read", f"a{indice}", "sem_resposta", ""))
    assert not recuperacao.esgotou()
    recuperacao.registrar_falha(Tentativa("browser.read", "a3", "sem_resposta", ""))
    assert recuperacao.esgotou()
    total = Recuperacao(tentativas_por_passo=99, falhas_por_tarefa=2)
    total.registrar_falha(Tentativa("x", "1", "erro_da_ferramenta", ""))
    total.seguidas = 0  # um sucesso no meio
    total.registrar_falha(Tentativa("x", "2", "erro_da_ferramenta", ""))
    assert total.esgotou()


def test_a_extensao_desatualizada_nao_gasta_tentativa() -> None:
    from jarvis.executor.ferramentas import ResultadoDeFerramenta

    resultado = ResultadoDeFerramenta(
        "browser.console",
        "erro",
        motivo="extensão desatualizada (extensao_desatualizada): recarregue",
        causa="erro_da_ferramenta",
    )
    assert codigo_da_falha(resultado) == "extensao_desatualizada"
    recuperacao = Recuperacao()
    recuperacao.observar((resultado,), ("browser.console {}",))
    sem_saida = recuperacao.sem_saida()
    assert sem_saida is not None and sem_saida.codigo == "extensao_desatualizada"
