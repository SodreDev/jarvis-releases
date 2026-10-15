"""Stub determinístico do `audio-io` (cartão F0-03): emite atividade e progresso sintéticos.

Sem placa de som, sem AEC e sem TTS — isso é F1. O que o esqueleto prova é a fronteira: o
`audio-io` é quem recebe do mundo (daí o `trust` vir da fronteira do microfone) e quem relata
`played_ms` real; ele não decide turno e não fala com LLM.
"""

from __future__ import annotations

import sys
import time

from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust
from jarvis.processo import Processo, analisador

DISPOSITIVO_SINTETICO = "sintetico:0"


def atividade(processo: Processo, *, fala: bool) -> Envelope:
    return Envelope(
        session_id=processo.session_id,
        epoch=processo.epoch,
        source="audio-io",
        trust=Trust.USER_VOICE,
        priority=Prioridade.P0 if fala else Prioridade.P1,
        type=Tipo.AUDIO_ACTIVITY,
        payload={
            "speech": fala,
            "device_id": DISPOSITIVO_SINTETICO,
            "energy_db": -18.0 if fala else -60.0,
            "aec_ok": True,
        },
    )


def reagir(_processo: Processo, _envelope: Envelope, _veredito: str) -> list[Envelope]:
    return []  # no esqueleto o audio-io só esvazia playback, que não existe ainda


def main(argv: list[str] | None = None) -> int:
    analisa = analisador("audio-io")
    analisa.add_argument(
        "--emitir-fala",
        action="store_true",
        help="publica um AudioActivity(speech=True) sintético ao conectar (cartão F0-03)",
    )
    args = analisa.parse_args(argv)
    processo = Processo(nome="audio-io", raiz=args.raiz, reacao=reagir)
    processo.abrir()
    try:
        if args.emitir_fala:
            time.sleep(0.2)  # dá tempo de os outros seis se registrarem
            processo.publicar(atividade(processo, fala=True))
        processo.rodar(timeout=args.timeout)
    finally:
        processo.fechar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
