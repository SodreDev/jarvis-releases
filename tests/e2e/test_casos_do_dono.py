"""Os cinco casos do dono, de ponta a ponta, com motor e ferramentas falsos (ADR-0070).

Nada aqui toca o navegador, as contas, o microfone nem o áudio de verdade: a extensão é um
falso **com estado e com DOM** (uma página do WhatsApp Web com a lista de conversas, o
cabeçalho, o campo e o botão de enviar) atrás do `ClienteDoNavegador` de verdade; o Claude
Code é o `claude` falso dos testes da delegação (um processo Python que só escreve arquivos na
pasta do teste); o motor é o roteirizado, no papel do Jarvis e do subagente. O que passa por
dentro é o código de produção: o cérebro, o gestor de tarefas, o motor do objetivo, a leitura
antes de agir, o PDP e a delegação. O caso (c), o alerta de rede, está em
`test_no_aplicativo.py`, com o aplicativo inteiro.

Os casos:

(a) «clica na conversa do Bruno»: o subagente LÊ a página antes de clicar, escolhe o alvo
    pelo que está nela e confere depois; o clique que falha leva a uma releitura e a outra
    tentativa, não à desistência;
(b) «manda pro Bruno que …»: a mensagem é REDIGIDA (não é a fala copiada), o contato é
    conferido no cabeçalho antes de digitar, e o envio é conferido depois;
(d) estouro de tentativas, do prazo do turno e dos turnos do subagente: vira notificação com
    o estado real, e o Jarvis decide (seguir, perguntar ou encerrar);
(e) delegação: o pedido ao subagente é FORMULADO (a cópia da fala é recusada) e a resposta ao
    dono só vem depois do retorno; a conversa segue livre, uma resposta por estímulo.
"""

from __future__ import annotations

import json
import re
import stat
import sys
import threading
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.delegacao.claude_code import HOST_NATIVO, DelegadorClaudeCode
from jarvis.delegacao.config import ConfiguracaoDaDelegacao
from jarvis.delegacao.pedido import RECUSA_DE_COPIA
from jarvis.executor.ferramentas import ExecutorDeFerramentas
from jarvis.navegador.cliente import ClienteDoNavegador
from jarvis.navegador.ferramentas import CorposDoNavegador
from jarvis.navegador.protocolo import PedidoDaPonte
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp
from jarvis.politica.permissao import ModoDePermissao
from jarvis.s2.cerebro import NOTA_DO_LIMITE_DO_TURNO, Cerebro
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.s2.roteiro_do_navegador import Contato
from jarvis.tarefas.gestor import EstadoDaTarefa, GestorDeTarefas, Tarefa
from jarvis.tarefas.limite import MARCA_DA_NOTIFICACAO

RAIZ = Path(__file__).resolve().parents[2]
CLAUDE_FALSO = RAIZ / "tests" / "unit" / "delegacao" / "claude_falso.py"
WHATSAPP = "https://web.whatsapp.com/"
CONVERSAS = ("Ana", "Bruno", "Carla")
ESPERA_S = 20.0


