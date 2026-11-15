"""Uma resposta por pedido (dono, 2026-10-25; ADR-0046): o pedido de um passo responde no turno.

O relato do dono: todo pedido virava tarefa com subagente e, quando ela acabava, o Jarvis
respondia de novo — a resposta dele e mais uma. Aqui, com o motor roteirizado propondo a ferramenta
(o caminho rápido desligado: é o caso em que a regra não pegou a fala) e a máquina falsa dos testes
de fechar e encerrar:

- a ação roda no turno (o laço todo no turno, sem o subagente: o que o harness usa; com o
  subagente ligado, a execução vai a ele — ADR-0070) e o dono ouve o resultado **uma vez**, na
  fala do motor: sem frase do código depois da ação, e sem o código encerrar o turno;
- o aviso de uma moderada vai ao motor como dado, e a fala é dele;
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


def _cerebro(
    executor: ExecutorDeFerramentas, motor: MotorRoteirizado, *, subagente: bool = False
) -> Cerebro:
    # O caminho rápido desligado: quem propõe é o motor, como na fala que a regra não pega. Estes
    # testes são do laço NO TURNO (sem o subagente); com ele ligado — a produção, ADR-0070 —, toda
    # execução vai ao subagente desde o primeiro passo.
    return Cerebro(motor=motor, ferramentas=executor, delegar_em_tarefa=subagente)


def _falado(publicados: Sequence[dict[str, Any]]) -> str:
    return " ".join(str(p["text"]) for p in publicados if p["text"])


def test_abrir_um_app_pelo_motor_ele_responde_uma_vez_e_sem_tarefa(
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
    assert _falado(publicados) == "Pronto, abri o Discord pra você.", "uma fala só, a do motor"
    assert len(motor.pedidos) == 2, "o motor vê o resultado e decide o que dizer"
    assert not resposta.tarefa_id
    assert executor.tarefas is not None
    # A única tarefa é a que acompanha o foco da janela que vai abrir (ADR-0037), não o pedido.
    assert [t.motor for t in executor.tarefas.tarefas.values()] == ["foco"]


def test_o_vou_abrir_do_motor_ja_diz_e_nao_ha_frase_do_codigo(
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
    assert _falado(publicados).startswith("Vou abrir o Discord.")
    assert "Abrindo o Discord" not in _falado(publicados), "nenhuma frase do código"
    assert len(motor.pedidos) == 2


def test_o_aviso_da_moderada_vai_ao_motor_como_dado(executor: ExecutorDeFerramentas) -> None:
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
    assert "«Encerrei o Discord.»" in motor.pedidos[-1].sistema, "o aviso foi ao motor como dado"
    assert _falado(publicados) == "O Discord foi encerrado."


def test_pedido_composto_segue_com_o_motor_e_ele_fala_uma_vez(
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
    assert _falado(publicados) == "Pronto, abri o Discord e o Steam."
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

    assert _falado(publicados) == "Abri o Discord. Quer que eu entre no servidor do trabalho?"
    assert len(motor.pedidos) == 2


def test_com_o_subagente_todo_o_pedido_composto_vai_a_uma_tarefa(
    executor: ExecutorDeFerramentas, lancados: list[str]
) -> None:
    _ligar(executor)

    def roteiro(contexto: Contexto) -> Sequence[Parte]:
        feitas = _feitas(contexto)
        if feitas < 2:
            return [PedidoDeTool("apps.launch", {"nome": ("discord", "steam")[feitas]})]
        if feitas == 2:
            return [PedidoDeTool("files.list_dir", {"path": "~"})]
        return ["Abri os dois; agora há três janelas."]

    motor = MotorRoteirizado(resposta=roteiro)
    publicados: list[dict[str, Any]] = []

    resposta = _cerebro(executor, motor, subagente=True).responder(
        "abre o discord, o steam e me diz as janelas", epoch=1, publicar=publicados.append
    )

    assert resposta.tarefa_id and resposta.ferramentas == [], "nada roda no turno (ADR-0070)"
    assert executor.tarefas is not None
    assert executor.tarefas.esperar(resposta.tarefa_id, 10.0)
    assert lancados == ["discord", "steam"]
    tarefa = executor.tarefas.tarefas[resposta.tarefa_id]
    assert tarefa.passo == 3 and tarefa.resposta == "Abri os dois; agora há três janelas."
    # O fim da tarefa sabe o que o dono já ouviu no turno: não repete.
    assert tarefa.ja_dito == "", "o código não falou nada no turno (ADR-0070)"
