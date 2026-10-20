"""O pedido vira objetivo com critério, estado e fase (dono, 2026-10-20, Lote C, C2; ADR-0030).

Integra o objetivo do Lote B (item 4) em vez de duplicar: o mesmo `Objetivo` ganha o critério de
pronto (pelo método do pedido, ADR-0035), o estado, a fase e os passos feitos (só ferramenta e
status); o Jev os recebe junto da chamada — na nuvem sem o texto do pedido de novo (D20) —, e a
tarefa em segundo plano tem o objetivo dela, que o PDP usa nas chamadas dela.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from jarvis.decisao.fake import ClassificadorFalso
from jarvis.decisao.interface import Pergunta, Resposta, RespostaEscolha, RespostaNoul
from jarvis.executor.desfazer import Contaminacao
from jarvis.executor.ferramentas import Avaliacao, ExecutorDeFerramentas
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.objetivo import EstadoDoObjetivo, Fase, Objetivo
from jarvis.politica.pdp import Pdp, Veredito
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.s2.portao import PortaoDeAcao
from jarvis.tarefas.gestor import Tarefa
from jarvis.tarefas.motores import MotorDeAgente
from jarvis.voz.interface import Onde


# --- o objetivo ----------------------------------------------------------------------------------
def test_o_criterio_de_pronto_vem_do_metodo_do_pedido() -> None:
    assert (
        "página pedida aberta e conferida" in Objetivo.do_pedido("abre o yt", "navegador").criterio
    )
    assert Objetivo.do_pedido("abre o spotify", "app").criterio == "o app aberto e em foco"
    assert "respondido" in Objetivo.do_pedido("qual a capital?").criterio


def _fase(objetivo: Objetivo) -> Fase:
    """Lida de novo a cada vez: `registrar` muda a fase (o mypy não sabe disso)."""
    return objetivo.fase


def test_as_fases_seguem_os_passos_e_ler_depois_de_agir_e_verificar() -> None:
    objetivo = Objetivo.do_pedido("abre o canal do primo rico no youtube", "navegador")
    assert (objetivo.fase, objetivo.estado) == (Fase.PLANEJANDO, EstadoDoObjetivo.ABERTO)

    objetivo.registrar("web.buscar", "ok", leitura=True)  # ler antes de agir: ainda executa
    assert (objetivo.fase, objetivo.estado) == (Fase.EXECUTANDO, EstadoDoObjetivo.EM_ANDAMENTO)
    objetivo.registrar("browser.navigate", "ok", leitura=False)
    objetivo.registrar("browser.read", "ok", leitura=True)
    assert _fase(objetivo) is Fase.VERIFICANDO
    objetivo.registrar("browser.click", "ok", leitura=False)
    assert _fase(objetivo) is Fase.EXECUTANDO
    objetivo.concluir(EstadoDoObjetivo.CONCLUIDO)
    assert (_fase(objetivo), objetivo.estado) == (Fase.CONCLUINDO, EstadoDoObjetivo.CONCLUIDO)
    assert objetivo.passos[-1] == ("browser.click", "ok") and objetivo.total_de_passos == 4


def test_a_pergunta_ao_dono_deixa_o_objetivo_esperando_por_ele() -> None:
    objetivo = Objetivo.do_pedido("apaga o arquivo velho")
    objetivo.registrar("files.move_to_trash", "pendente", leitura=False)
    objetivo.concluir(EstadoDoObjetivo.CONCLUIDO)
    assert objetivo.estado is EstadoDoObjetivo.AGUARDANDO_O_DONO


def test_ao_classificador_vai_o_contexto_e_na_nuvem_sem_o_texto_do_pedido() -> None:
    objetivo = Objetivo.do_pedido("abre o youtube, minha senha é hunter2hunter2", "navegador")
    objetivo.registrar("browser.navigate", "ok", leitura=False)

    local = objetivo.para_o_classificador(na_nuvem=False)
    nuvem = objetivo.para_o_classificador(na_nuvem=True)

    assert local["fase"] == "executando" and local["passos_feitos"] == ["browser.navigate:ok"]
    assert "hunter2" not in local["objetivo"]  # o texto do objetivo é redigido
    assert "objetivo" not in nuvem and nuvem["criterio_de_pronto"] == local["criterio_de_pronto"]


# --- o portão (Jev) recebe o objetivo e a fase ---------------------------------------------------
def _jev(onde: Onde = Onde.LOCAL) -> ClassificadorFalso:
    def roteiro(_estado: Any, perguntas: Mapping[str, Pergunta]) -> Mapping[str, Resposta]:
        return {
            "acao": RespostaEscolha("fazer", 0.95, {"fazer": 0.95}),
            "pedido_explicito": RespostaNoul(0.0),
        }

    jev = ClassificadorFalso(roteiro=roteiro)
    jev.onde = onde
    return jev


@pytest.mark.parametrize("onde", [Onde.LOCAL, Onde.NUVEM])
def test_o_jev_recebe_o_pedido_o_objetivo_os_passos_e_a_fase(onde: Onde) -> None:
    objetivo = Objetivo.do_pedido("abre o canal do primo rico no youtube", "navegador")
    objetivo.registrar("browser.navigate", "ok", leitura=False)
    objetivo.registrar("browser.read", "ok", leitura=True)
    jev = _jev(onde)

    PortaoDeAcao(classificador=jev).classificar(
        tool_id="browser.click",
        titulo="Clicar",
        argumentos={"alvo": "O Primo Rico"},
        pedido_do_dono="abre o canal do primo rico no youtube",
        mensagens=(),
        situacao={"modo_de_acesso": "padrao"},
        objetivo=objetivo,
    )

    estado, perguntas = jev.chamadas[0]
    assert estado["objetivo"]["fase"] == "verificando"
    assert estado["objetivo"]["passos_feitos"] == ["browser.navigate:ok", "browser.read:ok"]
    assert "primo rico" in estado["pedido_do_dono"]
    assert ("objetivo" in estado["objetivo"]) is (onde is Onde.LOCAL)
    assert "verificando" in json.dumps(perguntas, ensure_ascii=False) or "acao" in perguntas


# --- o executor: passos, fase e o objetivo próprio da tarefa ------------------------------------
@pytest.fixture
def executor(tmp_path: Path) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    (lar / "Documentos").mkdir(parents=True)
    (lar / "Documentos" / "nota.txt").write_text("comprar café\n", "utf-8")
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
        )
        executor = ExecutorDeFerramentas(pdp=pdp, lar=lar)
        executor.preparar()
        yield executor


def test_cada_chamada_concluida_vira_passo_do_objetivo_do_turno(
    executor: ExecutorDeFerramentas,
) -> None:
    executor.novo_turno("o que tem na minha nota?")
    executor.executar("files.read_text", {"path": "~/Documentos/nota.txt"}, cancelado=lambda: False)
    assert executor.objetivo is not None
    assert executor.objetivo.passos == [("files.read_text", "ok")]
    assert executor.objetivo.fase is Fase.EXECUTANDO


def test_a_tarefa_segue_o_objetivo_dela_e_nao_o_do_turno(executor: ExecutorDeFerramentas) -> None:
    """Depois de ler conteúdo de terceiros, abrir site fora do objetivo pergunta (ADR-0030). O
    objetivo que conta é o de quem chama: o turno pediu o Gmail; a tarefa, o YouTube."""
    executor.novo_turno("abre o gmail")
    executor.turno.valor = True  # o turno leu uma página
    da_tarefa = Contaminacao(True, Objetivo.do_pedido("acha o canal do primo rico no youtube"))

    pelo_turno = executor.avaliar("sites.open", {"url": "https://www.youtube.com/"})
    pela_tarefa = executor.avaliar(
        "sites.open", {"url": "https://www.youtube.com/"}, contaminacao=da_tarefa
    )

    assert isinstance(pelo_turno, Avaliacao) and isinstance(pela_tarefa, Avaliacao)
    assert pelo_turno.decisao.veredito is Veredito.CONFIRM
    assert pela_tarefa.decisao.veredito is not Veredito.CONFIRM


# --- o cérebro: o estado com que o objetivo termina o turno -------------------------------------
def _cerebro(executor: ExecutorDeFerramentas, *rodadas: list[Parte]) -> Cerebro:
    def resposta(contexto: Contexto) -> list[Parte]:
        feitas = sum(1 for m in contexto.mensagens if m.papel == "ferramenta")
        return rodadas[min(feitas, len(rodadas) - 1)]

    return Cerebro(motor=MotorRoteirizado(resposta=resposta), ferramentas=executor)


def test_o_turno_termina_dizendo_como_ficou_o_objetivo(executor: ExecutorDeFerramentas) -> None:
    ler = PedidoDeTool("files.read_text", {"path": "~/Documentos/nota.txt"})
    pronto = _cerebro(executor, [ler], ["Tem comprar café."]).responder(
        "o que tem na minha nota?", epoch=0, publicar=lambda _: None
    )
    sem_fim = _cerebro(executor, [ler]).responder(
        "lê a nota sem parar", epoch=1, publicar=lambda _: None
    )
    interrompido = _cerebro(executor, ["Vou ver."]).responder(
        "lê a nota", epoch=2, publicar=lambda _: None, cancelado=lambda: True
    )

    assert pronto.estado_do_objetivo == "concluido"
    assert sem_fim.estado_do_objetivo == "falhou"  # teto de passos sem resposta
    assert interrompido.estado_do_objetivo == "cancelado"


# --- a tarefa em segundo plano -------------------------------------------------------------------
def test_o_agente_da_tarefa_ve_o_criterio_a_fase_e_os_passos() -> None:
    motor = MotorRoteirizado(resposta="Terminei.")
    agente = MotorDeAgente(motor=motor, catalogo=lambda: [])
    objetivo = Objetivo.do_pedido("lista os vídeos novos do canal")
    objetivo.registrar("web.canal_videos", "ok", leitura=True)
    tarefa = Tarefa(
        id="t-1",
        descricao="lista os vídeos novos do canal",
        tool_id="web.canal_videos",
        parametros={"canal": "@primorico"},
        motor="agente",
        contaminacao=Contaminacao(False, objetivo),
    )

    agente.proximo(tarefa, [], lambda: False)

    pedido = motor.pedidos[0].mensagens[0].texto
    assert "Critério de pronto:" in pedido and "Fase: executando" in pedido
    assert "web.canal_videos:ok" in pedido and "até o critério estar cumprido" in pedido
    assert tarefa.para_o_modelo()["fase"] == "executando"
