"""O texto da resposta automática (ADR-0060, fatia D) vem do motor, curto, ou não vem."""

from __future__ import annotations

from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.social.redator import LIMITE, NAO_ENVIAR, redigir


def test_o_motor_redige_com_as_memorias_no_sistema() -> None:
    motor = MotorRoteirizado(resposta="«Oi, Ana! Ele volta à tarde.»")
    assert redigir(motor, "Ana", "- [instrução] tom: curto") == "Oi, Ana! Ele volta à tarde."
    sistema = motor.pedidos[0].sistema
    assert "tom: curto" in sistema and "nunca fale de dinheiro" in sistema


def test_recusa_falha_ou_texto_longo_nao_viram_envio() -> None:
    assert redigir(MotorRoteirizado(resposta=NAO_ENVIAR), "Ana", "") == ""
    assert redigir(MotorRoteirizado(resposta="x" * (LIMITE + 1)), "Ana", "") == ""
    assert redigir(MotorRoteirizado(resposta=""), "Ana", "") == ""
