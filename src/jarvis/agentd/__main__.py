"""`agentd`: corretor do barramento, dono do epoch e percepção stub (cartão F0-03).

A percepção de verdade (AEC, VAD, ASR incremental, detector semântico de turno) é F1. Aqui o
esqueleto prova as regras que não podem esperar: `speech_started` incrementa o epoch e emite
`Cancel` **antes** de qualquer transcrição, e a transcrição que sai depois já nasce no epoch
novo e atravessa os outros processos sem mudar de epoch.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jarvis.barramento.corretor import Corretor
from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust, uuid7
from jarvis.barramento.epoch import DonoDoEpoch
from jarvis.barramento.log import LogDeEventos

TEXTO_SINTETICO = "qual é o status do esqueleto"


class Percepcao:
    """S1 do esqueleto: de `AudioActivity(speech)` sai um turno completo, determinístico."""

    def __init__(self, dono: DonoDoEpoch) -> None:
        self.dono = dono
        self.turnos = 0
        self.aec_ok = True

    def __call__(self, envelope: Envelope, _seq: int) -> list[Envelope]:
        if envelope.type is not Tipo.AUDIO_ACTIVITY:
            return []
        # Cartão F1-04: quem emite `Cancel` é o agentd (§3.2), inclusive o `aec_fail`. O
        # `audio-io` só relata o fato (`aec_ok`); a decisão de cancelar é daqui, e sem ela o
        # assistente continuaria falando sem referência e se interromperia sozinho.
        aec_ok = bool(envelope.payload["aec_ok"])
        if not aec_ok and self.aec_ok:
            self.aec_ok = False
            return [self.dono.fala_comecou(motivo="aec_fail")]
        self.aec_ok = aec_ok
        if not bool(envelope.payload["speech"]):
            return []
        if self.turnos > 0:
            return []  # o esqueleto fecha um turno só; F1 cuida de conversa de verdade
        self.turnos += 1
        cancelamento = self.dono.fala_comecou()  # regra 1: epoch sobe antes do ASR
        transcricao = Envelope(
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
        return [cancelamento, transcricao]


def main(argv: list[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(prog="jarvis.agentd")
    analisa.add_argument("--raiz", type=Path, required=True, help="pasta de execução da sessão")
    analisa.add_argument("--session-id", default="", help="uuid v7 da sessão (padrão: novo)")
    analisa.add_argument(
        "--parar-em",
        default="",
        help="encerra depois de registrar um evento deste tipo (usado pelo esqueleto)",
    )
    analisa.add_argument("--timeout", type=float, default=30.0, help="limite total em segundos")
    args = analisa.parse_args(argv)

    args.raiz.mkdir(parents=True, exist_ok=True)
    session_id = args.session_id or uuid7()
    dono = DonoDoEpoch(session_id=session_id)
    with LogDeEventos(args.raiz / "eventos.sqlite") as log:
        corretor = Corretor(
            raiz=args.raiz,
            session_id=session_id,
            log=log,
            dono=dono,
            percepcao=Percepcao(dono),
        )
        corretor.abrir()
        (args.raiz / "sessao").write_text(session_id, encoding="utf-8")
        try:
            _laco(corretor, log, parar_em=args.parar_em, limite=args.timeout)
        finally:
            corretor.fechar()
    return 0


def _laco(corretor: Corretor, log: LogDeEventos, *, parar_em: str, limite: float) -> None:
    import time

    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        corretor.passo(timeout=0.05)
        if parar_em and any(
            str(registro.envelope.type) == parar_em
            for registro in log.ler(session_id=corretor.session_id)
        ):
            corretor.passo(timeout=0.2)  # deixa a última entrega sair
            return


if __name__ == "__main__":
    sys.exit(main())
