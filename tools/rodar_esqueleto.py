"""Sobe os sete processos, injeta um evento sintético e mostra a cadeia (cartão F0-03).

    uv run --frozen python tools/rodar_esqueleto.py --raiz /tmp/jarvis-esqueleto

Serve para ver o esqueleto funcionando sem ler teste: imprime o log do barramento na ordem,
com `seq`, tipo, origem, epoch e `trust`, e termina encerrando os filhos pelo PID registrado.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from jarvis.barramento.log import LogDeEventos
from jarvis.supervisao import PROCESSOS_CLIENTES, Supervisor


def main(argv: list[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--raiz", type=Path, default=None, help="pasta de execução")
    analisa.add_argument("--limite", type=float, default=20.0, help="segundos até desistir")
    args = analisa.parse_args(argv)

    temporaria = args.raiz is None
    raiz = Path(tempfile.mkdtemp(prefix="jarvis-esqueleto-")) if temporaria else args.raiz
    supervisor = Supervisor(raiz=raiz)
    try:
        supervisor.iniciar("agentd", "--parar-em", "StateRevision", "--timeout", str(args.limite))
        supervisor.esperar_barramento()
        for nome in PROCESSOS_CLIENTES:
            supervisor.iniciar(nome, "--timeout", str(args.limite))
        supervisor.iniciar("audio-io", "--emitir-fala", "--timeout", str(args.limite))

        filho = supervisor.filhos["agentd"]
        filho.wait(timeout=args.limite + 5)

        session_id = (raiz / "sessao").read_text(encoding="utf-8").strip()
        with LogDeEventos(raiz / "eventos.sqlite") as log:
            print(f"\nsessão {session_id} — log do barramento:\n")
            print(f"{'seq':>3}  {'tipo':20} {'origem':9} {'epoch':>5}  trust")
            for registro in log.ler(session_id=session_id):
                e = registro.envelope
                print(f"{registro.seq:>3}  {e.type:20.20} {e.source:9.9} {e.epoch:>5}  {e.trust}")
            print(f"\ncadeia de hash conferida: {log.verificar_cadeia()} registros")
        return 0
    finally:
        supervisor.parar_tudo()
        if temporaria:
            shutil.rmtree(raiz, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
