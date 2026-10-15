"""`agentd`: corretor do barramento, dono do epoch e percepção (cartões F0-03 e F1-05).

A regra que não pode esperar está em `jarvis.agentd.percepcao`: `speech_started` incrementa o
epoch e emite `Cancel` **antes** de qualquer transcrição, e a transcrição que sai depois já
nasce no epoch novo e atravessa os outros processos sem mudar de epoch. O ASR incremental
(F1-06) entra atrás dessa garantia, como encaixe da percepção.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jarvis.agentd.percepcao import Percepcao
from jarvis.barramento.corretor import Corretor
from jarvis.barramento.envelope import uuid7
from jarvis.barramento.epoch import DonoDoEpoch
from jarvis.barramento.log import LogDeEventos


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
