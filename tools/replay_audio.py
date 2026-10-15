"""Injeta áudio na cascata, grava a trilha de eventos e compara trilhas (cartão F1-01).

    # gera a trilha de um WAV do corpus
    uv run --frozen python tools/replay_audio.py --wav corpus/turnos/audio/t-0001.wav \
        --trilha /tmp/a.jsonl

    # gera a trilha de um sinal sintético (mesma semente ⇒ mesma trilha)
    uv run --frozen python tools/replay_audio.py --sintetico --semente 7 --trilha /tmp/b.jsonl

    # acusa a primeira divergência entre duas trilhas
    uv run --frozen python tools/replay_audio.py --trilha /tmp/a.jsonl --comparar /tmp/b.jsonl

O relógio padrão é o **falso**: a trilha sai com tempo virtual, igual em toda execução, e é
isso que torna o determinismo verificável. `--relogio sistema` roda em tempo real (1 s de
áudio leva 1 s), que é o que serve para olhar o comportamento, não para comparar bytes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Final

from jarvis.audio_io import (
    DetectorDeEnergia,
    FonteDeArquivo,
    FonteDeAudio,
    FonteSintetica,
    reproduzir,
)
from jarvis.audio_io import (
    trilha as modulo_trilha,
)
from jarvis.barramento.envelope import uuid7
from jarvis.relogio import Relogio, RelogioDoSistema, RelogioFalso

RAIZ: Final = Path(__file__).resolve().parent.parent


def montar_fonte(args: argparse.Namespace, relogio: Relogio) -> FonteDeAudio:
    if args.wav is not None:
        return FonteDeArquivo(caminho=args.wav, relogio=relogio)
    return FonteSintetica(relogio=relogio, semente=args.semente)


def comparar(caminho_a: Path, caminho_b: Path) -> int:
    a = modulo_trilha.ler(caminho_a)
    b = modulo_trilha.ler(caminho_b)
    divergencia = modulo_trilha.comparar(a, b)
    if divergencia is None:
        print(f"trilhas iguais: {len(a)} evento(s) em {caminho_a.name} e {caminho_b.name}")
        return 0
    print(f"DIVERGÊNCIA entre {caminho_a.name} e {caminho_b.name} — {divergencia}")
    return 1


def main(argv: list[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--wav", type=Path, help="WAV PCM16 mono 16 kHz para injetar")
    analisa.add_argument(
        "--sintetico", action="store_true", help="usa a fonte sintética em vez de um WAV"
    )
    analisa.add_argument("--semente", type=int, default=0, help="semente da fonte sintética")
    analisa.add_argument("--trilha", type=Path, help="arquivo JSONL da trilha (saída ou entrada)")
    analisa.add_argument("--comparar", type=Path, help="compara --trilha com esta outra trilha")
    analisa.add_argument(
        "--relogio", choices=("falso", "sistema"), default="falso", help="relógio injetado"
    )
    analisa.add_argument(
        "--limiar-db",
        type=float,
        default=None,
        help="limiar do detector de energia (não é o VAD; veja jarvis.audio_io.energia)",
    )
    args = analisa.parse_args(argv)

    if args.comparar is not None:
        if args.trilha is None:
            analisa.error("--comparar precisa de --trilha para ter o que comparar")
        return comparar(args.trilha, args.comparar)

    if args.wav is None and not args.sintetico:
        analisa.error("escolha a entrada: --wav ARQUIVO ou --sintetico")

    relogio: Relogio = RelogioFalso() if args.relogio == "falso" else RelogioDoSistema()
    detector = (
        DetectorDeEnergia(limiar_db=args.limiar_db)
        if args.limiar_db is not None
        else DetectorDeEnergia()
    )
    reproducao = reproduzir(montar_fonte(args, relogio), session_id=uuid7(), detector=detector)

    if args.trilha is not None:
        modulo_trilha.escrever(args.trilha, reproducao.eventos)
        destino = args.trilha
        print(f"{len(reproducao.eventos)} evento(s) em {destino}")
    else:
        for evento in reproducao.eventos:
            print(evento.para_dict())
    print(
        f"quadros: {reproducao.quadros} ({reproducao.duracao_ms:.0f} ms), "
        f"amostras: {reproducao.amostras}, relógio: {args.relogio}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
