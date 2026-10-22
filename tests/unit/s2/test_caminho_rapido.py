"""O caminho rápido no cérebro (dono, 2026-10-21: «precisa ser muito rápido»; ADR-0045).

O comando simples vai à ferramenta pela regra do código — **pelo mesmo `_chamar`** da proposta do
modelo, então o PDP e a pergunta ao dono continuam valendo — e, pronto e certo, a frase é do
código: o motor nem é chamado. O que se prova aqui, com a máquina falsa dos testes de fechar e
encerrar (processos e janelas de mentira, sinais gravados): abrir, fechar e encerrar um app
liberado sem o motor; encerrar o editor ainda pede o sim (e sem o sim nada recebe sinal); erro e
pedido que não cabe numa regra vão ao motor, que recebe o resultado; o método do pedido manda; e
desligado, tudo como antes.
"""

from __future__ import annotations

import signal
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.executor.ferramentas import Confirmacao, ExecutorDeFerramentas
from jarvis.executor.lancador import App, RegistroDeApps
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import Contexto
from jarvis.s2.motor_roteirizado import MotorRoteirizado
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


def test_abre_o_app_liberado_sem_chamar_o_motor(
    executor: ExecutorDeFerramentas, lancados: list[str], tmp_path: Path
) -> None:
    _ligar(executor)
    motor = MotorRoteirizado(resposta="o motor não devia falar")

    resposta = _cerebro(executor, motor).responder(
        "Jarvis, abre o Discord", epoch=1, publicar=lambda _: None
    )

    assert lancados == ["discord"]
    assert motor.pedidos == [], "o motor nem foi chamado"
    assert resposta.atalho == "abrir_app" and not resposta.motor_chamado
    assert resposta.gerado == "Abrindo o Discord."
    (evento,) = [e for e in eventos_do_ultimo_turno(tmp_path / "trilha") if e["evento"] == "atalho"]
    assert evento["regra"] == "abrir_app" and evento["tool_id"] == "apps.launch"
    assert evento["status"] == "ok" and evento["completo"] is True
    assert "Discord" not in str(evento), "só metadados: nem a fala nem o argumento"


def test_fecha_o_discord_fecha_so_a_janela_e_fala_do_codigo(
    executor: ExecutorDeFerramentas,
) -> None:
    tabela, janelas = _ligar(executor)
    motor = MotorRoteirizado(resposta="o motor não devia falar")

    resposta = _cerebro(executor, motor).responder(
        "fecha o discord", epoch=1, publicar=lambda _: None
    )

    assert janelas.fechadas == [_id(2)] and tabela.sinais == []
    assert motor.pedidos == [] and resposta.gerado == "Fechei a janela do Discord."


def test_encerrar_o_discord_fala_so_o_aviso_da_moderada(executor: ExecutorDeFerramentas) -> None:
    tabela, _janelas = _ligar(executor)
    motor = MotorRoteirizado(resposta="o motor não devia falar")

    resposta = _cerebro(executor, motor).responder(
        "mata o discord", epoch=1, publicar=lambda _: None
    )

    assert tabela.sinais == [(700, signal.SIGTERM)]
    assert motor.pedidos == []
    assert resposta.gerado.strip() == "Encerrei o Discord.", "o aviso diz; nada repetido"


def test_encerrar_o_editor_pela_regra_ainda_pede_o_sim_e_sem_ele_nada_recebe_sinal(
    executor: ExecutorDeFerramentas,
) -> None:
    """O caminho rápido não atropela a confirmação: o «sim» vem do alvo (ADR-0042) e o PDP o
    cobra igual — aqui o dono diz não, e o motor recebe o resultado para explicar."""
    tabela, _janelas = _ligar(executor)
    perguntas: list[Confirmacao] = []
    motor = MotorRoteirizado(resposta="Tudo bem, não encerrei o Kate.")

    resposta = _cerebro(executor, motor, perguntas=perguntas).responder(
        "fecha o kate todo", epoch=1, publicar=lambda _: None
    )

    assert perguntas and "trabalho não salvo" in perguntas[0].razao_falada
    assert tabela.sinais == [], "sem o sim, nada recebe sinal"
    assert resposta.ferramentas[0].status == "negado"
    assert len(motor.pedidos) == 1, "o motor segue, com o resultado na mão"
    assert any(m.papel == "ferramenta" for m in motor.pedidos[0].mensagens)
    assert resposta.gerado == "Tudo bem, não encerrei o Kate."


def test_erro_da_ferramenta_vai_ao_motor_com_o_resultado(executor: ExecutorDeFerramentas) -> None:
    _ligar(executor)
    motor = MotorRoteirizado(resposta="O Spotify não está aberto.")

    resposta = _cerebro(executor, motor).responder(
        "fecha o spotify", epoch=1, publicar=lambda _: None
    )

    assert resposta.atalho == "fechar_janela" and resposta.motor_chamado
    assert resposta.ferramentas[0].status == "negado"
    (pedido,) = motor.pedidos
    assert "O primeiro passo deste pedido o código já fez" in pedido.sistema
    assert any(m.papel == "ferramenta" for m in pedido.mensagens)


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