# --- a extensão falsa, com DOM -----------------------------------------------------------------
class PaginaDoWhatsApp:
    """A extensão do Jarvis respondendo como numa aba do WhatsApp Web, com estado.

    Cada leitura (`page.map`) é um instantâneo novo, e os `ref` são do instantâneo: o `ref` de uma
    leitura velha não serve depois que a página mudou — como na extensão de verdade. O clique pode
    falhar de propósito (`cliques_que_falham`: um aviso por cima da lista), e a mensagem só aparece
    na conversa depois do clique no botão de enviar."""

    def __init__(self) -> None:
        self.aberta = ""
        self.rascunho = ""
        self.enviadas: dict[str, list[str]] = {nome: [] for nome in CONVERSAS}
        self.instantaneo = 0
        self.cliques_que_falham = 0
        self.metodos: list[str] = []
        self.cliques: list[str] = []

    # o mapa da página: o que o subagente vê
    def _elementos(self) -> list[dict[str, Any]]:
        n = self.instantaneo
        elementos: list[dict[str, Any]] = [
            {"ref": f"m{n}.{i}", "papel": "listitem", "rotulo": nome, "nome": nome}
            for i, nome in enumerate(CONVERSAS)
        ]
        if self.aberta:
            elementos += [
                {"ref": f"m{n}.10", "papel": "heading", "rotulo": self.aberta},
                {
                    "ref": f"m{n}.11",
                    "papel": "textbox",
                    "rotulo": "Digite uma mensagem",
                    "campo": True,
                },
                {"ref": f"m{n}.12", "papel": "button", "rotulo": "Enviar"},
            ]
        return elementos

    def _por_ref(self, ref: object) -> dict[str, Any] | None:
        return next((e for e in self._elementos() if e["ref"] == ref), None)

    def _aba(self) -> dict[str, Any]:
        return {"id": 7, "janelaId": 1, "ativa": True, "url": WHATSAPP, "titulo": "WhatsApp"}

    def chamar(self, pedido: PedidoDaPonte, navegador: str = "") -> dict[str, Any]:
        self.metodos.append(pedido.method)
        ok = {"id": pedido.id, "ok": True}
        p = pedido.params
        match pedido.method:
            case "tabs.list":
                return ok | {"result": {"abas": [self._aba()]}}
            case "tabs.current":
                return ok | {"result": {"aba": self._aba()}}
            case "page.map":
                self.instantaneo += 1
                elementos = self._elementos()
                return ok | {
                    "result": {
                        "url": WHATSAPP,
                        "titulo": "WhatsApp",
                        "instantaneo": self.instantaneo,
                        "total": len(elementos),
                        "elementos": elementos,
                    }
                }
            case "page.read":
                cabecalho = f"Conversa com {self.aberta}. " if self.aberta else ""
                ultimas = " ".join(f"Você: {m}" for m in self.enviadas.get(self.aberta, []))
                return ok | {
                    "result": {
                        "url": WHATSAPP,
                        "titulo": "WhatsApp",
                        "textoVisivel": f"{cabecalho}{ultimas}".strip() or "Lista de conversas",
                        "links": [],
                        "datas": [],
                    }
                }
            case "page.inspect":
                elemento = self._por_ref(p.get("ref"))
                if elemento is None:
                    return {"id": pedido.id, "ok": False, "error": _erro("referência velha")}
                return ok | {"result": dict(elemento)}
            case "page.click":
                elemento = self._por_ref(p.get("ref"))
                if elemento is None:
                    return {"id": pedido.id, "ok": False, "error": _erro("referência velha")}
                if self.cliques_que_falham > 0:
                    self.cliques_que_falham -= 1
                    self.instantaneo += 1  # o aviso por cima mudou a página: os ref velhos caem
                    return {
                        "id": pedido.id,
                        "ok": False,
                        "error": _erro("o elemento está coberto por outro (um aviso por cima)"),
                    }
                self.cliques.append(str(elemento["rotulo"]))
                if elemento["papel"] == "listitem":
                    self.aberta, self.rascunho = str(elemento["rotulo"]), ""
                elif elemento["rotulo"] == "Enviar" and self.rascunho:
                    self.enviadas[self.aberta].append(self.rascunho)
                    self.rascunho = ""
                self.instantaneo += 1
                return ok | {"result": {"clicado": True}}
            case "page.type":
                elemento = self._por_ref(p.get("ref"))
                if elemento is None or not elemento.get("campo"):
                    return {"id": pedido.id, "ok": False, "error": _erro("não é um campo")}
                self.rascunho = str(p["texto"])
                return ok | {"result": {"digitado": len(self.rascunho)}}
        raise AssertionError(f"método inesperado na extensão falsa: {pedido.method}")


def _erro(mensagem: str) -> dict[str, str]:
    return {"codigo": "falha", "mensagem": mensagem}


# --- a montagem --------------------------------------------------------------------------------
def _claude_falso(pasta: Path, modo: str) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / "claude"
    alvo.write_text(f"#!{sys.executable} -I\n" + CLAUDE_FALSO.read_text("utf-8"), "utf-8")
    alvo.chmod(alvo.stat().st_mode | stat.S_IXUSR)
    (pasta / "modo.txt").write_text(modo, "utf-8")
    return alvo


