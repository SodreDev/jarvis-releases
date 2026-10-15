"""Aceite F0-02 (c) P0 preempta com fila cheia e (d) coalescing de parciais."""

from __future__ import annotations

import pytest

from jarvis.barramento import FilaCheia, FilaDePrioridade, Prioridade, Tipo, chave_de_coalescing
from tests.fabricas import evento


def test_p0_preempta_p1_a_p4_com_a_fila_cheia(sessao: str) -> None:
    """Aceite (c): a fila enche de trabalho e o `Cancel` ainda assim sai primeiro."""
    fila = FilaDePrioridade(capacidade_por_banda=8)
    for i in range(8):
        fila.publicar(evento(Tipo.DESKTOP_OBSERVATION, sessao, kind=f"janela-{i}"))  # P3
    for i in range(8):
        fila.publicar(evento(Tipo.FINAL_TRANSCRIPT, sessao, text=f"frase {i}"))  # P1
    for i in range(8):
        fila.publicar(evento(Tipo.POLICY_DECISION, sessao, call_id=f"c-{i}"))  # P2
    assert len(fila) == 24

    cancelamento = evento(Tipo.CANCEL, sessao, epoch=1, epoch_invalidado=0)
    fila.publicar(cancelamento)  # P0 nunca é recusado por fila cheia

    primeiro = fila.retirar()
    assert primeiro is not None
    assert primeiro.event_id == cancelamento.event_id
    assert primeiro.priority is Prioridade.P0


def test_banda_cheia_recusa_em_vez_de_perder_evento_em_silencio(sessao: str) -> None:
    fila = FilaDePrioridade(capacidade_por_banda=2)
    for i in range(2):
        fila.publicar(evento(Tipo.POLICY_DECISION, sessao, call_id=f"c-{i}"))

    with pytest.raises(FilaCheia, match="P2"):
        fila.publicar(evento(Tipo.POLICY_DECISION, sessao, call_id="c-x"))


def test_ordem_de_retirada_e_por_prioridade_e_depois_fifo(sessao: str) -> None:
    fila = FilaDePrioridade()
    fila.publicar(evento(Tipo.DESKTOP_OBSERVATION, sessao, kind="a"))  # P3
    fila.publicar(evento(Tipo.POLICY_DECISION, sessao, call_id="c-1"))  # P2
    fila.publicar(evento(Tipo.POLICY_DECISION, sessao, call_id="c-2"))  # P2
    fila.publicar(evento(Tipo.FINAL_TRANSCRIPT, sessao, text="oi"))  # P1

    retirados = [e.type for e in iter(fila.retirar, None)]

    assert retirados == [
        Tipo.FINAL_TRANSCRIPT,
        Tipo.POLICY_DECISION,
        Tipo.POLICY_DECISION,
        Tipo.DESKTOP_OBSERVATION,
    ]


def test_dez_parciais_em_200ms_viram_uma_hipotese(sessao: str) -> None:
    """Aceite (d): coalescing é obrigatório — 10 parciais não disparam 10 raciocínios."""
    fila = FilaDePrioridade()
    for i in range(10):
        fila.publicar(
            evento(
                Tipo.PARTIAL_TRANSCRIPT,
                sessao,
                text="liga o rádio"[: i + 1],
                stability=i / 10,
                t_end_ms=20 * (i + 1),
            )
        )

    assert fila.pendentes(Prioridade.P1) == 1
    assert fila.coalescidos == 9

    sobrevivente = fila.retirar()
    assert sobrevivente is not None
    assert sobrevivente.payload["t_end_ms"] == 200  # a hipótese mais recente venceu
    assert fila.retirar() is None


def test_fato_nunca_e_coalescido(sessao: str) -> None:
    """Perder um `FinalTranscript`, `ToolResult` ou `PlaybackProgress` muda o histórico (P4)."""
    fila = FilaDePrioridade()
    for i in range(3):
        fila.publicar(evento(Tipo.FINAL_TRANSCRIPT, sessao, text=f"frase {i}"))
        fila.publicar(evento(Tipo.PLAYBACK_PROGRESS, sessao, chunk_id=f"k-{i}", played_ms=20))
        fila.publicar(evento(Tipo.TOOL_RESULT, sessao, call_id=f"c-{i}"))

    assert len(fila) == 9
    assert fila.coalescidos == 0


def test_speech_started_nao_e_coalescido(sessao: str) -> None:
    """O gatilho do barge-in é P0 e não pode ser substituído por hipótese nenhuma."""
    inicio = evento(Tipo.AUDIO_ACTIVITY, sessao, speech=True)
    silencio = evento(Tipo.AUDIO_ACTIVITY, sessao, speech=False)

    assert chave_de_coalescing(inicio) is None
    assert chave_de_coalescing(silencio) is not None

    fila = FilaDePrioridade()
    fila.publicar(inicio)
    fila.publicar(evento(Tipo.AUDIO_ACTIVITY, sessao, speech=True))
    assert fila.pendentes(Prioridade.P0) == 2
    assert fila.coalescidos == 0


def test_coalescing_nao_mistura_epochs_nem_sessoes(sessao: str) -> None:
    fila = FilaDePrioridade()
    fila.publicar(evento(Tipo.PARTIAL_TRANSCRIPT, sessao, epoch=1, text="a"))
    fila.publicar(evento(Tipo.PARTIAL_TRANSCRIPT, sessao, epoch=2, text="b"))

    assert fila.pendentes(Prioridade.P1) == 2
    assert fila.coalescidos == 0
