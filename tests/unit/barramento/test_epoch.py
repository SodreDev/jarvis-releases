"""Aceite F0-02 (b): um teste para cada uma das seis regras de epoch da §3.3.

A numeração dos testes é a da SPEC, de propósito: quando a regra mudar, o teste que cai
aponta o parágrafo.
"""

from __future__ import annotations

import pytest

from jarvis.barramento import (
    DonoDoEpoch,
    EpochMorto,
    FilaDePrioridade,
    LivroDeFala,
    Prioridade,
    Tipo,
    Trust,
    Veredito,
    validar,
)
from jarvis.barramento.epoch import TIPOS_DE_AUDITORIA
from tests.fabricas import evento


def test_regra1_fala_comecou_incrementa_e_cancela_antes_de_qualquer_asr(sessao: str) -> None:
    """R1: `speech_started` → epoch+1 e `Cancel` imediato, sem esperar ASR nem S2."""
    dono = DonoDoEpoch(session_id=sessao, epoch_atual=7)

    cancelamento = dono.fala_comecou()

    assert dono.epoch_atual == 8
    assert cancelamento.type is Tipo.CANCEL
    assert cancelamento.priority is Prioridade.P0
    assert cancelamento.payload == {"epoch_invalidado": 7, "reason": "barge_in"}
    assert cancelamento.epoch == 8
    assert cancelamento.trust is Trust.SYSTEM
    validar(cancelamento)  # o Cancel sai pronto para o barramento


def test_regra1_motivo_fora_da_spec_e_recusado(sessao: str) -> None:
    dono = DonoDoEpoch(session_id=sessao)

    with pytest.raises(ValueError, match="motivo de Cancel"):
        dono.fala_comecou(motivo="cansei")

    assert dono.epoch_atual == 0  # nada muda quando o motivo é inválido


def test_regra2_cancelamento_esvazia_a_fila_e_marca_em_voo_como_stale(sessao: str) -> None:
    """R2: no mesmo tick, a fila do epoch morto é esvaziada e o que está em voo fica stale."""
    dono = DonoDoEpoch(session_id=sessao)
    leitura = dono.registrar_chamada("c-leitura", read_only=True)
    escrita = dono.registrar_chamada("c-escrita", read_only=False)

    fila = FilaDePrioridade()
    fila.publicar(evento(Tipo.PLAYBACK_PROGRESS, sessao, chunk_id="k-1", played_ms=40))
    fila.publicar(evento(Tipo.PARTIAL_TRANSCRIPT, sessao, text="liga o"))
    fila.publicar(evento(Tipo.TOOL_RESULT, sessao, call_id="c-leitura"))

    cancelamento = dono.fala_comecou()
    descartados = fila.descartar_epoch(
        cancelamento.payload["epoch_invalidado"], manter=TIPOS_DE_AUDITORIA
    )

    assert leitura.stale and escrita.stale
    assert {e.type for e in descartados} == {Tipo.PLAYBACK_PROGRESS, Tipo.PARTIAL_TRANSCRIPT}
    assert fila.pendentes(Prioridade.P2) == 1  # o ToolResult fica, pela regra 6


def test_regra3_tool_result_de_leitura_stale_sobrevive_para_reavaliacao(sessao: str) -> None:
    """R3: leitura `stale` pode terminar; só entra se o `s2` reavaliar."""
    dono = DonoDoEpoch(session_id=sessao)
    dono.fala_comecou()

    leitura = evento(Tipo.TOOL_RESULT, sessao, epoch=0, call_id="c-1", read_only=True)
    escrita = evento(Tipo.TOOL_RESULT, sessao, epoch=0, call_id="c-2", read_only=False)

    assert dono.classificar(leitura) is Veredito.ACEITAR_STALE
    assert dono.classificar(escrita) is Veredito.SO_AUDITORIA


def test_regra3_efeito_exige_chave_de_idempotencia(sessao: str) -> None:
    """R3: tool de efeito nunca é especulativa — a borda cobra a chave (ver test_contrato)."""
    from jarvis.barramento import ErroDeContrato

    with pytest.raises(ErroDeContrato, match="idempotency_key"):
        validar(evento(Tipo.TOOL_CALL_REQUESTED, sessao, dry_run=False))


def test_regra4_so_entra_no_historico_o_que_tocou(sessao: str) -> None:
    """R4 (P4): áudio enfileirado e não reproduzido não existe para o modelo."""
    livro = LivroDeFala()
    livro.enfileirar("k-1", "Achei três arquivos", epoch=0)
    livro.enfileirar("k-2", "e apaguei o primeiro", epoch=0)
    livro.progresso(evento(Tipo.PLAYBACK_PROGRESS, sessao, chunk_id="k-1", played_ms=820))

    assert livro.texto_tocado() == "Achei três arquivos"
    assert livro.audio_tocado_ms() == 820

    perdidos = livro.descartar_nao_tocado(epoch=0)

    assert perdidos == ["k-2"]
    assert livro.texto_tocado() == "Achei três arquivos"