def _delegador(tmp_path: Path, modo: str) -> tuple[DelegadorClaudeCode, Path]:
    pasta = tmp_path / "bin"
    executavel = _claude_falso(pasta, modo)
    casa = tmp_path / "casa-do-claude"
    host = casa / ".config" / "google-chrome" / "NativeMessagingHosts"
    host.mkdir(parents=True)
    (host / HOST_NATIVO).write_text("{}", "utf-8")
    delegador = DelegadorClaudeCode(
        configuracao=ConfiguracaoDaDelegacao(
            ligado=True, executavel=str(executavel), prazo_s=30.0, max_turnos=7
        ),
        ambiente={"HOME": str(casa), "PATH": "/usr/bin:/bin", "LANG": "pt_BR.UTF-8"},
        lar=casa,
    )
    return delegador, pasta


def _registros(pasta: Path) -> list[dict[str, Any]]:
    arquivos = sorted(pasta.glob("registro-*.json"), key=lambda p: int(p.stem.split("-")[1]))
    return [json.loads(a.read_text("utf-8")) for a in arquivos]


@pytest.fixture
def pagina() -> PaginaDoWhatsApp:
    return PaginaDoWhatsApp()


@pytest.fixture
def executor(tmp_path: Path, pagina: PaginaDoWhatsApp) -> Iterator[ExecutorDeFerramentas]:
    yield from _montar(tmp_path, pagina)


@pytest.fixture
def sem_extensao(tmp_path: Path) -> Iterator[ExecutorDeFerramentas]:
    """Sem a extensão do Jarvis no navegador: o caminho em que delegar ao Claude Code vale (com
    ela, a delegação é o último recurso — ADR-0054)."""
    yield from _montar(tmp_path, None)


def _montar(tmp_path: Path, pagina: PaginaDoWhatsApp | None) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    lar.mkdir()
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
            # O modo do dono (2026-11-14): age sem pedir; só matar processo e apagar pedem o sim.
            permissao=ModoDePermissao.AUTOMATICO,
        )
        ex = ExecutorDeFerramentas(
            pdp=pdp,
            lar=lar,
            abrir_site=lambda _url: None,
            navegador=CorposDoNavegador(ClienteDoNavegador(pagina)) if pagina else None,
        )
        ex.preparar()
        # O dono diz «sim» ao que ainda perguntar (a delegação gasta a cota dele, ADR-0054).
        ex.tarefas = GestorDeTarefas(executor=ex, confirmar=lambda _p, _c: True)
        yield ex
        ex.tarefas.encerrar()


def _cerebro(executor: ExecutorDeFerramentas, motor: MotorRoteirizado, **extra: Any) -> Cerebro:
    """O cérebro como o aplicativo liga: a execução vai ao subagente (ADR-0070)."""
    return Cerebro(
        motor=motor,
        ferramentas=executor,
        delegar_em_tarefa=True,
        contatos=lambda: (Contato("Bruno", "meu irmão"),),
        **extra,
    )


def _tarefa(executor: ExecutorDeFerramentas, tarefa_id: str) -> Tarefa:
    assert executor.tarefas is not None
    assert executor.tarefas.esperar(tarefa_id, ESPERA_S), "a tarefa não terminou"
    return executor.tarefas.tarefas[tarefa_id]


def _resultados(contexto: Contexto) -> list[dict[str, Any]]:
    """Os resultados de ferramenta que o motor vê, como o JSON que chega a ele."""
    saida: list[dict[str, Any]] = []
    for mensagem in contexto.mensagens:
        if mensagem.papel != "ferramenta":
            continue
        try:
            saida.append(json.loads(mensagem.texto.split(" …[truncado]")[0]))
        except ValueError:
            saida.append({"tool_id": "?", "status": "?", "bruto": mensagem.texto})
    return saida


def _ref(mapa: dict[str, Any], papel: str, rotulo: str) -> str:
    """O `ref` que o subagente escolhe **pelo que está na página** (o mapa da última leitura)."""
    for elemento in mapa.get("dados", {}).get("elementos", []):
        if elemento.get("papel") == papel and elemento.get("rotulo") == rotulo:
            return str(elemento["ref"])
    raise AssertionError(f"«{rotulo}» ({papel}) não está no mapa: {mapa}")


def _cabecalho(mapa: dict[str, Any]) -> str:
    for elemento in mapa.get("dados", {}).get("elementos", []):
        if elemento.get("papel") == "heading":
            return str(elemento.get("rotulo", ""))
    return ""


