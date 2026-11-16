"""Comando simples sem caminho rápido (ADR-0045 → ADR-0070 → ADR-0072, dono, 2026-11-16).

O caminho rápido foi regra, depois dica, e saiu: a fala do STT não vira parâmetro nem dispara
função. «Abre o Discord», «fecha o Kate todo» vão ao modelo como qualquer mensagem; ele escolhe a
ferramenta e os argumentos, e o código só valida (PDP, a pergunta do que é destrutivo) e executa.
O que se prova aqui, com a máquina falsa dos testes de fechar e encerrar: nada roda nem fala antes
do modelo e nenhuma «dica» tirada da fala chega a ele; o que ele propõe roda pelo caminho de
sempre; encerrar o editor com trabalho por salvar ainda pede o sim; o erro volta a ele.
"""

from __future__ import annotations

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
) -> Cerebro:
    def confirmar(pergunta: Confirmacao) -> bool:
        if perguntas is not None:
            perguntas.append(pergunta)
        return False

    assert executor.trilha is not None
    executor.trilha.novo_turno("t-01a16100-0000-7000-8000-000000000001", motor="teste")
    return Cerebro(motor=motor, ferramentas=executor, confirmar=confirmar)


class Propoe:
    """O motor de teste que decide como um modelo decidiria: propõe a ferramenta e, com o
    resultado na mão, responde."""

    def __init__(self, pedido: PedidoDeTool, fim: str = "Feito.") -> None:
        self.pedido = pedido
        self.fim = fim

    def __call__(self, contexto: Contexto) -> list[Parte]:
        if any(m.papel == "ferramenta" for m in contexto.mensagens):
            return [self.fim]
        return [self.pedido]


@pytest.mark.parametrize("fala", ["Jarvis, abre o Discord", "fecha o discord", "mata o discord"])
def test_nada_roda_nem_fala_antes_do_modelo_e_nenhuma_dica_sai_da_fala(
    executor: ExecutorDeFerramentas, lancados: list[str], tmp_path: Path, fala: str
) -> None:
    tabela, janelas = _ligar(executor)
    motor = MotorRoteirizado(resposta="Prefiro perguntar antes: qual Discord?")

    resposta = _cerebro(executor, motor).responder(fala, epoch=1, publicar=lambda _: None)

    assert lancados == [] and janelas.fechadas == [] and tabela.sinais == []
    # A dica do atalho trazia ferramenta E argumentos tirados da fala («parece ser apps.launch
    # com {"nome": ...}»); o roteador de método (que só lembra o caminho) continua.
    assert "parece ser" not in motor.pedidos[0].sistema
    assert resposta.atalho == "" and resposta.motor_chamado and len(motor.pedidos) == 1
    assert resposta.gerado == "Prefiro perguntar antes: qual Discord?", "nenhuma frase do código"
    eventos = eventos_do_ultimo_turno(tmp_path / "trilha")
    assert not [e for e in eventos if e["evento"] == "atalho"]


def test_o_modelo_abre_o_app_pelo_caminho_de_sempre(
    executor: ExecutorDeFerramentas, lancados: list[str]
) -> None:
    _ligar(executor)
    motor = MotorRoteirizado(
        resposta=Propoe(PedidoDeTool("apps.launch", {"nome": "discord"}), "Abri o Discord.")
    )

    resposta = _cerebro(executor, motor).responder(
        "Jarvis, abre o Discord", epoch=1, publicar=lambda _: None
    )

    assert lancados == ["discord"]
    assert resposta.ferramentas[0].tool_id == "apps.launch"
    assert dict(resposta.ferramentas[0].argumentos) == {"nome": "discord"}


def test_fecha_o_discord_fecha_so_a_janela(executor: ExecutorDeFerramentas) -> None:
    tabela, janelas = _ligar(executor)
    motor = MotorRoteirizado(
        resposta=Propoe(PedidoDeTool("window.close", {"app": "discord"}), "Fechei a janela.")
    )

    _cerebro(executor, motor).responder("fecha o discord", epoch=1, publicar=lambda _: None)

    assert janelas.fechadas == [_id(2)] and tabela.sinais == []


def test_mata_o_discord_encerra_o_app(executor: ExecutorDeFerramentas) -> None:
    tabela, _janelas = _ligar(executor)
    motor = MotorRoteirizado(resposta=Propoe(PedidoDeTool("apps.quit", {"app": "discord"})))

    _cerebro(executor, motor).responder("mata o discord", epoch=1, publicar=lambda _: None)

    assert tabela.sinais == [(700, signal.SIGTERM)]


def test_encerrar_o_editor_ainda_pede_o_sim_e_sem_ele_nada_recebe_sinal(
    executor: ExecutorDeFerramentas,
) -> None:
    """O «sim» vem do alvo (ADR-0042) e o PDP o cobra: aqui o dono diz não, e o motor recebe o
    resultado para explicar."""
    tabela, janelas = _ligar(executor)
    janelas.janelas = [
        replace(j, titulo="notas.md * — Kate") if j.classe == "org.kde.kate" else j
        for j in janelas.janelas
    ]
    perguntas: list[Confirmacao] = []
    motor = MotorRoteirizado(
        resposta=Propoe(
            PedidoDeTool("apps.quit", {"app": "kate"}), "Tudo bem, não encerrei o Kate."
        )
    )

    resposta = _cerebro(executor, motor, perguntas=perguntas).responder(
        "fecha o kate todo", epoch=1, publicar=lambda _: None
    )

    assert perguntas and "trabalho por salvar" in perguntas[0].razao_falada
    assert tabela.sinais == [], "sem o sim, nada recebe sinal"
    assert resposta.ferramentas[0].status == "negado"
    assert "Tudo bem, não encerrei o Kate." in resposta.gerado


def test_o_erro_da_ferramenta_que_o_modelo_escolheu_volta_a_ele(
    executor: ExecutorDeFerramentas,
) -> None:
    _ligar(executor)
    motor = MotorRoteirizado(
        resposta=Propoe(
            PedidoDeTool("window.close", {"app": "spotify"}), "O Spotify não está aberto."
        )
    )

    resposta = _cerebro(executor, motor).responder(
        "fecha o spotify", epoch=1, publicar=lambda _: None
    )

    assert resposta.ferramentas[0].status == "negado"
    assert any(m.papel == "ferramenta" for m in motor.pedidos[-1].mensagens)
    assert "O Spotify não está aberto." in resposta.gerado


def test_fechar_o_navegador_a_pedido_fecha_sem_perguntar(
    executor: ExecutorDeFerramentas,
) -> None:
    """«Fecha meu Firefox» é ordem explícita do dono: fecha, sem o sim (dono, 2026-10-25)."""
    _tabela, janelas = _ligar(executor)
    perguntas: list[Confirmacao] = []
    motor = MotorRoteirizado(
        resposta=Propoe(PedidoDeTool("window.close", {"app": "firefox"}), "Fechei o Firefox.")
    )

    _cerebro(executor, motor, perguntas=perguntas).responder(
        "fecha meu firefox", epoch=1, publicar=lambda _: None
    )

    assert not perguntas
    assert janelas.fechadas == [_id(6)]
