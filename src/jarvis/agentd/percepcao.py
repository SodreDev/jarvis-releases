"""Percepção do `agentd`: a regra 1 da §3.3 no lugar certo (cartão F1-05).

**A regra 1 é de ordem, não de cronômetro.** `speech_started` local ⇒ `epoch := epoch + 1` e
`Cancel(epoch_anterior)` **imediatos**, sem esperar ASR nem S2. Então aqui o `Cancel` é sempre
o **primeiro** envelope da lista devolvida, e qualquer transcrição vem depois dele e já nasce
no epoch novo. Um teste afirma essa ordem na trilha; medir com relógio provaria outra coisa.

Por que mora no `agentd` e não no `audio-io`: a §3.2 fixa a origem canônica de `Cancel` no
`agentd` (ele é o dono do epoch). O `audio-io` detecta e **relata** (`AudioActivity` com
`speech` e `aec_ok`); quem decide cancelar é este módulo.

O transcritor é um encaixe (`Transcritor`): no esqueleto ele não existe e a percepção fecha um
turno sintético — o ASR incremental de verdade é o cartão F1-06, e entra **atrás** desta
garantia de ordem, não no lugar dela.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust
from jarvis.barramento.epoch import DonoDoEpoch

TEXTO_SINTETICO = "qual é o status do esqueleto"


@runtime_checkable
class Transcritor(Protocol):
    """ASR incremental (cartão F1-06). Recebe o epoch do turno e devolve eventos."""

    nome: str

    def comecar(self, *, session_id: str, epoch: int) -> list[Envelope]:
        """Começa um turno novo. Devolve zero ou mais eventos (parciais iniciais)."""
        ...


@dataclass(slots=True)
class Percepcao:
    """S1 da percepção: de `AudioActivity` saem cancelamento e turno, nesta ordem."""

    dono: DonoDoEpoch
    transcritor: Transcritor | None = None
    turnos: int = 0
    aec_ok: bool = True
    um_turno_so: bool = True
    """O esqueleto fecha um turno só (F0-03). Conversa de verdade é F1/F2."""
    cancelamentos: list[str] = field(default_factory=list)

    def __call__(self, envelope: Envelope, _seq: int = 0) -> list[Envelope]:
        if envelope.type is not Tipo.AUDIO_ACTIVITY:
            return []

        # Cartão F1-04: `aec_ok` falso é fato do `audio-io`; cancelar é decisão daqui.
        aec_ok = bool(envelope.payload["aec_ok"])
        if not aec_ok and self.aec_ok:
            self.aec_ok = False
            self.cancelamentos.append("aec_fail")
            return [self.dono.fala_comecou(motivo="aec_fail")]
        self.aec_ok = aec_ok

        if not bool(envelope.payload["speech"]):
            return []
        if self.um_turno_so and self.turnos > 0:
            return []
        self.turnos += 1

        # Regra 1: o epoch sobe e o Cancel sai ANTES de qualquer transcrição.
        cancelamento = self.dono.fala_comecou()
        self.cancelamentos.append("barge_in")
        eventos = [cancelamento]

        if self.transcritor is not None:
            eventos += self.transcritor.comecar(
                session_id=self.dono.session_id, epoch=self.dono.epoch_atual
            )
        else:
            eventos.append(self._turno_sintetico())
        return eventos

    def _turno_sintetico(self) -> Envelope:
        """O turno do esqueleto (F0-03): determinístico, para a cadeia dos sete processos."""
        return Envelope(
            session_id=self.dono.session_id,
            epoch=self.dono.epoch_atual,
            source="agentd",
            trust=Trust.USER_VOICE,
            priority=Prioridade.P1,
            type=Tipo.FINAL_TRANSCRIPT,
            payload={
                "text": TEXTO_SINTETICO,
                "confidence": 1.0,
                "t_start_ms": 0,
                "t_end_ms": 1000,
            },
        )
