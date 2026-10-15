"""Cartão F1-05, aceite (b): a regra 1 da §3.3 é de ORDEM, e a ordem está na trilha."""

from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.agentd.percepcao import Percepcao, Transcritor
from jarvis.audio_io.trilha import EventoDeTrilha
from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust
from jarvis.barramento.epoch import DonoDoEpoch
from tests.fabricas import evento


@dataclass(slots=True)
class TranscritorApressado:
    """ASR que tenta publicar um parcial no mesmo instante em que a fala começa.

    É o pior caso para a regra 1: se a ordem dependesse de quem corre mais, o parcial poderia
    sair antes do `Cancel` e o barge-in chegaria tarde ao `s2`.
    """

    nome: str = "apressado@teste"
    chamadas: list[int] = field(default_factory=list)

    def comecar(self, *, session_id: str, epoch: int) -> list[Envelope]:
        self.chamadas.append(epoch)
        return [
            Envelope(
                session_id=session_id,
                epoch=epoch,
                source="agentd",
                trust=Trust.USER_VOICE,
                priority=Prioridade.P1,
                type=Tipo.PARTIAL_TRANSCRIPT,
                payload={
                    "text": "liga o",
                    "stability": 0.3,
                    "t_start_ms": 0,
                    "t_end_ms": 120,
                    "lang": "pt-BR",
                },
            )
        ]


def test_o_cancel_sai_antes_de_qualquer_parcial(sessao: str) -> None:
    """Aceite (b): ordem na trilha, não cronômetro."""
    transcritor = TranscritorApressado()
    percepcao = Percepcao(dono=DonoDoEpoch(session_id=sessao), transcritor=transcritor)

    eventos = percepcao(evento(Tipo.AUDIO_ACTIVITY, sessao, speech=True), 1)
    trilha = [EventoDeTrilha.de_envelope(e) for e in eventos]

    assert [e.type for e in trilha] == ["Cancel", "PartialTranscript"]
    assert eventos[0].priority is Prioridade.P0
    assert isinstance(transcritor, Transcritor)


def test_o_epoch_sobe_antes_do_asr_e_o_parcial_nasce_no_epoch_novo(sessao: str) -> None:
    dono = DonoDoEpoch(session_id=sessao)
    percepcao = Percepcao(dono=dono, transcritor=TranscritorApressado())

    eventos = percepcao(evento(Tipo.AUDIO_ACTIVITY, sessao, speech=True), 1)

    cancelamento, parcial = eventos
    assert cancelamento.payload["epoch_invalidado"] == 0
    assert cancelamento.epoch == 1
    assert parcial.epoch == 1, "o parcial não pode nascer no epoch que acabou de morrer"
    assert dono.epoch_atual == 1


def test_a_percepcao_nao_espera_o_asr_para_cancelar(sessao: str) -> None:
    """Sem transcritor nenhum, o `Cancel` sai igual: ele não depende de percepção de texto."""
    percepcao = Percepcao(dono=DonoDoEpoch(session_id=sessao), transcritor=None)

    eventos = percepcao(evento(Tipo.AUDIO_ACTIVITY, sessao, speech=True), 1)

    assert eventos[0].type is Tipo.CANCEL
    assert eventos[0].payload["reason"] == "barge_in"


def test_silencio_e_aec_ok_nao_geram_nada(sessao: str) -> None:
    percepcao = Percepcao(dono=DonoDoEpoch(session_id=sessao))

    assert percepcao(evento(Tipo.AUDIO_ACTIVITY, sessao, speech=False), 1) == []
    assert percepcao(evento(Tipo.PLAYBACK_PROGRESS, sessao), 2) == []


def test_cancel_do_aec_vem_antes_de_qualquer_turno(sessao: str) -> None:
    """Cartão F1-04 + F1-05: referência perdida cancela, e não abre turno nenhum."""
    transcritor = TranscritorApressado()
    percepcao = Percepcao(dono=DonoDoEpoch(session_id=sessao), transcritor=transcritor)

    eventos = percepcao(evento(Tipo.AUDIO_ACTIVITY, sessao, speech=True, aec_ok=False), 1)

    assert [e.type for e in eventos] == [Tipo.CANCEL]
    assert eventos[0].payload["reason"] == "aec_fail"
    assert transcritor.chamadas == [], "sem referência de AEC não se começa a ouvir"