def _falado(publicados: Sequence[dict[str, Any]]) -> str:
    return " ".join(str(p["text"]) for p in publicados if p["text"]).strip()


# --- (a) clicar na conversa: ler antes, escolher pelo que há, conferir depois -------------------
class SubagenteDoClique:
    """O Jarvis/subagente: chuta o clique no turno — a ação volta com o veredito de ler antes
    (ADR-0072) e ELE lê —, escolhe o `ref` no mapa, tenta de novo depois do erro e confere a
    conversa aberta antes de dizer que abriu."""

    def __init__(self, alvo: str) -> None:
        self.alvo = alvo
        self.vistos: list[list[str]] = []

    def __call__(self, contexto: Contexto) -> Sequence[Parte]:
        feitos = _resultados(contexto)
        self.vistos.append([f"{r['tool_id']}:{r['status']}:{r.get('motivo', '')}" for r in feitos])
        if "A SUA ÚLTIMA PROPOSTA não rodou" in contexto.sistema:
            return [PedidoDeTool("browser.inspecionar", {})]  # o veredito: ler antes de agir
        if not feitos:
            # Sem ler nada, o palpite: clicar pelo texto. Quem não deixa é a leitura antes de agir.
            return [PedidoDeTool("browser.click", {"alvo": f"conversa do {self.alvo}"})]
        ultimo = feitos[-1]
        if ultimo["tool_id"] == "browser.inspecionar" and ultimo["status"] == "ok":
            if _cabecalho(ultimo) == self.alvo:
                return [f"Abri a conversa do {self.alvo}."]
            return [PedidoDeTool("browser.click", {"ref": _ref(ultimo, "listitem", self.alvo)})]
        if ultimo["tool_id"] == "browser.click" and ultimo["status"] == "ok":
            return [PedidoDeTool("browser.inspecionar", {})]  # conferir antes de dizer
        if ultimo["tool_id"] == "browser.click":
            # O clique falhou: insiste no mesmo ref — o veredito manda reler antes.
            anterior = next(
                r for r in reversed(feitos[:-1]) if r["tool_id"] == "browser.inspecionar"
            )
            return [PedidoDeTool("browser.click", {"ref": _ref(anterior, "listitem", self.alvo)})]
        return [f"Não achei a conversa do {self.alvo}."]


def test_a_clicar_na_conversa_le_antes_escolhe_pela_pagina_e_confere(
    executor: ExecutorDeFerramentas, pagina: PaginaDoWhatsApp
) -> None:
    pagina.cliques_que_falham = 1
    subagente = SubagenteDoClique("Bruno")
    publicados: list[dict[str, Any]] = []

    resposta = _cerebro(executor, MotorRoteirizado(resposta=subagente)).responder(
        "clica na conversa do Bruno", epoch=0, publicar=publicados.append
    )

    # O turno não executa nada: o pedido foi ao subagente, e o código não falou ao delegar.
    assert resposta.tarefa_id and resposta.ferramentas == []
    assert _falado(publicados) == ""
    tarefa = _tarefa(executor, resposta.tarefa_id)
    assert tarefa.estado is EstadoDaTarefa.CONCLUIDA
    assert tarefa.resposta == "Abri a conversa do Bruno."
    assert pagina.aberta == "Bruno" and pagina.cliques == ["Bruno"]
    # A ordem na página: ler, clicar (falhou), RELER, clicar (deu), ler para conferir.
    na_pagina = [m for m in pagina.metodos if m in ("page.map", "page.click")]
    assert na_pagina == ["page.map", "page.click", "page.map", "page.click", "page.map"]
    # O primeiro clique nunca vem antes de uma leitura, e o palpite pelo texto não rodou.
    assert all(m != "page.click" for m in pagina.metodos[: pagina.metodos.index("page.map")])


# --- (b) mandar mensagem: redigir, conferir o contato, enviar, conferir o envio ----------------
FALA_DO_ENVIO = "manda pro Bruno no zap que vou atrasar uns dez minutos"
REDIGIDA = "Oi, Bruno! Vou me atrasar uns dez minutinhos, já chego."


