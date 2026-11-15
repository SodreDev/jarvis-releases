"""ADR-0025 e ADR-0070: o aviso é um evento para o Jarvis; quem decide falar, e o quê, é o motor."""

from __future__ import annotations

from typing import Any

from jarvis.agentd.fala_em_stream import avisos_tocados, falar_stream_para
from jarvis.agentd.tts import MotorParametrico, SintetizadorEmStreaming
from jarvis.s2.avisos import (
    MARCA_DO_SILENCIO,
    AvisoLiberado,
    calado,
    decidir_entrega,
    nota_dos_eventos,
)
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import Contexto, Fim, MotivoDoFim
from jarvis.s2.motor_roteirizado import MotorRoteirizado

TAREFA = AvisoLiberado("n1", "concluida", "tarefa · pesquisa", "a pesquisa de passagens terminou")
DECISAO = AvisoLiberado(
    "n2", "precisa_decisao", "mcp · arquivos", "o servidor pede um formulário", de_terceiros=True
)


def test_pedido_de_decisao_nunca_e_calado_e_resposta_estranha_vira_card() -> None:
    decisoes = decidir_entrega([TAREFA, DECISAO], julgar=lambda a: "calado")
    assert decisoes == {"n1": "calado", "n2": "so_card"}
    assert decidir_entrega([TAREFA], julgar=lambda a: "gritar") == {"n1": "so_card"}


def test_a_nota_traz_os_eventos_como_dado_e_nenhuma_frase_pronta() -> None:
    nota = nota_dos_eventos([TAREFA, DECISAO])
    assert "EVENTOS DO SISTEMA" in nota
    assert "a pesquisa de passagens terminou" in nota
    assert "de_terceiros=sim" in nota and "tipo=precisa_decisao" in nota
    assert MARCA_DO_SILENCIO in nota
    assert "Aviso:" not in nota
    assert nota_dos_eventos([]) == ""
    assert calado("[silencio]") and calado("  [Silencio].") and calado("")
    assert not calado("A pesquisa de passagens terminou.")


def test_com_a_mensagem_do_dono_o_motor_recebe_os_eventos_e_o_codigo_nao_fala_nada_antes() -> None:
    motor = MotorRoteirizado(resposta="Amanhã vai fazer sol. Ah, a pesquisa terminou.")
    cerebro = Cerebro(motor=motor)
    publicados: list[dict[str, Any]] = []

    cerebro.responder("vai chover amanhã?", epoch=0, publicar=publicados.append, avisos=[TAREFA])

    assert not any(p.get("notif_ids") for p in publicados), "nenhuma fala do código antes"
    falado = " ".join(p["text"] for p in publicados)
    assert "sol" in falado and "pesquisa terminou" in falado
    assert "pesquisa de passagens" in motor.pedidos[0].sistema
    assert "EVENTOS DO SISTEMA" in motor.pedidos[0].sistema
    assert publicados[-1]["last"]


def test_com_piso_livre_o_jarvis_fala_com_as_palavras_dele() -> None:
    motor = MotorRoteirizado(
        resposta="Terminei a pesquisa de passagens; e o servidor quer um dado.", conta_eventos=False
    )
    cerebro = Cerebro(motor=motor)
    publicados: list[dict[str, Any]] = []

    resposta = cerebro.avisar([TAREFA, DECISAO], epoch=0, publicar=publicados.append)

    assert len(motor.pedidos) == 1
    assert "EVENTOS DO SISTEMA" in motor.pedidos[0].sistema
    assert motor.pedidos[0].ferramentas == (), "o turno de avisos não executa nada"
    assert " ".join(p["text"] for p in publicados).startswith("Terminei a pesquisa")
    assert all(p["notif_ids"] == ["n1", "n2"] for p in publicados if p["text"])
    assert publicados[-1]["last"]
    assert not resposta.cancelada and not resposta.calado
    assert cerebro.falas_de_aviso["n2"] == resposta.gerado


def test_o_jarvis_pode_decidir_nao_falar() -> None:
    cerebro = Cerebro(motor=MotorRoteirizado(resposta=MARCA_DO_SILENCIO, conta_eventos=False))
    publicados: list[dict[str, Any]] = []

    resposta = cerebro.avisar([TAREFA], epoch=0, publicar=publicados.append)

    assert resposta.calado
    assert publicados == []


def test_motor_que_cai_nao_vira_frase_do_codigo() -> None:
    def caiu(_contexto: Contexto) -> list[Any]:
        return [Fim(MotivoDoFim.ERRO, "fora do ar")]

    cerebro = Cerebro(motor=MotorRoteirizado(resposta=caiu, conta_eventos=False))
    publicados: list[dict[str, Any]] = []

    resposta = cerebro.avisar([TAREFA], epoch=0, publicar=publicados.append)

    assert resposta.calado
    assert publicados == []


def test_cancelado_antes_do_aviso_o_motor_nem_e_chamado() -> None:
    motor = MotorRoteirizado()
    cerebro = Cerebro(motor=motor)
    resposta = cerebro.avisar([TAREFA], epoch=0, publicar=lambda _: None, cancelado=lambda: True)
    assert resposta.cancelada
    assert motor.pedidos == []
    resposta = cerebro.responder(
        "oi", epoch=0, publicar=lambda _: None, cancelado=lambda: True, avisos=[TAREFA]
    )
    assert resposta.cancelada
    assert motor.pedidos == [], "o motor não pode gerar depois do cancelamento"


def test_entregue_e_o_aviso_que_tocou_inteiro() -> None:
    """Regra 15: cortado no meio da fala dos avisos, eles voltam; tocada inteira, entregues."""
    texto = " ".join(f"palavra{i}" for i in range(30)) + "."
    cerebro = Cerebro(motor=MotorRoteirizado(resposta=texto, conta_eventos=False))
    publicados: list[dict[str, Any]] = []
    cerebro.avisar([TAREFA, DECISAO], epoch=0, publicar=publicados.append)
    sintese = SintetizadorEmStreaming(motor=MotorParametrico(), session_id="s", epoch=0)
    fala = falar_stream_para(sintese, publicados, lambda _p: True)

    assert avisos_tocados(publicados, fala, fala.amostras_sintetizadas, epoch=0) == (
        {"n1", "n2"},
        set(),
    )
    assert avisos_tocados(publicados, fala, 0, epoch=0) == (set(), {"n1", "n2"})
