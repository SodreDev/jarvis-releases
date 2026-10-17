"""ADR-0025, regra 13: o `s2` decide a entrega e diz o aviso antes da resposta."""

from __future__ import annotations

from typing import Any

from jarvis.agentd.fala_em_stream import avisos_tocados, falar_stream_para
from jarvis.agentd.tts import MotorParametrico, SintetizadorEmStreaming
from jarvis.s2.avisos import AvisoLiberado, decidir_entrega, frase_do_aviso
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor_roteirizado import MotorRoteirizado

TAREFA = AvisoLiberado("n1", "concluida", "tarefa · pesquisa", "a pesquisa de passagens terminou")
DECISAO = AvisoLiberado(
    "n2", "precisa_decisao", "mcp · arquivos", "o servidor pede um formulário", de_terceiros=True
)


def test_pedido_de_decisao_nunca_e_calado_e_resposta_estranha_vira_card() -> None:
    decisoes = decidir_entrega([TAREFA, DECISAO], julgar=lambda a: "calado")
    assert decisoes == {"n1": "calado", "n2": "so_card"}
    assert decidir_entrega([TAREFA], julgar=lambda a: "gritar") == {"n1": "so_card"}


def test_frase_de_terceiros_diz_de_quem_e_e_termina_em_ponto() -> None:
    frase = frase_do_aviso(DECISAO)
    assert frase.startswith("Aviso de mcp · arquivos:")
    assert frase.endswith("confirmar.")
    assert "*" not in frase
    assert frase_do_aviso(TAREFA) == "Aviso: a pesquisa de passagens terminou."


def test_o_aviso_vai_antes_da_resposta_e_o_motor_sabe_que_foi_dito() -> None:
    motor = MotorRoteirizado(resposta="Amanhã vai fazer sol o dia inteiro.")
    cerebro = Cerebro(motor=motor)
    publicados: list[dict[str, Any]] = []

    cerebro.responder("vai chover amanhã?", epoch=0, publicar=publicados.append, avisos=[TAREFA])

    com_aviso = [p for p in publicados if p.get("notif_ids")]
    sem_aviso = [p for p in publicados if not p.get("notif_ids")]
    assert " ".join(p["text"] for p in com_aviso) == frase_do_aviso(TAREFA)
    assert publicados[: len(com_aviso)] == com_aviso, "o aviso vem primeiro"
    assert "sol" in " ".join(p["text"] for p in sem_aviso)
    assert "pesquisa de passagens" in motor.pedidos[0].sistema
    assert publicados[-1]["last"]


def test_com_piso_livre_o_aviso_sai_sozinho_sem_chamar_o_motor() -> None:
    motor = MotorRoteirizado()
    cerebro = Cerebro(motor=motor)
    publicados: list[dict[str, Any]] = []

    resposta = cerebro.avisar([TAREFA, DECISAO], epoch=0, publicar=publicados.append)

    assert motor.pedidos == []
    assert {n for p in publicados for n in p.get("notif_ids", [])} == {"n1", "n2"}
    assert publicados[-1]["last"]
    assert not resposta.cancelada


def test_cancelado_durante_o_aviso_o_motor_nem_e_chamado() -> None:
    motor = MotorRoteirizado()
    cerebro = Cerebro(motor=motor)
    resposta = cerebro.responder(
        "oi", epoch=0, publicar=lambda _: None, cancelado=lambda: True, avisos=[TAREFA]
    )
    assert resposta.cancelada
    assert motor.pedidos == [], "o motor não pode gerar depois do cancelamento"


def test_entregue_e_o_aviso_que_tocou_inteiro() -> None:
    """Regra 15: cortado no meio do aviso, ele volta; tocado inteiro, conta como entregue."""
    cerebro = Cerebro(motor=MotorRoteirizado(resposta="Tudo certo por aqui, nada mais."))
    publicados: list[dict[str, Any]] = []
    cerebro.responder("e aí?", epoch=0, publicar=publicados.append, avisos=[TAREFA, DECISAO])
    sintese = SintetizadorEmStreaming(motor=MotorParametrico(), session_id="s", epoch=0)
    fala = falar_stream_para(sintese, publicados, lambda _p: True)

    ultimo_do_primeiro = max(
        i
        for i, p in enumerate(p for p in publicados if p["text"])
        if "n1" in p.get("notif_ids", [])
    )
    no_meio_do_segundo = fala.trechos[ultimo_do_primeiro + 1].inicio_em_amostras + 10
    assert avisos_tocados(publicados, fala, no_meio_do_segundo, epoch=0) == ({"n1"}, {"n2"})
    assert avisos_tocados(publicados, fala, fala.amostras_sintetizadas, epoch=0) == (
        {"n1", "n2"},
        set(),
    )
    assert avisos_tocados(publicados, fala, 0, epoch=0) == (set(), {"n1", "n2"})