class SubagenteDoEnvio:
    """Abre a conversa pelo mapa, confere o cabeçalho, digita a mensagem que ELE redigiu, clica em
    enviar e lê a conversa antes de dizer que mandou."""

    def __init__(self) -> None:
        self.sistema_da_tarefa = ""

    def __call__(self, contexto: Contexto) -> Sequence[Parte]:
        feitos = _resultados(contexto)
        if not feitos:
            return [PedidoDeTool("browser.inspecionar", {})]
        self.sistema_da_tarefa = contexto.sistema
        ultimo = feitos[-1]
        ok = [r["tool_id"] for r in feitos if r["status"] == "ok"]
        if ultimo["tool_id"] == "browser.read":
            texto = str(ultimo.get("dados", {}).get("texto", ""))
            assert "Conversa com Bruno" in texto
            return ["Mandei pro Bruno que você vai atrasar uns dez minutos."]
        if ultimo["tool_id"] == "browser.inspecionar":
            if _cabecalho(ultimo) != "Bruno":  # a trava: só digita na conversa certa
                return [PedidoDeTool("browser.click", {"ref": _ref(ultimo, "listitem", "Bruno")})]
            if "browser.type" not in ok:
                campo = _ref(ultimo, "textbox", "Digite uma mensagem")
                return [PedidoDeTool("browser.type", {"ref": campo, "texto": REDIGIDA})]
            return [PedidoDeTool("browser.click", {"ref": _ref(ultimo, "button", "Enviar")})]
        if ultimo["tool_id"] == "browser.click" and "browser.type" in ok:
            return [PedidoDeTool("browser.read", {})]  # conferir o envio
        return [PedidoDeTool("browser.inspecionar", {})]


def test_b_mandar_mensagem_redige_confere_o_contato_e_o_envio(
    executor: ExecutorDeFerramentas, pagina: PaginaDoWhatsApp
) -> None:
    subagente = SubagenteDoEnvio()
    publicados: list[dict[str, Any]] = []

    resposta = _cerebro(executor, MotorRoteirizado(resposta=subagente)).responder(
        FALA_DO_ENVIO, epoch=0, publicar=publicados.append
    )

    tarefa = _tarefa(executor, resposta.tarefa_id)
    assert tarefa.estado is EstadoDaTarefa.CONCLUIDA, tarefa.motivo
    # O que foi enviado é a mensagem que o Jarvis redigiu — não a fala do dono copiada.
    assert pagina.enviadas["Bruno"] == [REDIGIDA]
    assert all(not m for nome, m in pagina.enviadas.items() if nome != "Bruno")
    assert "vou atrasar uns dez minutos" not in REDIGIDA.casefold()
    # O subagente recebeu a orientação de redigir e as travas, não um texto pronto do código nem
    # o contato e a mensagem tirados da fala (ADR-0072).
    sistema = subagente.sistema_da_tarefa
    assert "Redija a mensagem" in sistema and "para «Bruno»" not in sistema
    assert "parece um envio direto" not in sistema, "nada tirado da fala por regex"
    assert "cabeçalho da conversa" in sistema
    # Antes de digitar, a página foi lida com a conversa do Bruno aberta (a trava do contato).
    antes_de_digitar = pagina.metodos[: pagina.metodos.index("page.type")]
    assert antes_de_digitar.count("page.map") >= 2 and pagina.cliques[0] == "Bruno"
    # Depois de enviar, a conversa foi lida antes de o Jarvis dizer que mandou.
    assert pagina.metodos.index("page.read") > len(pagina.metodos) - 3
    assert tarefa.resposta == "Mandei pro Bruno que você vai atrasar uns dez minutos."
    assert _falado(publicados) == "", "a resposta ao dono vem do fim da tarefa, não do turno"


