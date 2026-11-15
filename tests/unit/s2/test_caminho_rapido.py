"""O caminho rápido no cérebro virou DICA (ADR-0045; ADR-0070, dono, 2026-11-15).

A regra do código ainda reconhece o comando simples, mas não executa nem fala: diz ao motor qual
ferramenta e quais argumentos ela acharia, como contexto, e o motor decide. O que se prova aqui,
com a máquina falsa dos testes de fechar e encerrar: a dica chega ao motor e nada roda antes dele;
o motor que segue a dica executa pelo caminho de sempre (PDP, pergunta ao dono); encerrar o editor
ainda pede o sim; o que não cabe numa regra vai ao motor sem dica; e desligado, sem dica.
"""

from __future__ import annotations

import json
import re
import signal
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.executor.ferramentas import Confirmacao, ExecutorDeFerramentas
from jarvis.executor.lancador import App, RegistroDeApps
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.trilha import TrilhaDeDiagnostico, eventos_do_ultimo_turno
from tests.unit.executor.test_fechar_e_encerrar import CATALOGO, _id, _ligar

LIBERADOS = ("discord", "steam", "org.kde.kate")


@pytest.fixture
def lancados() -> list[str]:
    return []


@pytest.fixture
def executor(tmp_path: Path, lancados: list[str]) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    lar.mkdir()
    autorizados = {i: CATALOGO[i] for i in LIBERADOS}

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
        executor = ExecutorDeFerramentas(
            pdp=pdp,
            lar=lar,
            registro_de_apps=RegistroDeApps(
                autorizados=autorizados, instalados=frozenset(CATALOGO), catalogo=CATALOGO
            ),
            lancar_app=lancar,
            trilha=TrilhaDeDiagnostico(tmp_path / "trilha"),
        )
        executor.preparar()
        yield executor


def _cerebro(
    executor: ExecutorDeFerramentas,
    motor: MotorRoteirizado,
    *,
    perguntas: list[Confirmacao] | None = None,
    ligado: bool = True,
) -> Cerebro:
    def confirmar(pergunta: Confirmacao) -> bool:
        if perguntas is not None:
            perguntas.append(pergunta)
        return False

    assert executor.trilha is not None
    executor.trilha.novo_turno("t-01a16100-0000-7000-8000-000000000001", motor="teste")
    return Cerebro(motor=motor, ferramentas=executor, confirmar=confirmar, caminho_rapido=ligado)


class SegueADica:
    """O motor de teste que faz o que um modelo bem-comportado faria com a dica: propõe a
    ferramenta sugerida e, com o resultado na mão, responde."""

    def __init__(self, fim: str = "Feito.") -> None:
        self.fim = fim

    def __call__(self, contexto: Contexto) -> list[Parte]:
        if any(m.papel == "ferramenta" for m in contexto.mensagens):
            return [self.fim]
        achado = re.search(r"parece ser (\S+) com (\{.*?\})\. Use", contexto.sistema)
        assert achado is not None, "a dica não chegou ao motor"
        return [PedidoDeTool(achado.group(1), json.loads(achado.group(2)))]


def _dica(motor: MotorRoteirizado) -> str:
    return motor.pedidos[0].sistema if motor.pedidos else ""


def test_a_regra_vira_dica_e_nada_roda_nem_fala_antes_do_motor(
    executor: ExecutorDeFerramentas, lancados: list[str], tmp_path: Path
) -> None:
    _ligar(executor)
    motor = MotorRoteirizado(resposta="Prefiro perguntar antes: qual Discord?")

    resposta = _cerebro(executor, motor).responder(
        "Jarvis, abre o Discord", epoch=1, publicar=lambda _: None
    )

    assert lancados == [], "a regra não executa: o motor decidiu outra coisa"
    assert "DICA DO CÓDIGO" in _dica(motor) and "apps.launch" in _dica(motor)
    assert resposta.atalho == "abrir_app" and resposta.motor_chamado
    assert resposta.gerado == "Prefiro perguntar antes: qual Discord?", "nenhuma frase do código"
    (evento,) = [e for e in eventos_do_ultimo_turno(tmp_path / "trilha") if e["evento"] == "atalho"]
    assert evento["regra"] == "abrir_app" and evento["tool_id"] == "apps.launch"
    assert evento["status"] == "dica"
    assert "Discord" not in str(evento), "só metadados: nem a fala nem o argumento"


def test_seguindo_a_dica_o_motor_abre_o_app_pelo_caminho_de_sempre(
    executor: ExecutorDeFerramentas, lancados: list[str]
) -> None:
    _ligar(executor)
    motor = MotorRoteirizado(resposta=SegueADica("Abri o Discord pra você."))

    resposta = _cerebro(executor, motor).responder(
        "Jarvis, abre o Discord", epoch=1, publicar=lambda _: None
    )

    assert lancados == ["discord"]
    assert resposta.ferramentas[0].tool_id == "apps.launch", "pela proposta do motor, não da regra"


