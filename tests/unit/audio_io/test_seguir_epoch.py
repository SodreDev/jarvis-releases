"""O `audio-io` segue o epoch do barramento — defeito achado no F1-14.

Sem seguir, o **primeiro** `Cancel` da sessão deixava o microfone surdo: a captura continuava
publicando `AudioActivity` com o epoch da conexão, e `DonoDoEpoch.classificar` manda descartar
(`AudioActivity` não é tipo de auditoria). Silencioso, sem erro e sem log. Este teste conta a
história inteira: antes de seguir, o evento é descartado; depois, é aceito.
"""

from __future__ import annotations

from jarvis.audio_io import (
    Captura,
    DetectorDeEnergia,
    FilaDePlayback,
    FonteSintetica,
    SumidouroEmMemoria,
)
from jarvis.audio_io.controle import seguir_epoch
from jarvis.barramento.envelope import Envelope, Tipo
from jarvis.barramento.epoch import DonoDoEpoch, Veredito
from jarvis.relogio import RelogioFalso

SESSAO = "0193f0a0-0000-7000-8000-000000000000"


def montar() -> tuple[Captura, FilaDePlayback]:
    relogio = RelogioFalso()
    captura = Captura(
        fonte=FonteSintetica(relogio=relogio, semente=5),
        relogio=relogio,
        session_id=SESSAO,
        detector=DetectorDeEnergia(),
    )
    captura.abrir()
    fila = FilaDePlayback(sumidouro=SumidouroEmMemoria(), session_id=SESSAO)
    return captura, fila


def primeiro_evento(captura: Captura) -> Envelope:
    """O primeiro `AudioActivity` que a captura publicar — o evento de verdade, não um fabricado."""
    for _ in range(60):
        eventos = [e for e in captura.tick() if e.type is Tipo.AUDIO_ACTIVITY]
        if eventos:
            return eventos[0]
    raise AssertionError("a fonte sintética tem fala: algum AudioActivity tinha de sair")


def test_sem_seguir_o_epoch_o_microfone_fica_surdo() -> None:
    """A prova do defeito: o evento da captura é DESCARTADO depois de um barge-in."""
    captura, _ = montar()
    dono = DonoDoEpoch(session_id=SESSAO)
    dono.fala_comecou()  # primeiro barge-in da sessão: epoch 0 → 1

    envelope = primeiro_evento(captura)

    assert envelope.epoch == 0, "a captura carimbava o epoch da conexão"
    assert dono.epoch_atual == 1
    assert dono.classificar(envelope) is Veredito.DESCARTAR, (
        "era isto que acontecia com todo quadro depois do primeiro Cancel"
    )


def test_seguindo_o_epoch_o_evento_volta_a_ser_aceito() -> None:
    captura, fila = montar()
    dono = DonoDoEpoch(session_id=SESSAO)
    dono.fala_comecou()

    mudou = seguir_epoch(captura, fila, dono.epoch_atual)

    envelope = primeiro_evento(captura)

    assert mudou is True
    assert (captura.epoch, fila.epoch_atual) == (1, 1)
    assert envelope.epoch == 1
    assert dono.classificar(envelope) is Veredito.ACEITAR


def test_o_epoch_nunca_volta_atras() -> None:
    captura, fila = montar()
    seguir_epoch(captura, fila, 5)

    voltou = seguir_epoch(captura, fila, 3)

    assert voltou is False
    assert (captura.epoch, fila.epoch_atual) == (5, 5)
