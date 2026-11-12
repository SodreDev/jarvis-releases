"""A resposta no modo ausente (ADR-0060, fatia D): quem dispara, quantas vezes, e quando não."""

from __future__ import annotations

import threading
from pathlib import Path

from jarvis.social.ausente import RespostaAusente, Resultado
from jarvis.social.envio import (
    AjusteDoEnvio,
    EnvioRecusado,
    Guardiao,
    HistoricoDeEnvios,
    Pausas,
    PedidoDeEnvio,
    Permitido,
)
from jarvis.social.monitor import ConversaNaoLida, EstadoDaPagina
from tests.unit.social.test_envio import MEIO_DIA

ANA = Permitido("Ana Souza", "+55 11 98888-7777")


class EnviadorFalso:
    def __init__(self) -> None:
        self.enviados: list[PedidoDeEnvio] = []

    def enviar(self, pedido: PedidoDeEnvio) -> str:
        self.enviados.append(pedido)
        return "enviado"


def _montar(
    tmp_path: Path, ajuste: AjusteDoEnvio, redator: object = "padrão"
) -> tuple[RespostaAusente, EnviadorFalso, list[Resultado], threading.Event, list[str]]:
    pedidos_ao_redator: list[str] = []
    resultados: list[Resultado] = []
    chegou = threading.Event()

    def ao_resultado(resultado: Resultado) -> None:
        resultados.append(resultado)
        chegou.set()

    def redigir(nome: str) -> str:
        pedidos_ao_redator.append(nome)
        return f"Oi, {nome.split()[0]}! Ele está fora e responde à tarde."

    enviador = EnviadorFalso()
    resposta = RespostaAusente(
        guardiao=Guardiao(
            ajuste=lambda: ajuste,
            historico=HistoricoDeEnvios(tmp_path / "envios.jsonl"),
            pausas=Pausas(tmp_path / "pausas.json"),
            relogio=lambda: MEIO_DIA,
        ),
        enviador=enviador,  # type: ignore[arg-type]
        redator=redigir if redator == "padrão" else None,
        permitidos=lambda: ajuste.permitidos,
        ao_resultado=ao_resultado,
    )
    return resposta, enviador, resultados, chegou, pedidos_ao_redator


def _pagina(*conversas: tuple[str, int]) -> EstadoDaPagina:
    return EstadoDaPagina(
        "whatsapp",
        logado=True,
        nao_lidas=sum(n for _, n in conversas),
        conversas=tuple(ConversaNaoLida(nome, n) for nome, n in conversas),
    )


LIGADO = AjusteDoEnvio(automatico=True, ausente=True, permitidos=(ANA,))


def test_contato_da_lista_com_nao_lida_recebe_uma_resposta_so(tmp_path: Path) -> None:
    resposta, enviador, resultados, chegou, _ = _montar(tmp_path, LIGADO)
    resposta.ao_estado(_pagina(("Ana Souza", 1), ("Desconhecido", 3)))
    assert chegou.wait(3)
    resposta.ao_estado(_pagina(("Ana Souza", 2)))  # mais uma da Ana, sem ler: não responde de novo
    resposta.parar()
    assert resposta._fio is not None
    resposta._fio.join(3)
    assert [p.nome for p in enviador.enviados] == ["Ana Souza"]
    assert enviador.enviados[0].telefone == ANA.telefone, "o telefone vem da lista, não da página"
    assert resultados == [Resultado("Ana Souza", True)]


def test_depois_de_lida_a_proxima_mensagem_pode_ser_respondida(tmp_path: Path) -> None:
    resposta, enviador, _, chegou, _ = _montar(tmp_path, LIGADO)
    resposta.ao_estado(_pagina(("Ana Souza", 1)))
    assert chegou.wait(3)
    chegou.clear()
    resposta.ao_estado(_pagina())  # leu
    resposta.ao_estado(_pagina(("Ana Souza", 1)))
    assert chegou.wait(3)
    assert len(enviador.enviados) == 2


def test_sem_ausente_nem_redator_o_motor_nem_e_chamado(tmp_path: Path) -> None:
    presente = AjusteDoEnvio(automatico=True, ausente=False, permitidos=(ANA,))
    resposta, enviador, resultados, chegou, redator = _montar(tmp_path, presente)
    resposta.ao_estado(_pagina(("Ana Souza", 1)))
    assert chegou.wait(3)
    assert enviador.enviados == [] and redator == []
    assert not resultados[0].enviado and "ausente" in resultados[0].motivo

    resposta, enviador, resultados, chegou, _ = _montar(tmp_path / "b", LIGADO, redator=None)
    resposta.ao_estado(_pagina(("Ana Souza", 1)))
    assert chegou.wait(3)
    assert enviador.enviados == [] and "fechada" in resultados[0].motivo


def test_pagina_com_alerta_ou_deslogada_nao_dispara(tmp_path: Path) -> None:
    resposta, enviador, _, chegou, _ = _montar(tmp_path, LIGADO)
    com_alerta = EstadoDaPagina(
        "whatsapp", True, 1, (ConversaNaoLida("Ana Souza", 1),), alerta="captcha"
    )
    resposta.ao_estado(com_alerta)
    resposta.ao_estado(EstadoDaPagina("whatsapp", False, 1, (ConversaNaoLida("Ana Souza", 1),)))
    resposta.ao_estado(EstadoDaPagina("discord", True, 1, (ConversaNaoLida("Ana Souza", 1),)))
    assert not chegou.wait(0.3)
    assert enviador.enviados == []


def test_recusa_do_envio_vira_resultado_para_o_dono(tmp_path: Path) -> None:
    resposta, enviador, resultados, chegou, _ = _montar(tmp_path, LIGADO)

    def recusar(pedido: PedidoDeEnvio) -> str:
        raise EnvioRecusado("contato_divergente", "o chat aberto não é o do contato")

    enviador.enviar = recusar  # type: ignore[method-assign]
    resposta.ao_estado(_pagina(("Ana Souza", 1)))
    assert chegou.wait(3)
    assert resultados == [Resultado("Ana Souza", False, "o chat aberto não é o do contato")]
