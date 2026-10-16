"""ADR-0025, regra 10: o TTS consome os pedaços do epoch corrente, em ordem."""

from __future__ import annotations

from typing import Any

import pytest

from jarvis.agentd.fala_em_stream import StreamForaDeOrdem, falar_stream_para, trechos_do_stream
from jarvis.agentd.tts import MotorParametrico, SintetizadorEmStreaming
from jarvis.audio_io.playback import FilaDePlayback, Pedaco
from jarvis.audio_io.sumidouros import SumidouroEmMemoria
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor_roteirizado import MotorRoteirizado


def _pedaco(
    seq: int, texto: str, *, epoch: int = 1, last: bool = False, rid: str = "r"
) -> dict[str, Any]:
    return {
        "response_id": rid,
        "turn_id": "t",
        "epoch": epoch,
        "seq": seq,
        "text": texto,
        "boundary": "fim" if last else "limite",
        "last": last,
    }


def test_os_trechos_tem_posicao_no_texto_juntado() -> None:
    trechos = list(
        trechos_do_stream(
            [_pedaco(0, "Depois de quinta"), _pedaco(1, "vem sexta."), _pedaco(2, "", last=True)],
            epoch=1,
        )
    )
    assert trechos == [(0, "Depois de quinta"), (17, "vem sexta.")]


def test_pedaco_de_outro_epoch_ou_outra_resposta_e_ignorado() -> None:
    pedacos = [
        _pedaco(0, "velho", epoch=0),
        _pedaco(0, "Oi"),
        _pedaco(0, "intruso", rid="outra"),
        _pedaco(1, "tudo bem?", last=True),
        _pedaco(2, "depois do fim"),
    ]
    assert [t for _, t in trechos_do_stream(pedacos, epoch=1)] == ["Oi", "tudo bem?"]


def test_seq_fora_de_ordem_e_defeito_e_nao_ruido() -> None:
    with pytest.raises(StreamForaDeOrdem, match="esperava seq 1"):
        list(trechos_do_stream([_pedaco(0, "Oi"), _pedaco(2, "pulou")], epoch=1))


def test_do_cerebro_ao_alto_falante_e_de_volta_a_conversa() -> None:
    """O caminho inteiro: pedaços → síntese → fila → tocado → `Cerebro.ouvido`."""
    texto = "Depois de quinta vem sexta-feira, e depois o sábado."
    cerebro = Cerebro(motor=MotorRoteirizado(resposta=texto))
    publicados: list[dict[str, Any]] = []
    resposta = cerebro.responder("e depois de quinta?", epoch=1, publicar=publicados.append)

    sumidouro = SumidouroEmMemoria()
    fila = FilaDePlayback(sumidouro=sumidouro, session_id="s", epoch_atual=1)
    sintese = SintetizadorEmStreaming(motor=MotorParametrico(), session_id="s", epoch=1)
    entregues: list[Pedaco] = []

    def enfileirar(pedaco: Pedaco) -> bool:
        entregues.append(pedaco)
        return fila.enfileirar(pedaco)

    fala = falar_stream_para(sintese, publicados, enfileirar)
    assert fala.texto == texto
    assert len(entregues) == len([p for p in publicados if p["text"]])

    metade = fala.trechos[1].fim_em_amostras
    cerebro.ouvido(resposta.response_id, fala.texto_ate(metade), interrompida=True)
    assert cerebro.conversa.turnos[-1].texto == "Depois de quinta vem sexta-feira,"