def test_regra4_progresso_maior_vence_e_chunk_desconhecido_e_erro(sessao: str) -> None:
    livro = LivroDeFala()
    livro.enfileirar("k-1", "oi", epoch=0)
    livro.progresso(evento(Tipo.PLAYBACK_PROGRESS, sessao, chunk_id="k-1", played_ms=100))
    livro.progresso(evento(Tipo.PLAYBACK_PROGRESS, sessao, chunk_id="k-1", played_ms=40))

    assert livro.audio_tocado_ms() == 100

    with pytest.raises(KeyError, match="k-9"):
        livro.progresso(evento(Tipo.PLAYBACK_PROGRESS, sessao, chunk_id="k-9", played_ms=10))


def test_regra5_continua_nao_ressuscita_o_plano_antigo(sessao: str) -> None:
    """R5: a retomada parte do trecho realmente tocado, não do epoch morto."""
    dono = DonoDoEpoch(session_id=sessao)
    livro = LivroDeFala()
    livro.enfileirar("k-1", "o relatório tem", epoch=0)
    livro.enfileirar("k-2", "quatro pendências", epoch=0)
    livro.progresso(evento(Tipo.PLAYBACK_PROGRESS, sessao, chunk_id="k-1", played_ms=500))

    dono.fala_comecou(motivo="stop_word")
    livro.descartar_nao_tocado(epoch=0)

    with pytest.raises(EpochMorto, match="está morto"):
        dono.retomar(0)

    dono.retomar(dono.epoch_atual)  # o epoch vivo é retomável
    assert livro.texto_tocado() == "o relatório tem"
    assert dono.morto(0)


def test_regra6_evento_de_epoch_antigo_e_descartado(sessao: str) -> None:
    """R6: epoch < atual é descartado por padrão."""
    dono = DonoDoEpoch(session_id=sessao)
    dono.fala_comecou()

    for tipo in (Tipo.PARTIAL_TRANSCRIPT, Tipo.FINAL_TRANSCRIPT, Tipo.STATE_REVISION):
        assert dono.classificar(evento(tipo, sessao, epoch=0)) is Veredito.DESCARTAR


def test_regra6_excecoes_sao_auditoria_e_leitura_stale(sessao: str) -> None:
    """R6: as exceções são `ToolResult` de leitura (R3) e os eventos de auditoria."""
    dono = DonoDoEpoch(session_id=sessao)
    dono.fala_comecou()

    decisao = evento(Tipo.POLICY_DECISION, sessao, epoch=0)
    leitura = evento(Tipo.TOOL_RESULT, sessao, epoch=0, read_only=True)

    assert dono.classificar(decisao) is Veredito.SO_AUDITORIA
    assert dono.classificar(leitura) is Veredito.ACEITAR_STALE


def test_regra6_evento_do_epoch_atual_e_aceito_e_do_futuro_e_descartado(sessao: str) -> None:
    dono = DonoDoEpoch(session_id=sessao, epoch_atual=3)

    assert dono.classificar(evento(Tipo.FINAL_TRANSCRIPT, sessao, epoch=3)) is Veredito.ACEITAR
    assert dono.classificar(evento(Tipo.FINAL_TRANSCRIPT, sessao, epoch=9)) is Veredito.DESCARTAR


def test_regra6_a_excecao_de_auditoria_vale_tambem_para_epoch_do_futuro(sessao: str) -> None:
    """Achado 11 da revisão F0+F1: a exceção da regra 6 era só para o epoch do passado.

    `classificar` descartava tudo que vinha com `epoch > epoch_atual` antes de consultar
    `TIPOS_DE_AUDITORIA`. Cenário: depois de um restart o `policy` lê o epoch do log e publica
    `POLICY_DECISION` enquanto o `agentd` ainda não processou o `fala_comecou` que incrementa o
    contador dele. A decisão chegava do "futuro" e era descartada **sem registro** — buraco no
    audit_log justamente na decisão de política, que a §5.5 manda registrar antes do efeito.

    A invariante do comentário do módulo não distingue passado de futuro, e agora o código
    também não.
    """
    dono = DonoDoEpoch(session_id=sessao, epoch_atual=3)

    for tipo in TIPOS_DE_AUDITORIA:
        do_futuro = evento(tipo, sessao, epoch=9)

        assert dono.classificar(do_futuro) is Veredito.SO_AUDITORIA, (
            f"{tipo} do futuro tem de chegar à auditoria, não ao raciocínio"
        )

    # O resto do futuro continua descartado: a exceção é dos dois tipos, não do epoch.
    assert dono.classificar(evento(Tipo.FINAL_TRANSCRIPT, sessao, epoch=9)) is Veredito.DESCARTAR
