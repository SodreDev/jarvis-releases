"""Uma resposta por pedido (dono, 2026-10-25; ADR-0046): o pedido de um passo responde no turno.

O relato do dono: todo pedido virava tarefa com subagente e, quando ela acabava, o Jarvis
respondia de novo — a resposta dele e mais uma. Aqui, com o motor roteirizado propondo a ferramenta
(o caminho rápido desligado: é o caso em que a regra não pegou a fala) e a máquina falsa dos testes
de fechar e encerrar:

- a ação de um passo roda no turno e o dono ouve o resultado **uma vez** — a frase do código, ou o
  "vou abrir" do motor, nunca os dois — e o motor não é chamado de novo para dizer "pronto";
- o aviso de uma moderada fecha o pedido simples do mesmo jeito;
- pedido composto segue com o motor, e a frase dele que só repete o já dito vai à tela, não à voz;
- nenhuma tarefa nasce para isso.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.executor.ferramentas import ExecutorDeFerramentas
from jarvis.executor.lancador import App, RegistroDeApps
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.tarefas.gestor import GestorDeTarefas
from tests.unit.executor.test_fechar_e_encerrar import CATALOGO, _ligar

LIBERADOS = ("discord", "steam", "org.kde.kate")


@pytest.fixture
def lancados() -> list[str]:
    return []


@pytest.fixture
def executor(tmp_path: Path, lancados: list[str]) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    lar.mkdir()

    def lancar(app: App) -> int:
        lancados.append(app.id)
        return 4242

    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
            apps_autorizados=frozenset(LIBERADOS),
        )
        ex = ExecutorDeFerramentas(
            pdp=pdp,
            lar=lar,
            registro_de_apps=RegistroDeApps(
                autorizados={i: CATALOGO[i] for i in LIBERADOS},
                instalados=frozenset(CATALOGO),
                catalogo=CATALOGO,
            ),
            lancar_app=lancar,
        )
        ex.preparar()
        ex.tarefas = GestorDeTarefas(executor=ex, confirmar=lambda _p, _c: False)
        yield ex
        ex.tarefas.encerrar()


def _feitas(contexto: Contexto) -> int:
    return sum(m.papel == "ferramenta" for m in contexto.mensagens)


def _cerebro(executor: ExecutorDeFerramentas, motor: MotorRoteirizado) -> Cerebro:
    # O caminho rápido desligado: quem propõe é o motor, como na fala que a regra não pega.
    return Cerebro(motor=motor, ferramentas=executor, delegar_em_tarefa=True)


def _falado(publicados: Sequence[dict[str, Any]]) -> str:
    return " ".join(str(p["text"]) for p in publicados if p["text"])


def test_abrir_um_app_pelo_motor_responde_uma_vez_e_sem_tarefa(
    executor: ExecutorDeFerramentas, lancados: list[str]
) -> None:
    _ligar(executor)

    def roteiro(contexto: Contexto) -> Sequence[Parte]:
        if _feitas(contexto) == 0:
            return [PedidoDeTool("apps.launch", {"nome": "discord"})]
        return ["Pronto, abri o Discord pra você."]  # o "pronto" de novo: não pode ser ouvido

    motor = MotorRoteirizado(resposta=roteiro)
    publicados: list[dict[str, Any]] = []

    resposta = _cerebro(executor, motor).responder(
        "Jarvis, abre aquele Discord", epoch=1, publicar=publicados.append
    )

    assert lancados == ["discord"]
    assert _falado(publicados) == "Abrindo o Discord.", "uma frase só, a do código, já"
    assert len(motor.pedidos) == 1, "o motor não é chamado de novo para dizer «pronto»"
    assert not resposta.tarefa_id
    assert executor.tarefas is not None
    # A única tarefa é a que acompanha o foco da janela que vai abrir (ADR-0037), não o pedido.
    assert [t.motor for t in executor.tarefas.tarefas.values()] == ["foco"]


def test_o_vou_abrir_do_motor_ja_diz_e_a_frase_do_codigo_nao_repete(
    executor: ExecutorDeFerramentas, lancados: list[str]
) -> None:
    _ligar(executor)
    motor = MotorRoteirizado(
        resposta=lambda c: (
            ["Vou abrir o Discord. ", PedidoDeTool("apps.launch", {"nome": "discord"})]
            if _feitas(c) == 0
            else ["Abri o Discord."]
        )
    )
    publicados: list[dict[str, Any]] = []

    _cerebro(executor, motor).responder("abre o discord aí", epoch=1, publicar=publicados.append)

    assert lancados == ["discord"]
    assert _falado(publicados) == "Vou abrir o Discord."
    assert len(motor.pedidos) == 1


def test_o_aviso_da_moderada_fecha_o_pedido_simples(executor: ExecutorDeFerramentas) -> None:
    tabela, _janelas = _ligar(executor)
    motor = MotorRoteirizado(
        resposta=lambda c: (
            [PedidoDeTool("apps.quit", {"app": "discord"})]
            if _feitas(c) == 0
            else ["O Discord foi encerrado."]
        )
    )
    publicados: list[dict[str, Any]] = []

    _cerebro(executor, motor).responder(
        "acaba com esse discord de vez", epoch=1, publicar=publicados.append
    )

    assert tabela.sinais, "o Discord recebeu o sinal"
    assert _falado(publicados) == "Encerrei o Discord."
    assert len(motor.pedidos) == 1


def test_pedido_composto_segue_com_o_motor_e_a_repeticao_fica_na_tela(
    executor: ExecutorDeFerramentas, lancados: list[str]
) -> None:
    _ligar(executor)

    def roteiro(contexto: Contexto) -> Sequence[Parte]:
        feitas = _feitas(contexto)
        if feitas == 0:
            return [PedidoDeTool("apps.launch", {"nome": "discord"})]
        if feitas == 1:
            return [PedidoDeTool("apps.launch", {"nome": "steam"})]
        return ["Pronto, abri o Discord e o Steam."]

    motor = MotorRoteirizado(resposta=roteiro)
    publicados: list[dict[str, Any]] = []

    resposta = _cerebro(executor, motor).responder(
        "abre o discord e o steam", epoch=1, publicar=publicados.append
    )

    assert lancados == ["discord", "steam"], "dois passos cabem no turno"
    assert _falado(publicados) == "Abrindo o Discord. Abrindo o Steam."
    assert resposta.caladas == ["Pronto, abri o Discord e o Steam."]
    assert "Pronto, abri o Discord e o Steam." in resposta.gerado, "a tela mostra"
    assert not resposta.tarefa_id


def test_a_resposta_com_algo_novo_depois_da_acao_e_dita(
    executor: ExecutorDeFerramentas, lancados: list[str]
) -> None:
    """O filtro cala a repetição, nunca a novidade: a pergunta de seguimento passa."""
    _ligar(executor)
    motor = MotorRoteirizado(
        resposta=lambda c: (
            [PedidoDeTool("apps.launch", {"nome": "discord"})]
            if _feitas(c) == 0
            else ["Abri o Discord. Quer que eu entre no servidor do trabalho?"]
        )
    )
    publicados: list[dict[str, Any]] = []

    _cerebro(executor, motor).responder(
        "abre o discord, por favor", epoch=1, publicar=publicados.append
    )

    assert _falado(publicados) == ("Abrindo o Discord. Quer que eu entre no servidor do trabalho?")
    assert len(motor.pedidos) == 2, "a fala com vírgula não é simples: o motor segue"


def test_o_terceiro_passo_e_trabalho_longo_e_vai_para_a_tarefa(
    executor: ExecutorDeFerramentas, lancados: list[str]
) -> None:
    _ligar(executor)

    def roteiro(contexto: Contexto) -> Sequence[Parte]:
        feitas = _feitas(contexto)
        if feitas < 2:
            return [PedidoDeTool("apps.launch", {"nome": ("discord", "steam")[feitas]})]
        if feitas == 2:
            return [PedidoDeTool("window.list", {})]
        return ["Abri os dois; agora há três janelas."]

    motor = MotorRoteirizado(resposta=roteiro)
    publicados: list[dict[str, Any]] = []

    resposta = _cerebro(executor, motor).responder(
        "abre o discord, o steam e me diz as janelas", epoch=1, publicar=publicados.append
    )

    assert resposta.tarefa_id, "o terceiro passo passou do teto do turno"
    assert executor.tarefas is not None
    assert executor.tarefas.esperar(resposta.tarefa_id, 10.0)
    assert lancados == ["discord", "steam"]
    tarefa = executor.tarefas.tarefas[resposta.tarefa_id]
    assert tarefa.passo == 1 and tarefa.resposta == "Abri os dois; agora há três janelas."
    # O fim da tarefa sabe o que o dono já ouviu no turno: não repete.
    assert tarefa.ja_dito == "Abrindo o Discord. Abrindo o Steam."
