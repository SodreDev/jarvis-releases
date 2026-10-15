"""Custo da decisão do S1, com n ≥ 10 000 (cartão F1-08, aceite (b)).

    uv run --frozen python tools/harness_s1.py
    uv run --frozen python tools/harness_s1.py --n 2000 --saida /tmp/x

Mede o que o S1 gasta para decidir, por linha da tabela e no total, e compara com o teto de
100 ms da §2. **Não depende de hardware nenhum**: a tabela é dado, o estado é dado, e por isso
este cartão é 100% verificável sem microfone — o relatório pode afirmar isso sem ressalva.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.agentd.s1 import S1, TETO_MS, Acao, EstadoS1, Tabela
from jarvis.medicao import hardware, percentil

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_SAIDA: Final = RAIZ / "docs" / "medicoes"

ESTADOS: Final[tuple[tuple[str, EstadoS1], ...]] = (
    ("orçamento estourado", EstadoS1(orcamento_estourado=True)),
    ("epoch morto", EstadoS1(epoch_atual=5, epoch_do_evento=4, decisao_de_turno="yield")),
    ("aec_fail", EstadoS1(aec_ok=False, tocando=True)),
    ("barge-in curto", EstadoS1(fala_do_dono=True, tocando=True, duracao_fala_ms=120.0)),
    ("barge-in", EstadoS1(fala_do_dono=True, tocando=True, duracao_fala_ms=900.0)),
    (
        "backchannel",
        EstadoS1(
            fala_do_dono=True,
            tocando=False,
            duracao_fala_ms=5000.0,
            p_eot=0.1,
            decisao_de_turno="hold",
        ),
    ),
    ("nossa vez", EstadoS1(fala_do_dono=False, tocando=False, decisao_de_turno="yield")),
    ("sem confiança", EstadoS1(fala_do_dono=False, decisao_de_turno="unknown", p_eot=0.5)),
    ("esperando", EstadoS1(fala_do_dono=False, decisao_de_turno="hold")),
)


@dataclass(frozen=True, slots=True)
class Braco:
    cenario: str
    linha: str
    acao: str
    n: int
    p50_us: float
    p95_us: float
    p99_us: float
    max_us: float


@dataclass(slots=True)
class Medicao:
    n: int
    bracos: list[Braco] = field(default_factory=list)


def medir(s1: S1, estado: EstadoS1, n: int) -> tuple[list[float], str, Acao]:
    tempos: list[float] = []
    decisao = s1.decidir(estado)
    for _ in range(n):
        antes = time.perf_counter_ns()
        s1.decidir(estado)
        tempos.append((time.perf_counter_ns() - antes) / 1000.0)
    return tempos, decisao.linha, decisao.acao


def escrever_csv(medicao: Medicao, caminho: Path) -> None:
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(["cenario", "linha", "acao", "n", "p50_us", "p95_us", "p99_us", "max_us"])
        for b in medicao.bracos:
            escritor.writerow(
                [
                    b.cenario,
                    b.linha,
                    b.acao,
                    b.n,
                    f"{b.p50_us:.3f}",
                    f"{b.p95_us:.3f}",
                    f"{b.p99_us:.3f}",
                    f"{b.max_us:.3f}",
                ]
            )


def escrever_markdown(medicao: Medicao, caminho: Path, *, tabela: Tabela) -> None:
    maquina = hardware()
    pior = max((b.p95_us for b in medicao.bracos), default=0.0)
    linhas = [
        "# F1-08 — S1: custo da decisão e o orçamento de 20–100 ms",
        "",
        "**Gerado por** `tools/harness_s1.py` (não editar à mão). **Data:** "
        f"{time.strftime('%Y-%m-%d')}.",
        "",
        "> **Este cartão não depende de hardware.** A tabela é dado, o estado é dado: tudo aqui "
        "é verificável sem microfone, e esta é a única medição da F1 que pode dizer isso sem "
        "ressalva.",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {maquina['cpu']}, {maquina['nucleos']} fios, {maquina['memoria']} de RAM",
        f"- {maquina['plataforma']}, Python {maquina['python']}",
        f"- {medicao.n} decisões por cenário (n total = {medicao.n * len(medicao.bracos)})",
        f"- tabela `tabelas/s1.v1.json` versão {tabela.versao}, {len(tabela.linhas)} linhas",
        f"- teto do orçamento da §2: **{TETO_MS:.0f} ms**",
        "",
        "## Custo por cenário",
        "",
        "| cenário | linha | ação | n | p50 | p95 | p99 | máximo |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for b in medicao.bracos:
        linhas.append(
            f"| {b.cenario} | `{b.linha}` | `{b.acao}` | {b.n} | {b.p50_us:.2f} µs "
            f"| {b.p95_us:.2f} µs | {b.p99_us:.2f} µs | {b.max_us:.2f} µs |"
        )
    linhas += [
        "",
        f"**Pior p95 medido: {pior:.2f} µs** — {pior / 1000 / TETO_MS:.5%} do teto de "
        f"{TETO_MS:.0f} ms. O orçamento do S1 não é gasto pela tabela: ele é gasto pelo que vem "
        "antes dela (captura, AEC, VAD, ASR), e é por isso que a guarda existe — estourar o "
        "teto cai em `ouvir`, nunca em `falar`.",
        "",
        "## O que não foi medido",
        "",
        "- **nada depende de hardware aqui** — o cartão é fechável sem microfone, por projeto;",
        "- o custo do que **chega** ao S1 (captura → AEC → VAD → ASR → detector) está nos "
        "relatórios dos cartões F1-03 a F1-07;",
        "- Windows: o código é só biblioteca padrão, mas a medição rodou em Linux.",
    ]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument(
        "--n", type=int, default=10_000, help="decisões por cenário (o aceite pede ≥ 10 000)"
    )
    analisa.add_argument("--saida", type=Path, default=PASTA_SAIDA)
    args = analisa.parse_args(argv)

    tabela = Tabela.do_arquivo()
    s1 = S1(tabela=tabela)
    medicao = Medicao(n=args.n)
    for cenario, estado in ESTADOS:
        tempos, linha, acao = medir(s1, estado, args.n)
        medicao.bracos.append(
            Braco(
                cenario=cenario,
                linha=linha,
                acao=str(acao),
                n=len(tempos),
                p50_us=percentil(tempos, 50),
                p95_us=percentil(tempos, 95),
                p99_us=percentil(tempos, 99),
                max_us=max(tempos),
            )
        )

    args.saida.mkdir(parents=True, exist_ok=True)
    escrever_csv(medicao, args.saida / "f1-08-s1.csv")
    escrever_markdown(medicao, args.saida / "f1-08-s1.md", tabela=tabela)

    for b in medicao.bracos:
        print(
            f"{b.cenario:22.22} {b.linha:5.5} {b.acao:12.12} "
            f"p50 {b.p50_us:7.2f} µs p95 {b.p95_us:7.2f} µs"
        )
    print(f"\ntotal de decisões: {sum(b.n for b in medicao.bracos)}")
    print(f"média do p95: {statistics.mean(b.p95_us for b in medicao.bracos):.2f} µs")
    print(f"csv e relatório em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
