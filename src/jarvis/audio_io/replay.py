"""A cascata do F1-01: quadros entram, eventos saem, trilha fica gravada.

O que esta cascata tem hoje: fonte → detector de energia → `AudioActivity` validado pelo
contrato (`schemas/events.v1.json`). O que ela **não** tem, de propósito: AEC (F1-04), VAD
de verdade (F1-05), regra 1 do epoch (F1-05) e ASR (F1-06). Cada cartão pendura o seu
estágio aqui, e a trilha cresce com ele.

Roda em processo, com o relógio injetado: é isso que faz a trilha ser comparável byte a
byte. O caminho de IPC de verdade (sete processos, corretor, log encadeado) é o F0-03 e
continua sendo exercido pelos testes de integração dele — misturar as duas coisas traria
tempo de escalonador para dentro de uma asserção de determinismo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.audio_io.energia import DetectorDeEnergia
from jarvis.audio_io.fontes import FonteDeAudio
from jarvis.audio_io.trilha import EventoDeTrilha
from jarvis.barramento.contrato import validar
from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust


@dataclass(frozen=True, slots=True)
class Reproducao:
    """O resultado de injetar um sinal na cascata."""

    eventos: list[EventoDeTrilha] = field(default_factory=list)
    quadros: int = 0
    amostras: int = 0

    @property
    def duracao_ms(self) -> float:
        return self.quadros * 20.0


def atividade(
    *,
    session_id: str,
    epoch: int,
    device_id: str,
    fala: bool,
    energia_db: float,
    ts_mono_ns: int,
    aec_ok: bool = True,
) -> Envelope:
    """`AudioActivity` da §3.2 — P0 quando é `speech_started`, P1 quando não é."""
    payload = {
        "speech": fala,
        "device_id": device_id,
        "energy_db": energia_db,
        "aec_ok": aec_ok,
    }
    return validar(
        Envelope(
            session_id=session_id,
            epoch=epoch,
            source="audio-io",
            trust=Trust.USER_VOICE,
            priority=Prioridade.P0 if fala else Prioridade.P1,
            type=Tipo.AUDIO_ACTIVITY,
            payload=payload,
            ts_mono_ns=ts_mono_ns,
        )
    )


def reproduzir(
    fonte: FonteDeAudio,
    *,
    session_id: str,
    epoch: int = 0,
    detector: DetectorDeEnergia | None = None,
) -> Reproducao:
    """Injeta a fonte na cascata e devolve a trilha de eventos (sem tocar em IPC)."""
    detector = detector if detector is not None else DetectorDeEnergia()
    eventos: list[EventoDeTrilha] = []
    quadros = 0
    amostras = 0
    fonte.abrir()
    try:
        for quadro in fonte.quadros():
            quadros += 1
            amostras += quadro.n_amostras
            mudou = detector.ver(quadro)
            if mudou is None:
                continue
            envelope = atividade(
                session_id=session_id,
                epoch=epoch,
                device_id=fonte.device_id,
                fala=mudou,
                energia_db=quadro.energia_db,
                ts_mono_ns=quadro.ts_mono_ns,
            )
            eventos.append(EventoDeTrilha.de_envelope(envelope))
    finally:
        fonte.fechar()
    return Reproducao(eventos=eventos, quadros=quadros, amostras=amostras)
