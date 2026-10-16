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

from jarvis.agentd.aviso import falar_aviso
from jarvis.agentd.percepcao import Percepcao
from jarvis.barramento.canal_de_audio import CanalDeConexao
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
    analisa.add_argument(
        "--muitos-turnos",
        action="store_true",
        help=(
            "deixa a percepção fechar mais de um turno. O esqueleto fecha UM (F0-03) para a "
            "cadeia dos sete processos ser determinística; conversa de verdade é F1/F2, e o "
            "F1-14 precisa de um segundo turno para provar o pedido que cai com a rede fora"
        ),
    )
    analisa.add_argument(
        "--canal-de-audio",
        action="store_true",
        help=(
            "escuta o canal de áudio do audio-io (ADR-0015). Sem ele, o agentd só recebe "
            "decisões pelo barramento, que é o esqueleto do F0-03"
        ),
    )
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
            percepcao=Percepcao(dono, um_turno_so=not args.muitos_turnos),
        )
        corretor.abrir()
        (args.raiz / "sessao").write_text(session_id, encoding="utf-8")
        canal = CanalDeConexao.escutar(args.raiz) if args.canal_de_audio else None
        try:
            _laco(
                corretor,
                log,
                parar_em=args.parar_em,
                limite=args.timeout,
                canal=canal,
                dono=dono,
                raiz=args.raiz,
            )
        finally:
            if canal is not None:
                canal.fechar()
            corretor.fechar()
    return 0


def _laco(
    corretor: Corretor,
    log: LogDeEventos,
    *,
    parar_em: str,
    limite: float,
    canal: CanalDeConexao | None = None,
    dono: DonoDoEpoch | None = None,
    raiz: Path | None = None,
) -> None:
    import time

    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        corretor.passo(timeout=0.05)
        if canal is not None:
            _consumir_audio(canal, dono=dono, raiz=raiz)
        if raiz is not None:
            # Cartão F1-14: quem tem o TTS é o `agentd`, então é ele que diz o aviso de
            # degradação — e `falar_aviso` devolve `None` depois da primeira vez.
            falar_aviso(
                raiz,
                session_id=corretor.session_id,
                epoch=dono.epoch_atual if dono is not None else 0,
            )
        if parar_em and any(
            str(registro.envelope.type) == parar_em
            for registro in log.ler(session_id=corretor.session_id)
        ):
            corretor.passo(timeout=0.2)  # deixa a última entrega sair
            return


def _consumir_audio(canal: CanalDeConexao, *, dono: DonoDoEpoch | None, raiz: Path | None) -> int:
    """Drena os quadros que chegaram pelo canal, descartando os de epoch morto.

    O `agentd` consome quadro para a percepção que **precisa de áudio** (ASR incremental do
    F1-06, detector de turno do F1-07). Aqui ele conta e descarta o que não serve: o número
    fica num arquivo da pasta de sessão, do mesmo jeito que `pronto` e `sessao`, porque é assim
    que o supervisor e os testes observam o processo sem inventar evento no barramento.
    """
    epoch_minimo = dono.epoch_atual if dono is not None else 0
    consumidos = 0
    while canal.receber(epoch_minimo=epoch_minimo) is not None:
        consumidos += 1
    if consumidos and raiz is not None:
        (raiz / "quadros-de-audio").write_text(
            f"{canal.recebidos} {canal.descartados}", encoding="utf-8"
        )
    return consumidos


if __name__ == "__main__":
    sys.exit(main())
