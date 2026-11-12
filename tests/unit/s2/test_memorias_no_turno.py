"""As memórias fixas chegam ao motor só no turno do assunto (ADR-0060, fatia C; ADR-0047)."""

from __future__ import annotations

from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.social.memorias import CABECALHO, bloco, nova

MEMORIAS = (
    nova("contato", "Ana Souza", "colega do financeiro", "+55 11 98888-7777"),
    nova("instrucao", "tom", "responda curto e diga que eu retorno à tarde"),
)


def _sistema(fala: str) -> str:
    motor = MotorRoteirizado(resposta="Ok.")
    Cerebro(motor=motor, memorias_fixas=lambda texto: bloco(texto, MEMORIAS)).responder(
        fala, epoch=0, publicar=lambda _: None
    )
    return motor.pedidos[0].sistema


def test_turno_do_assunto_leva_o_bloco_sem_telefone() -> None:
    sistema = _sistema("se a Ana mandar mensagem no whatsapp, responde por mim")
    assert CABECALHO in sistema
    assert "Ana Souza: colega do financeiro" in sistema
    assert "retorno à tarde" in sistema
    assert "98888" not in sistema


def test_turno_de_outro_assunto_nao_paga_o_bloco() -> None:
    assert CABECALHO not in _sistema("que horas são?")


def test_memoria_que_falha_nao_derruba_o_turno() -> None:
    def quebrada(_texto: str) -> str:
        raise OSError("disco")

    motor = MotorRoteirizado(resposta="Oi.")
    Cerebro(motor=motor, memorias_fixas=quebrada).responder(
        "mensagem do whatsapp", epoch=0, publicar=lambda _: None
    )
    assert CABECALHO not in motor.pedidos[0].sistema