def test_fecha_o_discord_pela_dica_fecha_so_a_janela(executor: ExecutorDeFerramentas) -> None:
    tabela, janelas = _ligar(executor)
    motor = MotorRoteirizado(resposta=SegueADica("Fechei a janela."))

    _cerebro(executor, motor).responder("fecha o discord", epoch=1, publicar=lambda _: None)

    assert janelas.fechadas == [_id(2)] and tabela.sinais == []


def test_mata_o_discord_pela_dica_encerra_o_app(executor: ExecutorDeFerramentas) -> None:
    tabela, _janelas = _ligar(executor)
    motor = MotorRoteirizado(resposta=SegueADica("Pronto."))

    _cerebro(executor, motor).responder("mata o discord", epoch=1, publicar=lambda _: None)

    assert tabela.sinais == [(700, signal.SIGTERM)]


def test_encerrar_o_editor_pela_dica_ainda_pede_o_sim_e_sem_ele_nada_recebe_sinal(
    executor: ExecutorDeFerramentas,
) -> None:
    """A dica não atropela a confirmação: o «sim» vem do alvo (ADR-0042) e o PDP o cobra igual —
    aqui o dono diz não, e o motor recebe o resultado para explicar."""
    tabela, janelas = _ligar(executor)
    janelas.janelas = [
        replace(j, titulo="notas.md * — Kate") if j.classe == "org.kde.kate" else j
        for j in janelas.janelas
    ]
    perguntas: list[Confirmacao] = []
    motor = MotorRoteirizado(resposta=SegueADica("Tudo bem, não encerrei o Kate."))

    resposta = _cerebro(executor, motor, perguntas=perguntas).responder(
        "fecha o kate todo", epoch=1, publicar=lambda _: None
    )

    assert perguntas and "trabalho por salvar" in perguntas[0].razao_falada
    assert tabela.sinais == [], "sem o sim, nada recebe sinal"
    assert resposta.ferramentas[0].status == "negado"
    assert "Tudo bem, não encerrei o Kate." in resposta.gerado


def test_o_erro_da_ferramenta_que_o_motor_escolheu_volta_a_ele(
    executor: ExecutorDeFerramentas,
) -> None:
    _ligar(executor)
    motor = MotorRoteirizado(resposta=SegueADica("O Spotify não está aberto."))

    resposta = _cerebro(executor, motor).responder(
        "fecha o spotify", epoch=1, publicar=lambda _: None
    )

    assert resposta.atalho == "fechar_janela" and resposta.motor_chamado
    assert resposta.ferramentas[0].status == "negado"
    assert any(m.papel == "ferramenta" for m in motor.pedidos[-1].mensagens)
    assert "O Spotify não está aberto." in resposta.gerado


@pytest.mark.parametrize(
    "fala",
    [
        "abre o diário",  # não resolve para app liberado
        "abre o discord e manda um oi pra ana",  # composto
        "roda o discord no terminal",  # o método (pede_terminal) tira o apps.launch do turno
    ],
)
def test_o_que_nao_cabe_numa_regra_vai_ao_motor(
    executor: ExecutorDeFerramentas, lancados: list[str], fala: str
) -> None:
    _ligar(executor)
    motor = MotorRoteirizado(resposta="Certo.")

    resposta = _cerebro(executor, motor).responder(fala, epoch=1, publicar=lambda _: None)

    assert resposta.atalho == "" and len(motor.pedidos) == 1 and lancados == []


def test_desligado_tudo_vai_ao_motor_como_antes(
    executor: ExecutorDeFerramentas, lancados: list[str]
) -> None:
    _ligar(executor)
    vistos: list[Contexto] = []

    def roteiro(contexto: Contexto) -> str:
        vistos.append(contexto)
        return "Abrindo."

    resposta = _cerebro(executor, MotorRoteirizado(resposta=roteiro), ligado=False).responder(
        "abre o Discord", epoch=1, publicar=lambda _: None
    )

    assert resposta.atalho == "" and len(vistos) == 1 and lancados == []


def test_fechar_o_navegador_a_pedido_pela_dica_fecha_sem_perguntar(
    executor: ExecutorDeFerramentas,
) -> None:
    """«Fecha meu Firefox» é ordem explícita do dono: fecha, sem o sim (dono, 2026-10-25)."""
    _tabela, janelas = _ligar(executor)
    perguntas: list[Confirmacao] = []
    motor = MotorRoteirizado(resposta=SegueADica("Fechei o Firefox."))

    resposta = _cerebro(executor, motor, perguntas=perguntas).responder(
        "fecha meu firefox", epoch=1, publicar=lambda _: None
    )

    assert resposta.atalho == "fechar_janela" and not perguntas
    assert janelas.fechadas == [_id(6)]


def test_fechar_o_navegador_sem_nome_a_dica_resolve_pelo_que_esta_aberto(
    executor: ExecutorDeFerramentas,
) -> None:
    _tabela, janelas = _ligar(executor)
    motor = MotorRoteirizado(resposta=SegueADica("Fechei."))

    _cerebro(executor, motor).responder(
        "Jarvis, fecha o navegador", epoch=1, publicar=lambda _: None
    )

    assert janelas.fechadas == [_id(6)]
