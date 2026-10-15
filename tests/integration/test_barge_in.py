"""Barge-in ponta a ponta dentro do barramento: fila, epoch e log juntos (§3.3).

Ainda não há processos (isso é o cartão F0-03): aqui o que se prova é que as peças do
barramento combinadas produzem o comportamento que a SPEC cobra — interromper vence tudo,
o que não tocou desaparece e o log continua verificável.
"""

from __future__ import annotations

from pathlib import Path

from jarvis.barramento import (
    DonoDoEpoch,
    FilaDePrioridade,
    Fronteira,
    LivroDeFala,
    LogDeEventos,
    Prioridade,
    Tipo,
    Trust,
    Veredito,
    receber,
)
from jarvis.barramento.epoch import TIPOS_DE_AUDITORIA
from tests.fabricas import evento


def test_interromper_no_meio_da_resposta_nao_deixa_nada_para_tras(
    tmp_path: Path, sessao: str
) -> None:
    dono = DonoDoEpoch(session_id=sessao)
    fila = FilaDePrioridade()
    livro = LivroDeFala()

    with LogDeEventos(tmp_path / "eventos.sqlite") as log:
        # O Jarvis está falando: três pedaços na fila, só o primeiro tocou.
        for i, texto in enumerate(("Achei três arquivos", "o maior é", "o relatório de junho")):
            livro.enfileirar(f"k-{i}", texto, epoch=0)
        progresso = evento(Tipo.PLAYBACK_PROGRESS, sessao, chunk_id="k-0", played_ms=900)
        livro.progresso(progresso)
        log.anexar(progresso)

        # Trabalho pendente de várias prioridades, incluindo uma leitura em voo.
        dono.registrar_chamada("c-leitura", read_only=True)
        for i in range(3):
            pendente = evento(Tipo.PARTIAL_TRANSCRIPT, sessao, text=f"hipótese {i}")
            fila.publicar(pendente)
            log.anexar(pendente)
        fila.publicar(evento(Tipo.DESKTOP_OBSERVATION, sessao, kind="janela"))

        # O dono fala em cima: audio-io recebe do mundo, agentd cancela.
        bruto = evento(Tipo.AUDIO_ACTIVITY, sessao, speech=True).para_dict()
        bruto["trust"] = str(Trust.SYSTEM)  # o emissor tenta se promover
        recebido = receber(bruto, Fronteira.MICROFONE)
        assert recebido.envelope.trust is Trust.USER_VOICE
        assert recebido.envelope.priority is Prioridade.P0

        cancelamento = dono.fala_comecou()
        log.anexar(recebido.envelope)
        log.anexar(cancelamento)
        fila.publicar(cancelamento)

        # P0 sai antes de todo o trabalho pendente (P3 incluído).
        primeiro = fila.retirar()
        assert primeiro is not None
        assert primeiro.type is Tipo.CANCEL

        # O epoch morto é esvaziado; auditoria sobrevive.
        descartados = fila.descartar_epoch(0, manter=TIPOS_DE_AUDITORIA)
        perdidos = livro.descartar_nao_tocado(0)

        assert len(descartados) == 2  # 1 parcial coalescida + 1 observação
        assert fila.retirar() is None
        assert perdidos == ["k-1", "k-2"]

        # Histórico: só o que tocou de verdade (P4).
        assert livro.texto_tocado() == "Achei três arquivos"
        assert livro.audio_tocado_ms() == 900

        # Nada do epoch velho volta a influenciar o raciocínio…
        atrasado = evento(Tipo.FINAL_TRANSCRIPT, sessao, epoch=0, text="…de junho")
        assert dono.classificar(atrasado) is Veredito.DESCARTAR

        # …exceto a leitura que já estava em voo, e só para reavaliação.
        leitura = evento(Tipo.TOOL_RESULT, sessao, epoch=0, call_id="c-leitura", read_only=True)
        assert dono.classificar(leitura) is Veredito.ACEITAR_STALE
        assert dono.em_voo["c-leitura"].stale

        # O log registrou o caminho inteiro e continua íntegro.
        log.anexar(atrasado)
        log.anexar(leitura)
        assert log.verificar_cadeia() == 8
        tipos = [r.envelope.type for r in log.ler(session_id=sessao)]
        assert tipos.count(Tipo.CANCEL) == 1
        assert tipos[-2:] == [Tipo.FINAL_TRANSCRIPT, Tipo.TOOL_RESULT]
