"""ADR-0059: a tarefa de um pedido chega ao teto, pergunta ao dono, e ele decide.

Sem rede nem áudio: motor roteirizado e a pendência de sempre. Cada passo é uma leitura de pasta,
que roda sem pedir o sim; a única pergunta ao dono nestes testes é a do teto.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.executor.ferramentas import Confirmacao, ExecutorDeFerramentas
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.s2.pendencias import Pendencia, RegistroDePendencias
from jarvis.s2.tarefa_do_pedido import NOTA_DO_TETO
from jarvis.tarefas.gestor import TOOL_DO_TETO, EstadoDaTarefa, GestorDeTarefas, Tarefa
from jarvis.tarefas.laco import GuardaDeLaco

BLOCO = 3
NO_TURNO = 2
"""Os passos que cabem no turno antes de delegar (ADR-0046): o primeiro bloco os desconta."""
PRIMEIRA_PARADA = BLOCO - NO_TURNO
SEGUNDA_PARADA = PRIMEIRA_PARADA + BLOCO
PEDIDO = "organize a pasta de documentos"


@pytest.fixture
def executor(tmp_path: Path) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    (lar / "Documentos").mkdir(parents=True)
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
        # Sem a guarda de laço (ADR-0062): cada passo relê a mesma pasta vazia, que é laço; aqui
        # o assunto é o teto.
        executor.tarefas = GestorDeTarefas(
            executor=executor, confirmar=lambda _p, _c: False, guarda_de_laco=None
        )
        yield executor
        executor.tarefas.encerrar()


class Roteiro:
    """Pede passos até `passos` e então responde; sem ferramentas na mão, conta o que fez."""

    def __init__(self, passos: int = 1000, resumo: str = "Li a pasta, faltou organizar.") -> None:
        self.passos = passos
        self.resumo = resumo
        self.chamadas = 0

    def __call__(self, contexto: Contexto) -> Sequence[Parte]:
        if NOTA_DO_TETO in contexto.sistema:
            assert not contexto.ferramentas, "o resumo do teto é sem ferramentas"
            return [self.resumo] if self.resumo else [PedidoDeTool("files.list_dir", {})]
        self.chamadas += 1
        if self.chamadas > self.passos:
            return ["Organizei a pasta."]
        return [PedidoDeTool("files.list_dir", {"path": "~/Documentos"})]


def _comecar(
    executor: ExecutorDeFerramentas, roteiro: Roteiro, **extra: Any
) -> tuple[Cerebro, Tarefa]:
    cerebro = Cerebro(
        motor=MotorRoteirizado(resposta=roteiro),
        ferramentas=executor,
        delegar_em_tarefa=True,
        pendencia_sem_portao=True,
        maximo_de_passos=BLOCO,
        **extra,
    )
    resposta = cerebro.responder(PEDIDO, epoch=0, publicar=lambda _p: None)
    assert executor.tarefas is not None and resposta.tarefa_id
    return cerebro, executor.tarefas.tarefas[resposta.tarefa_id]


def _pergunta(cerebro: Cerebro, anterior: str = "") -> Pendencia:
    """Espera a pergunta aberta (outra que não a `anterior`) e a dá por ouvida, como a voz faria."""
    limite = time.monotonic() + 10.0
    while time.monotonic() < limite:
        aberta = cerebro.pendencias.valida()
        if aberta is not None and aberta.id != anterior:
            cerebro.pendencias.marcar_ouvida(aberta.id)
            return aberta
        time.sleep(0.01)
    raise AssertionError("a pergunta do teto não abriu")


def _fim(executor: ExecutorDeFerramentas, tarefa: Tarefa) -> Tarefa:
    assert executor.tarefas is not None
    assert executor.tarefas.esperar(tarefa.id, 10.0), "a tarefa não terminou"
    return tarefa


def _dizer(cerebro: Cerebro, fala: str) -> str:
    return cerebro.responder(fala, epoch=1, publicar=lambda _p: None).gerado


def test_no_teto_a_tarefa_para_e_pergunta_com_a_conversa_livre(
    executor: ExecutorDeFerramentas,
) -> None:
    roteiro = Roteiro()
    cerebro, tarefa = _comecar(executor, roteiro)

    pergunta = _pergunta(cerebro).pergunta

    assert pergunta.tool_id == TOOL_DO_TETO and pergunta.continuar_por == BLOCO
    assert tarefa.estado is EstadoDaTarefa.ESPERANDO_O_DONO
    assert pergunta.pergunta_falada.startswith(f"Posso continuar por mais {BLOCO} passos")
    assert "até terminar" in pergunta.pergunta_falada
    assert pergunta.pergunta_falada.endswith("ainda falta.")
    assert "tarefa.continuar" not in pergunta.pergunta_falada
    assert f"Já dei {BLOCO} passos" in pergunta.pergunta_falada, "os do turno contam"
    assert tarefa.passo == PRIMEIRA_PARADA
    assert _dizer(cerebro, "não") == "Tudo bem, paro por aqui."
    _fim(executor, tarefa)


def test_sim_da_mais_um_bloco_e_pergunta_de_novo(executor: ExecutorDeFerramentas) -> None:
    cerebro, tarefa = _comecar(executor, Roteiro())
    primeira = _pergunta(cerebro)

    assert _dizer(cerebro, "sim, pode seguir") == "Certo."

    segunda = _pergunta(cerebro, anterior=primeira.id)
    assert tarefa.passo == SEGUNDA_PARADA
    _dizer(cerebro, "não")
    assert segunda.pergunta.continuar_por == BLOCO
    _fim(executor, tarefa)


def test_mais_50_dito_vale_como_mais_um_bloco(executor: ExecutorDeFerramentas) -> None:
    cerebro, tarefa = _comecar(executor, Roteiro())
    primeira = _pergunta(cerebro)

    _dizer(cerebro, f"mais {BLOCO}")

    _pergunta(cerebro, anterior=primeira.id)
    assert tarefa.passo == SEGUNDA_PARADA
    _dizer(cerebro, "não")
    _fim(executor, tarefa)


def test_ate_terminar_nao_pergunta_mais_e_a_tarefa_acaba_sozinha(
    executor: ExecutorDeFerramentas,
) -> None:
    cerebro, tarefa = _comecar(executor, Roteiro(passos=4 * BLOCO))
    _pergunta(cerebro)

    assert _dizer(cerebro, "até terminar") == "Certo."

    _fim(executor, tarefa)
    assert tarefa.estado is EstadoDaTarefa.CONCLUIDA
    assert tarefa.resposta == "Organizei a pasta."
    assert cerebro.pendencias.valida() is None
    assert tarefa.passo > SEGUNDA_PARADA


def test_o_clique_em_sim_da_mais_um_bloco(executor: ExecutorDeFerramentas) -> None:
    cerebro, tarefa = _comecar(executor, Roteiro())
    primeira = _pergunta(cerebro)

    assert cerebro.resolver_pendencia(primeira.id, True)

    _pergunta(cerebro, anterior=primeira.id)
    assert tarefa.passo == SEGUNDA_PARADA
    segunda = cerebro.pendencias.valida()
    assert segunda is not None and cerebro.resolver_pendencia(segunda.id, False)
    _fim(executor, tarefa)


def test_nao_encerra_com_o_resumo_do_que_foi_feito(executor: ExecutorDeFerramentas) -> None:
    cerebro, tarefa = _comecar(executor, Roteiro())
    _pergunta(cerebro)

    _dizer(cerebro, "não")

    _fim(executor, tarefa)
    assert tarefa.estado is EstadoDaTarefa.FALHOU
    assert tarefa.resposta == "Parei sem terminar. Li a pasta, faltou organizar."
    assert tarefa.aviso != "", "o resumo vai à voz: o dono pediu para ouvir o que foi feito"


def test_sem_resposta_tambem_encerra_com_o_resumo(executor: ExecutorDeFerramentas) -> None:
    agora = [1000.0]
    cerebro, tarefa = _comecar(
        executor, Roteiro(), pendencias=RegistroDePendencias(relogio=lambda: agora[0])
    )
    _pergunta(cerebro)

    agora[0] += 121.0  # os 120 s da pergunta

    _fim(executor, tarefa)
    assert tarefa.estado is EstadoDaTarefa.FALHOU
    assert tarefa.resposta.startswith("Parei sem terminar.")


def test_o_motor_que_nao_resume_nao_deixa_o_dono_sem_resumo(
    executor: ExecutorDeFerramentas,
) -> None:
    """Pediu outra ferramenta em vez de contar: o resumo é do código, sem nome de ferramenta."""
    cerebro, tarefa = _comecar(executor, Roteiro(resumo=""))
    _pergunta(cerebro)

    _dizer(cerebro, "não")

    _fim(executor, tarefa)
    assert tarefa.resposta.startswith("Parei sem terminar, depois de")
    assert "deram certo" in tarefa.resposta and "files." not in tarefa.resposta


def test_o_fim_exato_no_teto_nao_pergunta(executor: ExecutorDeFerramentas) -> None:
    """A tarefa que acabaria ali não incomoda o dono: a pergunta só vem com outro passo na mão."""
    cerebro, tarefa = _comecar(executor, Roteiro(passos=BLOCO))

    _fim(executor, tarefa)

    assert tarefa.estado is EstadoDaTarefa.CONCLUIDA
    assert cerebro.pendencias.valida() is None


def test_cancelar_com_a_pergunta_aberta_cancela_a_tarefa(executor: ExecutorDeFerramentas) -> None:
    cerebro, tarefa = _comecar(executor, Roteiro())
    _pergunta(cerebro)
    assert executor.tarefas is not None

    executor.tarefas.cancelar(tarefa.id)

    _fim(executor, tarefa)
    assert tarefa.estado is EstadoDaTarefa.CANCELADA
    assert cerebro.pendencias.valida() is None


def test_com_outra_pergunta_aberta_a_do_teto_espera_a_vez(executor: ExecutorDeFerramentas) -> None:
    pendencias = RegistroDePendencias()
    outra = Confirmacao("outra", "files.list_dir", "Outra", "outra coisa", "", 60.0)

    class AbreOutra(Roteiro):
        """Outra pergunta abre já com a tarefa rodando: a do turno que a criou a teria cancelado."""

        def __call__(self, contexto: Contexto) -> Sequence[Parte]:
            if self.chamadas == NO_TURNO:
                pendencias.abrir(outra)
            return super().__call__(contexto)

    cerebro, tarefa = _comecar(executor, AbreOutra(), pendencias=pendencias)

    limite = time.monotonic() + 10.0
    while tarefa.estado is not EstadoDaTarefa.ESPERANDO_O_DONO and time.monotonic() < limite:
        time.sleep(0.01)
    aberta = pendencias.valida()
    assert aberta is not None and aberta.id == "outra" and not tarefa.estado.final

    pendencias.cancelar()

    assert _pergunta(cerebro, anterior="outra").pergunta.tool_id == TOOL_DO_TETO
    _dizer(cerebro, "não")
    _fim(executor, tarefa)


def test_o_prazo_do_bloco_tambem_pergunta_e_o_do_turno_nao_vale_para_a_tarefa(
    executor: ExecutorDeFerramentas,
) -> None:
    cerebro, tarefa = _comecar(
        executor, Roteiro(), prazo_da_tarefa_s=1e-9, prazo_do_laco_de_ferramentas_s=90.0
    )

    pergunta = _pergunta(cerebro).pergunta

    assert "O tempo acabou" in pergunta.pergunta_falada
    assert tarefa.passo == 0
    _dizer(cerebro, "não")
    _fim(executor, tarefa)
    assert tarefa.estado is EstadoDaTarefa.FALHOU and tarefa.resposta.startswith("Parei")


def test_com_a_guarda_o_laco_avisa_o_motor_e_para_sem_perguntar(
    executor: ExecutorDeFerramentas,
) -> None:
    """ADR-0062: reler a mesma pasta vazia é laço. A nota vai ao motor uma vez; se ele insiste, a
    tarefa acaba com o resumo, sem a pergunta do teto."""
    assert executor.tarefas is not None
    executor.tarefas.guarda_de_laco = GuardaDeLaco
    executor.tarefas.passos_por_bloco = 50
    vistos: list[str] = []

    class Espiao(Roteiro):
        def __call__(self, contexto: Contexto) -> Sequence[Parte]:
            vistos.append(contexto.sistema)
            return super().__call__(contexto)

    cerebro = Cerebro(
        motor=MotorRoteirizado(resposta=Espiao()),
        ferramentas=executor,
        delegar_em_tarefa=True,
        pendencia_sem_portao=True,
        maximo_de_passos=50,
    )
    resposta = cerebro.responder(PEDIDO, epoch=0, publicar=lambda _p: None)
    tarefa = _fim(executor, executor.tarefas.tarefas[resposta.tarefa_id])

    assert sum("LAÇO" in s for s in vistos) == 1, "a nota vai uma vez, no passo seguinte"
    assert tarefa.estado is EstadoDaTarefa.FALHOU
    assert tarefa.resposta.startswith("Parei sem terminar: eu estava repetindo")
    assert "Li a pasta, faltou organizar." in tarefa.resposta
    assert cerebro.pendencias.valida() is None, "o laço não vira pergunta"