# --- (d) limites viram notificação, e o Jarvis decide -------------------------------------------
def test_d_tentativas_esgotadas_viram_notificacao_e_o_jarvis_decide(
    executor: ExecutorDeFerramentas, pagina: PaginaDoWhatsApp
) -> None:
    """O clique falha sempre: o orçamento de tentativas acaba, a tarefa NÃO responde sozinha — o
    motor recebe a notificação com o que tentou e o erro real, e decide encerrar explicando."""
    pagina.cliques_que_falham = 1000
    notificacoes: list[str] = []

    def roteiro(contexto: Contexto) -> Sequence[Parte]:
        if MARCA_DA_NOTIFICACAO in contexto.sistema:
            assert not contexto.ferramentas, "a decisão no limite é do Jarvis, sem ferramentas"
            nota = contexto.sistema.split(MARCA_DA_NOTIFICACAO, 1)[1]
            notificacoes.append(nota)
            texto = "Tentei abrir a conversa do Bruno várias vezes, mas um aviso cobre a lista."
            return [json.dumps({"decisao": "encerrar", "texto": texto})]
        return SubagenteDoClique("Bruno")(contexto)

    resposta = _cerebro(executor, MotorRoteirizado(resposta=roteiro)).responder(
        "clica na conversa do Bruno", epoch=0, publicar=lambda _p: None
    )
    tarefa = _tarefa(executor, resposta.tarefa_id)

    assert notificacoes, "o limite chegou ao Jarvis como notificação"
    # O estado real: os passos e o erro de verdade da página, não uma frase pronta.
    assert "coberto por outro" in notificacoes[0] and "browser.click" in notificacoes[0]
    assert tarefa.resposta.startswith("Tentei abrir a conversa do Bruno")
    assert pagina.aberta == ""


def test_d_prazo_do_turno_vira_notificacao_e_o_jarvis_segue_pelo_subagente(
    executor: ExecutorDeFerramentas, pagina: PaginaDoWhatsApp
) -> None:
    """a17: o prazo do turno acaba enquanto o Jarvis pensa; ele recebe o limite e decide seguir —
    o passo vai ao subagente e a conversa fica livre."""
    relogio = [0.0]
    subagente = SubagenteDoClique("Bruno")

    def roteiro(contexto: Contexto) -> Sequence[Parte]:
        if NOTA_DO_LIMITE_DO_TURNO in contexto.sistema:
            return [
                "Demorou aqui, sigo em segundo plano. ",
                PedidoDeTool("browser.inspecionar", {}),
            ]
        if not _resultados(contexto) and relogio[0] == 0.0:
            relogio[0] = 1000.0  # pensar estourou o prazo do turno
            return ["Hum, deixa eu pensar."]
        return subagente(contexto)

    publicados: list[dict[str, Any]] = []
    resposta = _cerebro(
        executor, MotorRoteirizado(resposta=roteiro), relogio=lambda: relogio[0]
    ).responder("clica na conversa do Bruno", epoch=0, publicar=publicados.append)

    assert resposta.limite_do_turno and resposta.tarefa_id
    assert "sigo em segundo plano" in _falado(publicados)
    tarefa = _tarefa(executor, resposta.tarefa_id)
    assert tarefa.resposta == "Abri a conversa do Bruno." and pagina.aberta == "Bruno"


def test_d_max_turns_do_claude_code_volta_com_o_estado_e_o_jarvis_decide(
    tmp_path: Path, sem_extensao: ExecutorDeFerramentas
) -> None:
    """a19: o Claude Code esgota os turnos; o Jarvis recebe o que ele fez (os parciais) e o
    limite, e decide perguntar ao dono — sem «falhou» dito pelo código."""
    executor = sem_extensao
    delegador, _pasta = _delegador(tmp_path, "max_turnos")
    executor.delegacao = delegador
    pergunta = "O Claude achou a conversa da Ana mas parou no limite; quer que ele continue?"
    vistos: list[dict[str, Any]] = []

    def roteiro(contexto: Contexto) -> Sequence[Parte]:
        feitos = _resultados(contexto)
        if not feitos:
            return [PedidoDeTool("delegar.claude_code", _pedido_formulado())]
        vistos.append(feitos[-1])
        return [pergunta]

    resposta = _cerebro(executor, MotorRoteirizado(resposta=roteiro)).responder(
        FALA_DA_DELEGACAO, epoch=0, publicar=lambda _p: None
    )
    tarefa = _tarefa(executor, resposta.tarefa_id)

    resultado = vistos[0]
    assert resultado["tool_id"] == "delegar.claude_code"
    assert "falhou" not in str(resultado.get("motivo", ""))
    dados = resultado["dados"]
    assert dados["codigo"] == "claude_code_limite_de_turnos" and dados["feito"] is False
    assert dados["o_que_fez"][0] == "o subagente disse: Achei a conversa da Ana."
    assert dados["limite"]["turnos_permitidos"] == 7
    assert tarefa.resposta == pergunta


# --- (e) delegação: o pedido é formulado e a resposta vem depois do retorno ----------------------
FALA_DA_DELEGACAO = "pede pro Claude ver o horário de amanhã na clinica.example"


