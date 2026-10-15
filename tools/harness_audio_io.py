"""Piso de software do `audio-io`: captura→`AudioActivity` e `Cancel`→fila vazia (F1-03).

    uv run --frozen python tools/harness_audio_io.py            # publica em docs/medicoes
    uv run --frozen python tools/harness_audio_io.py --quadros 2000 --execucoes 1 --saida /tmp/x

**É piso de software, sem dispositivo.** O que está medido aqui é o custo do *nosso* código no
caminho de 20 ms, sobre a fonte `arquivo` (um WAV, como o cartão pede). O que **não** está
medido, e não dá para medir sem hardware: jitter de captura, período e latência do driver,
latência do caminho de saída e cancelamento perceptível ao ouvido — a fila do driver não é a
nossa fila. Somar este piso com a lacuna de hardware e chamar de SLO-1 seria inventar número.

Por que o relógio da **fonte** é o falso e o do **cronômetro** é o real: a fonte ritma a
entrega em 20 ms, e esperar 20 ms de verdade 10 000 vezes mediria o `sleep` do sistema (e
levaria 200 s por execução). O tempo virtual entrega o quadro na hora; o `perf_counter_ns`
mede só o nosso trabalho em cima dele.

Para o caminho de evento ter `n` de verdade, o áudio é de 20 ms alternados (fala/silêncio), o
que força **um evento por quadro**. É pior caso declarado, não uso típico: em fala real o
`AudioActivity` sai nas transições.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
import wave
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from jarvis.audio_io import (
    BYTES_POR_AMOSTRA,
    TAXA_PADRAO,
    Captura,
    DetectorDeEnergia,
    FilaDePlayback,
    FonteDeArquivo,
    Pedaco,
    SumidouroEmMemoria,
    TipoDeTrecho,
    Trecho,
    gerar,
)
from jarvis.barramento.envelope import uuid7
from jarvis.medicao import hardware, percentil
from jarvis.relogio import RelogioFalso

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_SAIDA: Final = RAIZ / "docs" / "medicoes"
ETIQUETA: Final = "piso de software, sem dispositivo"
MS_DE_FILA_PARA_CANCELAR: Final = 2000.0


@dataclass(frozen=True, slots=True)
class Braco:
    """Um caminho medido, numa execução."""

    nome: str
    execucao: int
    n: int
    media_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    observacao: str = ""


@dataclass(slots=True)
class Medicao:
    quadros: int
    execucoes: int
    resultados: list[Braco] = field(default_factory=list)
    lacunas: list[tuple[str, str]] = field(default_factory=list)


def de_tempos(nome: str, execucao: int, tempos: list[float], observacao: str = "") -> Braco:
    return Braco(
        nome=nome,
        execucao=execucao,
        n=len(tempos),
        media_ms=statistics.mean(tempos) if tempos else 0.0,
        p50_ms=percentil(tempos, 50),
        p95_ms=percentil(tempos, 95),
        p99_ms=percentil(tempos, 99),
        max_ms=max(tempos) if tempos else 0.0,
        observacao=observacao,
    )


def escrever_wav(caminho: Path, quadros: int, *, alternado: bool) -> None:
    """WAV de 20 ms alternados (um evento por quadro) ou de silêncio (nenhum evento)."""
    if alternado:
        roteiro = tuple(
            Trecho(TipoDeTrecho.FALA if i % 2 else TipoDeTrecho.SILENCIO, 20.0)
            for i in range(quadros)
        )
    else:
        roteiro = (Trecho(TipoDeTrecho.SILENCIO, 20.0 * quadros),)
    amostras = gerar(roteiro, semente=20_261_015)
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(BYTES_POR_AMOSTRA)
        arquivo.setframerate(TAXA_PADRAO)
        arquivo.writeframes(amostras)


def medir_captura(caminho: Path, execucao: int, *, nome: str, observacao: str) -> Braco:
    """Tempo de `tick` sobre um WAV. O que o braço mede depende do áudio que entra."""
    relogio = RelogioFalso()
    captura = Captura(
        fonte=FonteDeArquivo(caminho=caminho, relogio=relogio),
        relogio=relogio,
        session_id=uuid7(),
        detector=DetectorDeEnergia(),
    )
    captura.abrir()
    tempos: list[float] = []
    try:
        while True:
            vistos = captura.quadros
            antes = time.perf_counter_ns()
            captura.tick()
            gasto = (time.perf_counter_ns() - antes) / 1e6
            if captura.quadros == vistos:
                break  # fonte esgotada: o tick não consumiu quadro
            tempos.append(gasto)
    finally:
        captura.fechar()
    return de_tempos(nome, execucao, tempos, observacao)


def medir_cancelamento(execucao: int, repeticoes: int) -> tuple[Braco, Braco]:
    """Tempo de esvaziar 2 s de fila no mesmo tick, e o erro de `played_ms` em ms."""
    audio = gerar(semente=7)
    alvo = int(TAXA_PADRAO * MS_DE_FILA_PARA_CANCELAR / 1000) * BYTES_POR_AMOSTRA
    pedaco_longo = (audio * (alvo // len(audio) + 1))[:alvo]
    tempos: list[float] = []
    erros: list[float] = []
    for _ in range(repeticoes):
        sumidouro = SumidouroEmMemoria()
        fila = FilaDePlayback(sumidouro=sumidouro, session_id=uuid7())
        for i in range(10):
            fatia = pedaco_longo[i * (alvo // 10) : (i + 1) * (alvo // 10)]
            fila.enfileirar(Pedaco(chunk_id=f"k-{i}", epoch=0, amostras=fatia))
        for _ in range(5):  # 100 ms tocados antes do barge-in
            fila.tick()

        antes = time.perf_counter_ns()
        cancelamento = fila.cancelar(reason="barge_in")
        tempos.append((time.perf_counter_ns() - antes) / 1e6)

        consumido_ms = 1000 * sumidouro.amostras_consumidas / TAXA_PADRAO
        erros.append(abs(cancelamento.played_ms - consumido_ms))
    return (
        de_tempos(
            "Cancel→fila vazia",
            execucao,
            tempos,
            f"{MS_DE_FILA_PARA_CANCELAR:.0f} ms enfileirados em 10 pedaços, esvaziados na chamada",
        ),
        de_tempos(
            "erro de played_ms (ms)",
            execucao,
            erros,
            "diferença entre o played_ms do evento e as amostras consumidas pelo sumidouro",
        ),
    )


def resumo_por_braco(medicao: Medicao) -> dict[str, dict[str, float]]:
    """Mediana entre execuções, por braço — é o que vai para a tabela."""
    por_nome: dict[str, list[Braco]] = {}
    for resultado in medicao.resultados:
        por_nome.setdefault(resultado.nome, []).append(resultado)
    return {
        nome: {
            "n": float(statistics.median(r.n for r in grupo)),
            "p50": statistics.median(r.p50_ms for r in grupo),
            "p95": statistics.median(r.p95_ms for r in grupo),
            "p99": statistics.median(r.p99_ms for r in grupo),
            "max": max(r.max_ms for r in grupo),
        }
        for nome, grupo in por_nome.items()
    }


def escrever_csv(medicao: Medicao, caminho: Path) -> None:
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(
            ["braco", "execucao", "n", "media_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms"]
        )
        for r in medicao.resultados:
            escritor.writerow(
                [
                    r.nome,
                    r.execucao,
                    r.n,
                    f"{r.media_ms:.6f}",
                    f"{r.p50_ms:.6f}",
                    f"{r.p95_ms:.6f}",
                    f"{r.p99_ms:.6f}",
                    f"{r.max_ms:.6f}",
                ]
            )


def escrever_markdown(medicao: Medicao, caminho: Path) -> None:
    maquina = hardware()
    resumo = resumo_por_braco(medicao)
    linhas = [
        "# F1-03 — piso de software do `audio-io`: números medidos",
        "",
        "**Gerado por** `tools/harness_audio_io.py` (não editar à mão). **Data:** "
        f"{time.strftime('%Y-%m-%d')}.",
        "",
        f"> **{ETIQUETA}.** Nenhum dispositivo de áudio foi aberto: a fonte é um WAV e o "
        "sumidouro é memória.",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {maquina['cpu']}, {maquina['nucleos']} fios, {maquina['memoria']} de RAM",
        f"- {maquina['plataforma']}, Python {maquina['python']}",
        f"- {medicao.quadros} quadros de 20 ms por execução "
        f"({medicao.quadros * 20 / 1000:.0f} s de áudio), {medicao.execucoes} execuções",
        "- fonte `arquivo` (WAV PCM16 mono 16 kHz) com 20 ms de fala e 20 ms de silêncio "
        "alternados, o que força **um evento por quadro**: é pior caso declarado, não uso "
        "típico",
        "- o relógio da fonte é o **falso** (tempo virtual: a espera de 20 ms não entra na "
        "conta) e o cronômetro é `time.perf_counter_ns` (tempo real do nosso código)",
        "- `captura→AudioActivity` mede energia + detector de limiar + envelope da §3.1 + "
        "validação na borda do contrato. O detector **não** é o VAD (o `silero-vad` é o "
        "cartão F1-05): o número do VAD está em `f0-04-captura.md`",
        "",
        "## Resultado por caminho (mediana das execuções)",
        "",
        "| caminho | n | p50 (ms) | p95 (ms) | p99 (ms) | máximo (ms) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for nome, valores in resumo.items():
        linhas.append(
            f"| `{nome}` | {valores['n']:.0f} | {valores['p50']:.4f} | {valores['p95']:.4f} "
            f"| {valores['p99']:.4f} | {valores['max']:.4f} |"
        )
    linhas += ["", "## O que não foi medido", ""]
    linhas += [f"- **{o_que}** — {por_que}" for o_que, por_que in medicao.lacunas]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--quadros", type=int, default=10_000, help="quadros de 20 ms (n)")
    analisa.add_argument("--execucoes", type=int, default=3)
    analisa.add_argument("--cancelamentos", type=int, default=1_000)
    analisa.add_argument(
        "--saida",
        type=Path,
        default=PASTA_SAIDA,
        help="onde publicar (padrão: docs/medicoes; o teste de fumaça usa pasta temporária)",
    )
    args = analisa.parse_args(argv)

    medicao = Medicao(quadros=args.quadros, execucoes=args.execucoes)
    with TemporaryDirectory(prefix="jarvis-f1-03-") as temporario:
        alternado = Path(temporario) / "alternado.wav"
        silencio = Path(temporario) / "silencio.wav"
        escrever_wav(alternado, args.quadros, alternado=True)
        escrever_wav(silencio, args.quadros, alternado=False)
        for execucao in range(1, args.execucoes + 1):
            medicao.resultados.append(
                medir_captura(
                    alternado,
                    execucao,
                    nome="captura→AudioActivity",
                    observacao=(
                        "energia, detector, envelope da §3.1 e validação na borda do contrato "
                        "(áudio alternado de 20 ms: um evento por quadro)"
                    ),
                )
            )
            medicao.resultados.append(
                medir_captura(
                    silencio,
                    execucao,
                    nome="quadro→decisão (sem evento)",
                    observacao="energia e detector só, sobre silêncio: nenhum evento sai",
                )
            )
            medicao.resultados.extend(medir_cancelamento(execucao, args.cancelamentos))

    medicao.lacunas += [
        (
            "jitter de captura, xruns, período e latência do driver",
            "exigem dispositivo real; nada disso foi aberto por este harness (F1-16, na "
            "máquina do dono)",
        ),
        (
            "latência do caminho de saída e cancelamento perceptível ao ouvido",
            "a fila do driver não é a nossa fila: esvaziar a nossa em 0,0x ms não garante que "
            "o alto-falante parou (F1-10 piso, F1-16 aceite)",
        ),
        (
            "SLO-1 de verdade",
            "este é o piso do nosso código sobre arquivo; o SLO-1 é do microfone ao evento, "
            "com AEC (F1-04) e VAD (F1-05) no caminho",
        ),
        ("Windows", "o harness é portável (só biblioteca padrão), mas rodou só em Linux"),
    ]

    args.saida.mkdir(parents=True, exist_ok=True)
    escrever_csv(medicao, args.saida / "f1-03-audio-io.csv")
    escrever_markdown(medicao, args.saida / "f1-03-audio-io.md")

    print(f"\n{'caminho':30} {'n':>7} {'p50':>9} {'p95':>9} {'p99':>9} {'máx':>9}")
    for nome, valores in resumo_por_braco(medicao).items():
        print(
            f"{nome:30.30} {valores['n']:7.0f} {valores['p50']:9.4f} {valores['p95']:9.4f} "
            f"{valores['p99']:9.4f} {valores['max']:9.4f}"
        )
    for o_que, _ in medicao.lacunas:
        print(f"não medido: {o_que}")
    print(f"\ncsv e relatório em {args.saida} ({ETIQUETA})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
