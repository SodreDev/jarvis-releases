"""O stream SSE: linhas na ordem, comentário ignorado, cancelamento que fecha a conexão."""

from __future__ import annotations

import json
import time

import pytest

from jarvis.provedores.compativel import MotorCompativelOpenAI
from jarvis.provedores.stream import StreamCancelado, eventos_sse, linhas
from jarvis.s2.motor import (
    PRAZO_DE_CANCELAMENTO_S,
    Contexto,
    Fim,
    Mensagem,
    Modo,
    MotivoDoFim,
    Raciocinio,
    Texto,
)
from jarvis.voz.chaves import Chave
from jarvis.voz.interface import Onde, nunca_cancelado
from jarvis.voz.nuvem import NuvemRealProibidaEmCI
from tests.unit.voz.servidor_falso import Roteiro, ServicoFalso

SEGREDO = "sk-proj-chave_de_teste_que_nao_pode_vazar_0123456789"
VARIAVEL = "JARVIS_TESTE_API_KEY"
AMBIENTE = {"CI": "1", VARIAVEL: SEGREDO}


def sse(*eventos: object, comentario: bool = True) -> bytes:
    partes = [": OPENROUTER PROCESSING\n\n"] if comentario else []
    partes += [f"data: {json.dumps(e)}\n\n" for e in eventos]
    partes.append("data: [DONE]\n\n")
    return "".join(partes).encode()


def pedaco(texto: str = "", raciocinio: str = "") -> dict[str, object]:
    delta: dict[str, object] = {}
    if texto:
        delta["content"] = texto
    if raciocinio:
        delta["reasoning"] = raciocinio
    return {"choices": [{"index": 0, "delta": delta}]}


def contexto() -> Contexto:
    return Contexto(sistema="persona", mensagens=(Mensagem("dono", "que horas são?"),))


def motor(servico: ServicoFalso, **extras: object) -> MotorCompativelOpenAI:
    return MotorCompativelOpenAI(
        base=servico.base + "/v1",
        modelo="falso-1",
        nome="Falso · falso-1",
        onde=Onde.NUVEM,
        variavel_da_chave=VARIAVEL,
        ambiente=AMBIENTE,
        **extras,  # type: ignore[arg-type]
    )


def test_eventos_sse_junta_data_ignora_comentario_e_para_no_done() -> None:
    entrada = [": ping", "data: a", "data: b", "", "event: x", "data: c", "", "data: [DONE]", ""]
    assert list(eventos_sse(entrada)) == ["a\nb", "c"]


def test_texto_vai_para_a_fala_e_raciocinio_nao() -> None:
    corpo = sse(
        pedaco(raciocinio="vou ver o relógio"),
        pedaco(texto="São "),
        pedaco(texto="dez horas."),
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 4}},
    )
    with ServicoFalso(Roteiro(corpo=corpo, tipo="text/event-stream")) as servico:
        deltas = list(motor(servico).gerar(contexto(), Modo.RAPIDO, nunca_cancelado))

    assert [d.texto for d in deltas if isinstance(d, Texto)] == ["São ", "dez horas."]
    assert [d.texto for d in deltas if isinstance(d, Raciocinio)] == ["vou ver o relógio"]
    fim = deltas[-1]
    assert isinstance(fim, Fim) and fim.motivo is MotivoDoFim.CONCLUIDO
    assert fim.uso == {"entrada": 12, "saida": 4}
    pedido = servico.pedidos[0]
    assert pedido.caminho == "/v1/chat/completions"
    assert pedido.autorizacao == f"Bearer {SEGREDO}"
    assert SEGREDO.encode() not in pedido.corpo
    enviado = json.loads(pedido.corpo)
    assert enviado["model"] == "falso-1" and enviado["stream"] is True
    assert enviado["messages"][0]["role"] == "system"


def test_esforco_vai_no_campo_do_provedor() -> None:
    corpo = sse(pedaco(texto="ok"))
    with ServicoFalso(Roteiro(corpo=corpo, tipo="text/event-stream")) as servico:
        list(motor(servico, esforco="low").gerar(contexto(), Modo.RAPIDO, nunca_cancelado))
        list(
            motor(servico, esforco="low", estilo_do_esforco="reasoning").gerar(
                contexto(), Modo.PENSAR, nunca_cancelado
            )
        )
    primeiro, segundo = (json.loads(p.corpo) for p in servico.pedidos)
    assert primeiro["reasoning_effort"] == "low"
    assert segundo["reasoning"] == {"effort": "high"}  # o pensar sobe
    assert "reasoning_effort" not in segundo


def test_recusa_do_servico_vira_fim_com_motivo_sem_a_chave() -> None:
    roteiro = Roteiro(status=401, corpo=json.dumps({"error": {"message": SEGREDO}}).encode())
    with ServicoFalso(roteiro) as servico:
        deltas = list(motor(servico).gerar(contexto(), Modo.RAPIDO, nunca_cancelado))
    fim = deltas[-1]
    assert isinstance(fim, Fim) and fim.motivo is MotivoDoFim.ERRO
    assert "recusou" in fim.detalhe and "401" in fim.detalhe
    assert SEGREDO not in fim.detalhe


def test_cancelar_no_meio_para_em_ate_50_ms_e_fecha_a_conexao() -> None:
    corpo = sse(*(pedaco(texto=f"palavra {i} ") for i in range(40)))
    roteiro = Roteiro(corpo=corpo, tipo="text/event-stream", pedacos=40, pausa_s=0.05)
    cancelou_em: list[float] = []

    def cancelado() -> bool:
        return bool(cancelou_em)

    with ServicoFalso(roteiro) as servico:
        gerador = motor(servico).gerar(contexto(), Modo.RAPIDO, cancelado)
        deltas = []
        for delta in gerador:
            deltas.append(delta)
            if isinstance(delta, Texto) and not cancelou_em:
                cancelou_em.append(time.monotonic())
        parou_em = time.monotonic()

    fim = deltas[-1]
    assert isinstance(fim, Fim) and fim.motivo is MotivoDoFim.CANCELADO
    assert parou_em - cancelou_em[0] < PRAZO_DE_CANCELAMENTO_S + 0.05
    assert sum(isinstance(d, Texto) for d in deltas) < 5


def test_sob_ci_base_de_nuvem_de_verdade_recusa_antes_do_socket() -> None:
    with pytest.raises(NuvemRealProibidaEmCI):
        next(
            linhas(
                "https://api.openai.com/v1/chat/completions",
                corpo=b"{}",
                chave=Chave(VARIAVEL, SEGREDO),
                cancelado=nunca_cancelado,
                prazo_s=1.0,
                ambiente={"CI": "1"},
            )
        )


def test_cancelado_antes_nao_abre_conexao() -> None:
    with ServicoFalso(Roteiro()) as servico, pytest.raises(StreamCancelado):
        next(
            linhas(
                servico.base + "/x",
                corpo=b"{}",
                chave=None,
                cancelado=lambda: True,
                prazo_s=1.0,
                ambiente=AMBIENTE,
            )
        )
    assert servico.pedidos == []