def _pedido_formulado() -> dict[str, Any]:
    return {
        "tarefa": "Abrir a página de horários da clinica.example e ler o horário de amanhã",
        "contexto": "o dono quer saber a que horas é o atendimento amanhã",
        "passos": ["abrir a página de horários", "ler a linha de amanhã"],
        "pronto_quando": "o horário de amanhã foi lido na página",
        "devolver": "o horário de amanhã, como está na página",
    }


def test_e_delegacao_formula_o_pedido_e_responde_so_depois_do_retorno(
    tmp_path: Path, sem_extensao: ExecutorDeFerramentas
) -> None:
    executor = sem_extensao
    delegador, pasta = _delegador(tmp_path, "limpo")
    executor.delegacao = delegador
    ordem: list[str] = []
    recusas: list[str] = []

    def roteiro(contexto: Contexto) -> Sequence[Parte]:
        feitos = _resultados(contexto)
        if not feitos:
            # Primeiro, a cópia preguiçosa da fala do dono: o código a recusa e devolve ao motor.
            ordem.append("copia")
            copia = _pedido_formulado() | {"tarefa": FALA_DA_DELEGACAO}
            return [PedidoDeTool("delegar.claude_code", copia)]
        ultimo = feitos[-1]
        if ultimo["tool_id"] == "delegar.claude_code" and ultimo["status"] != "ok":
            recusas.append(str(ultimo.get("motivo", "")))
            ordem.append("formulado")
            return [PedidoDeTool("delegar.claude_code", _pedido_formulado())]
        ordem.append("resposta")
        horario = re.search(r"\b\d{1,2}h\b", json.dumps(ultimo, ensure_ascii=False))
        assert horario, "a resposta usa o que o subagente devolveu"
        return [f"Amanhã o atendimento é às {horario.group(0)}."]

    publicados: list[dict[str, Any]] = []
    resposta = _cerebro(executor, MotorRoteirizado(resposta=roteiro)).responder(
        FALA_DA_DELEGACAO, epoch=0, publicar=publicados.append
    )
    falado_no_turno = _falado(publicados)
    tarefa = _tarefa(executor, resposta.tarefa_id)

    assert falado_no_turno == "", "nada é dito ao dono antes do retorno do subagente"
    assert ordem == ["copia", "formulado", "resposta"], recusas
    (registro,) = _registros(pasta)[-1:]
    entrada = str(registro["entrada"])
    assert entrada.startswith("OBJETIVO: Abrir a página de horários")
    assert FALA_DA_DELEGACAO not in entrada, "o subagente recebe o pedido formulado"
    assert "PRONTO QUANDO" in entrada and "DEVOLVA" in entrada
    assert tarefa.resposta == "Amanhã o atendimento é às 14h."
    assert recusas == [RECUSA_DE_COPIA], "a cópia da fala voltou ao motor para ele formular"


# --- a conversa segue enquanto o subagente trabalha, uma resposta por estímulo -----------------
def test_e_a_conversa_segue_livre_enquanto_o_subagente_trabalha(
    executor: ExecutorDeFerramentas, pagina: PaginaDoWhatsApp
) -> None:
    liberar = threading.Event()
    subagente = SubagenteDoClique("Bruno")

    def roteiro(contexto: Contexto) -> Sequence[Parte]:
        if contexto.turno == "que horas são?":
            return ["São dez horas."]
        if _resultados(contexto):
            assert liberar.wait(ESPERA_S)
        return subagente(contexto)

    cerebro = _cerebro(executor, MotorRoteirizado(resposta=roteiro))
    primeiro = cerebro.responder("clica na conversa do Bruno", epoch=0, publicar=lambda _p: None)
    publicados: list[dict[str, Any]] = []
    comeco = time.monotonic()
    segundo = cerebro.responder("que horas são?", epoch=1, publicar=publicados.append)
    assert time.monotonic() - comeco < 5.0, "o turno novo não espera o subagente"
    assert _falado(publicados) == "São dez horas.", "uma resposta, e só uma, ao estímulo novo"
    assert not segundo.tarefa_id
    liberar.set()
    assert _tarefa(executor, primeiro.tarefa_id).resposta == "Abri a conversa do Bruno."
