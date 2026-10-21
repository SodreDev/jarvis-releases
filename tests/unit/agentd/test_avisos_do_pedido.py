"""ADR-0038: os avisos da tarefa de um pedido do dono (a resposta, a pergunta) na fila de avisos.

Não são espontâneos — quem abriu a conversa foi o dono, ao pedir —, então não esperam o teto de
fala de 2 min (D22); o piso livre continua valendo: nunca por cima da fala, e um por vez. E a frase
é a fala como ela é, sem "Aviso:" na frente."""

from __future__ import annotations

from jarvis.agentd.fila_de_avisos import ORIGEM_DO_PEDIDO, FilaDeAvisos, notificacao
from jarvis.barramento.envelope import uuid7
from jarvis.s2.avisos import AvisoLiberado, frase_do_aviso

S = str(uuid7())


def _fila_com_um_falado_agora() -> FilaDeAvisos:
    fila = FilaDeAvisos(session_id=S)
    fila.receber(notificacao(S, "a1", tipo="evento", origem="x", resumo="primeiro"), 0.0)
    liberado = fila.liberar(10.0)
    assert liberado is not None
    fila.tocou(["a1"], 10.0)
    return fila


def test_aviso_espontaneo_espera_o_teto_e_o_do_pedido_nao() -> None:
    fila = _fila_com_um_falado_agora()
    fila.receber(notificacao(S, "a2", tipo="evento", origem="x", resumo="espontâneo"), 11.0)
    assert fila.liberar(20.0) is None, "o espontâneo espera os 2 min do D22"
    origem = f"{ORIGEM_DO_PEDIDO}abre o vídeo"
    fila.receber(notificacao(S, "t-1", tipo="concluida", origem=origem, resumo="Abri."), 21.0)
    liberado = fila.liberar(30.0)
    assert liberado is not None and liberado.payload["notif_ids"] == ["t-1"]


def test_o_do_pedido_nunca_sai_por_cima_da_fala() -> None:
    fila = FilaDeAvisos(session_id=S)
    fila.receber(
        notificacao(S, "t-1", tipo="concluida", origem=f"{ORIGEM_DO_PEDIDO}x", resumo="Abri."),
        0.0,
    )
    fila.tts_tocando(True, 1.0)
    assert fila.liberar(5.0) is None
    fila.tts_tocando(False, 5.0)
    assert fila.liberar(5.5) is None, "piso livre: 1,5 s de silêncio"
    assert fila.liberar(7.0) is not None


def test_a_frase_do_pedido_e_a_fala_como_ela_e() -> None:
    origem = f"{ORIGEM_DO_PEDIDO}abre o vídeo"
    resposta = AvisoLiberado("t-1", "concluida", origem, "Abri o vídeo na aba atual")
    pergunta = AvisoLiberado("p-1", "precisa_decisao", origem, "Preciso do seu sim. Posso?")
    assert frase_do_aviso(resposta) == "Abri o vídeo na aba atual."
    assert frase_do_aviso(pergunta) == "Preciso do seu sim. Posso?"
    alheio = AvisoLiberado("x", "concluida", origem, "a página diz X", de_terceiros=True)
    assert frase_do_aviso(alheio).startswith("Aviso de"), "de terceiros continua marcado"
