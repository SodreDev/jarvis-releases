"""ADR-0038: o pedido que precisa de ferramenta vira tarefa do objetivo (dono, 2026-10-21).

O relato do dono: o Jarvis lia em voz alta a chamada e os argumentos das ferramentas, ficava
surdo enquanto o laço rodava dentro do turno e, em "abre um vídeo no YouTube", parava depois da
primeira tentativa. Aqui, sem rede e sem navegador de verdade (a extensão é um falso atrás do
`ClienteDoNavegador`), o que se prova:

- o protocolo de ferramenta nunca chega à fala do turno nem à resposta da tarefa;
- o turno acaba na frase curta e as ferramentas seguem **encadeadas na mesma tarefa**;
- a conversa recebe um pedido novo enquanto a tarefa trabalha;
- a aba muda de verdade antes de o Jarvis dizer que abriu, e "abri" sem conferir não passa;
- a falha do navegador volta como frase de gente, sem fingir sucesso;
- a pergunta de uma tarefa espera o dono sem prender a conversa, e o "sim" falado só vale depois
  de ela tocar inteira (o PDP e o Jev de sempre).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.decisao.fake import ClassificadorFalso
from jarvis.decisao.interface import Pergunta, Resposta, RespostaEscolha, RespostaNoul
from jarvis.executor.ferramentas import ExecutorDeFerramentas
from jarvis.navegador.cliente import ClienteDoNavegador, NavegadorIndisponivel
from jarvis.navegador.ferramentas import CorposDoNavegador
from jarvis.navegador.protocolo import PedidoDaPonte
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp
from jarvis.s2.cerebro import FRASE_AO_DELEGAR, Cerebro
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.s2.pendencias import RegistroDePendencias
from jarvis.s2.portao import AutorizacoesExplicitas, PortaoDeAcao
from jarvis.s2.tarefa_do_pedido import NOTA_DE_CONFERIR
from jarvis.tarefas.gestor import EstadoDaTarefa, GestorDeTarefas, Tarefa

BUSCA = "https://www.youtube.com/results?search_query=canal+x"
VIDEO = "https://www.youtube.com/watch?v=novo"
TITULO = "Vídeo novo do Canal X"
PEDIDO = "abre o vídeo mais recente do canal X no youtube"
PROTOCOLO = ("tool_id", "<<", ">>", "{", "}", "browser.", "files.", '"args"', "invoke")


class ExtensaoFalsa:
    """O que a extensão responderia, **com estado**: a aba muda quando navega, e a leitura lê a
    página que está nela. Responde como a extensão confere a navegação (a aba saiu do lugar, a
    página nova respondeu) e aceita a aba nova na janela do Jarvis."""

    def __init__(self) -> None:
        self.abas: dict[int, str] = {7: "https://www.google.com/"}
        self.ativa = 7
        self.fora_do_ar = False
        self.metodos: list[str] = []
        self.leitura_liberada = threading.Event()
        self.leitura_liberada.set()
        self.lendo = threading.Event()

    @property
    def url(self) -> str:
        """O endereço da aba que o dono vê."""
        return self.abas[self.ativa]

    def _aba(self, tab_id: object = None) -> dict[str, Any]:
        identificador = tab_id if isinstance(tab_id, int) and tab_id in self.abas else self.ativa
        url = self.abas[identificador]
        return {
            "id": identificador,
            "janelaId": 1 if identificador == 7 else 50,
            "ativa": identificador == self.ativa,
            "url": url,
            "titulo": _titulo(url),
        }

    def _foi(self, tab_id: int) -> dict[str, Any]:
        aba = self._aba(tab_id)
        pagina = {"url": aba["url"], "titulo": aba["titulo"]}
        visivel = tab_id == self.ativa
        janela = "dono" if tab_id == 7 else "jarvis"
        return {"aba": aba, "comecou": True, "carregou": True, "pagina": pagina} | {
            "janela": janela,
            "visivel": visivel,
        }

    def chamar(self, pedido: PedidoDaPonte, navegador: str = "") -> dict[str, Any]:
        if self.fora_do_ar:
            raise NavegadorIndisponivel("nenhum navegador com a extensão do Jarvis está aberto")
        self.metodos.append(pedido.method)
        ok = {"id": pedido.id, "ok": True}
        p = pedido.params
        match pedido.method:
            case "tabs.list":
                return ok | {"result": {"abas": [self._aba(i) for i in self.abas]}}
            case "tabs.current":
                return ok | {"result": {"aba": self._aba(p.get("tabId"))}}
            case "tabs.navigate":
                tab_id = int(p["tabId"]) if p.get("tabId") in self.abas else self.ativa
                self.abas[tab_id] = str(p["url"])
                return ok | {"result": self._foi(tab_id)}
            case "tabs.open":
                tab_id = max(self.abas) + 1
                self.abas[tab_id] = str(p["url"])
                return ok | {"result": self._foi(tab_id)}
            case "tabs.show":
                self.ativa = int(p["tabId"])
                return ok | {"result": {"visivel": True, "janela": "dono"}}
            case "page.read":
                self.lendo.set()
                assert self.leitura_liberada.wait(5.0)
                url = self._aba(p.get("tabId"))["url"]
                links = [{"texto": TITULO, "href": VIDEO}] if "results" in url else []
                pagina = {"url": url, "titulo": _titulo(url), "textoVisivel": "Canal X"}
                return ok | {"result": pagina | {"links": links, "datas": []}}
        raise AssertionError(pedido.method)


def _titulo(url: str) -> str:
    if "watch?v=novo" in url:
        return f"{TITULO} - YouTube"
    return "Resultados" if "results" in url else "Google"


@pytest.fixture
def extensao() -> ExtensaoFalsa:
    return ExtensaoFalsa()


@pytest.fixture
def executor(tmp_path: Path, extensao: ExtensaoFalsa) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    (lar / "Documentos").mkdir(parents=True)
    (lar / "Documentos" / "notas.txt").write_text("comprar café\n", "utf-8")
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
        )
        ex = ExecutorDeFerramentas(
            pdp=pdp,
            lar=lar,
            abrir_site=lambda _url: None,
            navegador=CorposDoNavegador(ClienteDoNavegador(extensao)),
        )
        ex.preparar()
        ex.tarefas = GestorDeTarefas(executor=ex, confirmar=lambda _p, _c: False)
        yield ex
        ex.tarefas.encerrar()


def _falado(publicados: Sequence[Mapping[str, Any]]) -> str:
    return " ".join(str(p["text"]) for p in publicados if p["text"])


def _cerebro(executor: ExecutorDeFerramentas, motor: MotorRoteirizado, **extra: Any) -> Cerebro:
    return Cerebro(motor=motor, ferramentas=executor, delegar_em_tarefa=True, **extra)


def _tarefa(executor: ExecutorDeFerramentas, tarefa_id: str) -> Tarefa:
    assert executor.tarefas is not None
    assert executor.tarefas.esperar(tarefa_id, 10.0), "a tarefa não terminou"
    return executor.tarefas.tarefas[tarefa_id]


def _feitas(contexto: Contexto) -> list[str]:
    return [m.texto for m in contexto.mensagens if m.papel == "ferramenta"]


def _sem_protocolo(texto: str) -> None:
    for marca in PROTOCOLO:
        assert marca not in texto, f"{marca!r} vazou em {texto!r}"


# --- o protocolo não vaza --------------------------------------------------------------------
def test_protocolo_escrito_como_texto_nao_vai_a_fala_nem_a_resposta(
    executor: ExecutorDeFerramentas,
) -> None:
    """O motor esqueceu a marca, depois narrou o passo e por fim citou a ferramenta: nada disso é
    fala. O JSON solto e a marca viram propostas (rodam pelo PDP), a narração vira raciocínio e a
    frase que cita a ferramenta sai da resposta."""
    listar = json.dumps({"tool_id": "files.list_dir", "args": {"path": "~/Documentos"}})
    ler = json.dumps({"tool_id": "files.read_text", "args": {"path": "~/Documentos/notas.txt"}})

    def roteiro(contexto: Contexto) -> Sequence[Parte]:
        feitas = len(_feitas(contexto))
        if feitas == 0:
            return [f"Deixa eu ver. {listar}"]
        if feitas == 1:
            return [f"Achei a pasta, agora leio. <<ferramenta>> {ler}"]
        return ["Usei files.read_text para ler a nota. Na sua nota tem comprar café."]

    motor = MotorRoteirizado(resposta=roteiro)
    publicados: list[dict[str, Any]] = []

    resposta = _cerebro(executor, motor).responder(
        "o que tem na minha nota?", epoch=0, publicar=publicados.append
    )
    tarefa = _tarefa(executor, resposta.tarefa_id)

    assert _falado(publicados) == "Deixa eu ver."
    assert tarefa.estado is EstadoDaTarefa.CONCLUIDA
    assert tarefa.resposta == "Na sua nota tem comprar café."
    _sem_protocolo(_falado(publicados))
    _sem_protocolo(tarefa.resposta)


def test_sem_frase_do_motor_o_turno_diz_a_frase_curta_do_codigo(
    executor: ExecutorDeFerramentas,
) -> None:
    motor = MotorRoteirizado(
        resposta=lambda c: (
            [PedidoDeTool("files.list_dir", {"path": "~/Documentos"})]
            if not _feitas(c)
            else ["Tem só o arquivo de notas."]
        )
    )
    publicados: list[dict[str, Any]] = []
    resposta = _cerebro(executor, motor).responder(
        "lista Documentos", epoch=0, publicar=publicados.append
    )
    assert _falado(publicados) == FRASE_AO_DELEGAR
    assert _tarefa(executor, resposta.tarefa_id).resposta == "Tem só o arquivo de notas."


# --- várias ferramentas, uma tarefa; a conversa segue ---------------------------------------
def _roteiro_do_youtube(contexto: Contexto) -> Sequence[Parte]:
    if contexto.turno != PEDIDO:
        return ["São dez horas."]
    feitas = len(_feitas(contexto))
    if feitas == 0:
        return ["Vou procurar no YouTube. ", PedidoDeTool("browser.navigate", {"url": BUSCA})]
    if feitas == 1:
        return [PedidoDeTool("browser.read", {})]
    if feitas == 2:
        return ["Achei, vou abrir. ", PedidoDeTool("browser.navigate", {"url": VIDEO})]
    if feitas == 3:
        if NOTA_DE_CONFERIR in contexto.sistema:
            return [PedidoDeTool("browser.read", {})]
        return ["Pronto, abri o vídeo."]  # sem conferir: o código não aceita
    return [f"Abri «{TITULO}» na aba atual."]


def test_abrir_video_no_youtube_encadeia_ate_a_aba_mudar_e_conferir(
    executor: ExecutorDeFerramentas, extensao: ExtensaoFalsa
) -> None:
    motor = MotorRoteirizado(resposta=_roteiro_do_youtube)
    publicados: list[dict[str, Any]] = []

    resposta = _cerebro(executor, motor).responder(PEDIDO, epoch=0, publicar=publicados.append)
    tarefa = _tarefa(executor, resposta.tarefa_id)

    assert resposta.ferramentas == [], "o turno não roda ferramenta: ela vai para a tarefa"
    assert _falado(publicados) == "Vou procurar no YouTube."
    assert extensao.url == VIDEO, "a aba do dono mudou de verdade"
    navegou = extensao.metodos.count("tabs.navigate") + extensao.metodos.count("tabs.open")
    assert navegou == 2 and extensao.metodos.count("page.read") == 2
    assert tarefa.passo == 4, "quatro ferramentas na mesma tarefa, uma depois da outra"
    assert tarefa.estado is EstadoDaTarefa.CONCLUIDA
    assert tarefa.resposta == f"Abri «{TITULO}» na aba atual."
    assert any(NOTA_DE_CONFERIR in c.sistema for c in motor.pedidos), "o código cobrou a leitura"
    assert "Pronto, abri o vídeo" not in tarefa.resposta + _falado(publicados)
    objetivo = tarefa.contaminacao.objetivo
    assert objetivo is not None and not objetivo.falta_conferir


def test_a_conversa_recebe_outro_pedido_enquanto_a_tarefa_trabalha(
    executor: ExecutorDeFerramentas, extensao: ExtensaoFalsa
) -> None:
    extensao.leitura_liberada.clear()  # a leitura da página fica presa até o teste soltar
    motor = MotorRoteirizado(resposta=_roteiro_do_youtube)
    cerebro = _cerebro(executor, motor)

    primeira = cerebro.responder(PEDIDO, epoch=0, publicar=lambda _p: None)
    assert extensao.lendo.wait(5.0), "a tarefa chegou à leitura"
    publicados: list[dict[str, Any]] = []
    segunda = cerebro.responder("que horas são?", epoch=1, publicar=publicados.append)

    assert executor.tarefas is not None
    assert executor.tarefas.tarefas[primeira.tarefa_id].estado is EstadoDaTarefa.RODANDO
    assert _falado(publicados) == "São dez horas." and not segunda.tarefa_id
    extensao.leitura_liberada.set()
    assert _tarefa(executor, primeira.tarefa_id).estado is EstadoDaTarefa.CONCLUIDA
    assert extensao.url == VIDEO


# --- a falha volta como resultado útil ------------------------------------------------------
def test_navegador_fora_do_ar_volta_como_frase_de_gente_sem_fingir_sucesso(
    executor: ExecutorDeFerramentas, extensao: ExtensaoFalsa
) -> None:
    extensao.fora_do_ar = True

    def roteiro(contexto: Contexto) -> Sequence[Parte]:
        feitas = len(_feitas(contexto))
        if feitas == 0:
            return ["Vou abrir. ", PedidoDeTool("browser.navigate", {"url": BUSCA})]
        if feitas == 1:  # outra tentativa, por outro caminho
            return [PedidoDeTool("browser.navigate", {"url": VIDEO, "nova_aba": True})]
        return ["Pronto, abri o vídeo."]  # mente: nenhuma tentativa deu certo

    publicados: list[dict[str, Any]] = []
    resposta = _cerebro(executor, MotorRoteirizado(resposta=roteiro)).responder(
        PEDIDO, epoch=0, publicar=publicados.append
    )
    tarefa = _tarefa(executor, resposta.tarefa_id)

    assert tarefa.passo == 2, "não parou depois da primeira tentativa"
    assert tarefa.estado is EstadoDaTarefa.FALHOU
    assert tarefa.resposta == (
        "Não consegui: nenhum navegador com a extensão do Jarvis está aberto."
    )
    assert "Pronto" not in tarefa.resposta
    _sem_protocolo(tarefa.resposta)


def test_cancelar_a_tarefa_para_os_passos_e_nao_responde_como_se_tivesse_feito(
    executor: ExecutorDeFerramentas, extensao: ExtensaoFalsa
) -> None:
    extensao.leitura_liberada.clear()
    resposta = _cerebro(executor, MotorRoteirizado(resposta=_roteiro_do_youtube)).responder(
        PEDIDO, epoch=0, publicar=lambda _p: None
    )
    assert extensao.lendo.wait(5.0)
    assert executor.tarefas is not None
    executor.tarefas.cancelar(resposta.tarefa_id)
    extensao.leitura_liberada.set()
    tarefa = _tarefa(executor, resposta.tarefa_id)
    assert tarefa.estado is EstadoDaTarefa.CANCELADA
    assert VIDEO not in extensao.abas.values(), "depois do cancelamento nenhum passo novo rodou"


def test_interromper_antes_da_proposta_nao_cria_tarefa(executor: ExecutorDeFerramentas) -> None:
    motor = MotorRoteirizado(resposta=_roteiro_do_youtube)
    resposta = _cerebro(executor, motor).responder(
        PEDIDO, epoch=0, publicar=lambda _p: None, cancelado=lambda: True
    )
    assert resposta.cancelada and not resposta.tarefa_id
    assert executor.tarefas is not None and executor.tarefas.tarefas == {}


# --- a pergunta da tarefa: PDP, Jev e o "sim" de sempre -------------------------------------
class _Relogio:
    agora = 1000.0

    def __call__(self) -> float:
        return self.agora


def _jev(resposta: str) -> ClassificadorFalso:
    def roteiro(_estado: Any, perguntas: Mapping[str, Pergunta]) -> Mapping[str, Resposta]:
        if "acao" in perguntas:
            return {
                "acao": RespostaEscolha("fazer", 0.95, {"fazer": 0.95}),
                "pedido_explicito": RespostaNoul(0.0),
            }
        return {"resposta": RespostaEscolha(resposta, 0.95, {resposta: 0.95})}

    return ClassificadorFalso(roteiro=roteiro)


def test_a_pergunta_da_tarefa_espera_o_sim_falado_depois_de_tocar(
    executor: ExecutorDeFerramentas,
) -> None:
    """Ler a nota contamina; abrir o site que saiu dela é `confirm` no PDP. Na tarefa, isso vira
    a pendência de sempre, mas quem espera é a tarefa: a conversa segue. O "sim" dito antes de a
    pergunta tocar não vale; depois, vale uma vez, e a tarefa continua até a resposta."""
    abertos: list[str] = []
    executor.abrir_site = abertos.append
    avisos: list[tuple[str, str, str]] = []
    assert executor.tarefas is not None
    executor.tarefas.ao_avisar = lambda _t, i, tipo, frase: avisos.append((i, tipo, frase))

    def roteiro(contexto: Contexto) -> Sequence[Parte]:
        feitas = len(_feitas(contexto))
        if contexto.turno != "lê as notas e abre o site que estiver nelas":
            return ["Certo."]
        if feitas == 0:
            return [PedidoDeTool("files.read_text", {"path": "~/Documentos/notas.txt"})]
        if feitas == 1:
            return [PedidoDeTool("sites.open", {"url": "https://exemplo.com.br"})]
        return ["Abri o exemplo.com.br."]

    relogio = _Relogio()
    cerebro = _cerebro(
        executor,
        MotorRoteirizado(resposta=roteiro),
        portao=PortaoDeAcao(classificador=_jev("sim")),
        pendencias=RegistroDePendencias(relogio=relogio),
        autorizacoes=AutorizacoesExplicitas(relogio=relogio),
    )
    resposta = cerebro.responder(
        "lê as notas e abre o site que estiver nelas", epoch=0, publicar=lambda _p: None
    )
    tarefa_id = resposta.tarefa_id
    fim = time.monotonic() + 30.0  # generoso: sob carga a tarefa demora a chegar à pergunta
    while cerebro.pendencias.valida() is None and time.monotonic() < fim:
        threading.Event().wait(0.01)
    pendencia = cerebro.pendencias.valida()
    assert pendencia is not None and pendencia.espera is not None
    assert executor.tarefas.tarefas[tarefa_id].estado is EstadoDaTarefa.ESPERANDO_O_DONO
    pergunta = next(a for a in avisos if a[1] == "precisa_decisao")
    assert pergunta[0] == f"pergunta-{pendencia.id}"
    assert pergunta[2] == "Preciso do seu sim para abrir exemplo.com.br no seu navegador. Posso?"

    antes = cerebro.responder("sim", epoch=1, publicar=lambda _p: None)
    assert antes.motor != "portao", "a pergunta não tocou: o sim não a responde"
    assert cerebro.pendencias.valida() is not None and abertos == []

    cerebro.pendencias.marcar_ouvida(pendencia.id)
    publicados: list[dict[str, Any]] = []
    depois = cerebro.responder("sim", epoch=2, publicar=publicados.append)
    tarefa = _tarefa(executor, tarefa_id)

    assert depois.motor == "portao"
    assert _falado(publicados).startswith("Certo, estou fazendo: abrir exemplo.com.br")
    assert abertos == ["https://exemplo.com.br"]
    assert tarefa.estado is EstadoDaTarefa.CONCLUIDA
    # O motor foi cobrado a conferir e não leu: a resposta diz isso, em vez de afirmar sozinha.
    assert tarefa.resposta == "Abri o exemplo.com.br. Não consegui conferir se ficou certo."


def test_a_voz_da_pergunta_nao_tem_id_de_ferramenta_nem_json(
    executor: ExecutorDeFerramentas,
) -> None:
    """A janela mostra a chamada exata (`detalhe`); a voz diz a ação em frase de gente."""
    from jarvis.executor.ferramentas import Avaliacao

    avaliacao = executor.avaliar("browser.click", {"alvo": "Enviar"})
    assert isinstance(avaliacao, Avaliacao)
    pergunta = executor.pergunta_de(avaliacao)
    executor.descartar(avaliacao, "negado", "teste", causa="dono_nao_confirmou")

    assert "browser.click" in pergunta.detalhe and "{" in pergunta.detalhe
    assert pergunta.para_ouvir == "clicar num elemento da página «Enviar»"
    _sem_protocolo(pergunta.para_ouvir)
