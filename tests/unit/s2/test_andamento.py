"""ADR-0070: o progresso do subagente volta ao Jarvis como evento, e ele decide o que contar."""

from __future__ import annotations

from jarvis.s2.cerebro import PASSOS_NO_ANDAMENTO, Cerebro, fica_no_turno
from jarvis.s2.motor_roteirizado import MotorRoteirizado


def test_o_progresso_do_subagente_vai_ao_turno_do_jarvis_como_nota() -> None:
    motor = MotorRoteirizado(resposta="Ainda estou abrindo a conversa da Ana.")
    cerebro = Cerebro(motor=motor)
    for passo in range(PASSOS_NO_ANDAMENTO + 2):
        cerebro.anotar_progresso("t-1", "manda oi pra Ana", f"browser.read → ok ({passo})")

    cerebro.responder("e aí, já foi?", epoch=0, publicar=lambda _p: None)

    sistema = motor.pedidos[0].sistema
    assert "SUBAGENTES EM ANDAMENTO" in sistema and "«manda oi pra Ana»" in sistema
    assert f"({PASSOS_NO_ANDAMENTO + 1})" in sistema and "(0)" not in sistema, "só os últimos"

    cerebro.esquecer_andamento("t-1")
    assert cerebro.nota_do_andamento() == ""


def test_so_as_consultas_do_proprio_jarvis_ficam_no_turno() -> None:
    for propria in ("system.clock.now", "memoria.apagar", "window.list", "tela.mostrar"):
        assert fica_no_turno(propria), propria
    for execucao in (
        "browser.click",
        "apps.launch",
        "web.buscar",
        "script.rodar",
        "files.list_dir",
    ):
        assert not fica_no_turno(execucao), execucao
    assert not fica_no_turno("delegar.claude_code"), "a delegação não pode prender a voz"
