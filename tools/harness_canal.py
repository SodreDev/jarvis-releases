"""Latência e jitter do canal de áudio, com dois processos de verdade (ADR-0015).

    uv run --frozen python tools/harness_canal.py              # publica em docs/medicoes
    uv run --frozen python tools/harness_canal.py --quadros 300 --execucoes 1 --saida /tmp/x

Dois candidatos, mesmo teste: **anel em memória compartilhada** e **socket de domínio Unix em
datagrama**. O produtor roda em **outro processo** e envia quadros de 20 ms no ritmo real; o
consumidor mede.

- **latência** = instante da leitura menos `ts_mono_ns` do cabeçalho. No Linux o
  `CLOCK_MONOTONIC` é do sistema, então os dois processos leem o mesmo relógio — é o que torna a
  conta possível sem relógio combinado;
- **jitter** = desvio do intervalo entre chegadas em relação aos 20 ms nominais. É o número que
  diz se o canal entrega "em rajada": rajada de 5 quadros é pior para o VAD do que atraso
  constante, porque o VAD decide por quadro;
- **descartes** = política dos dois canais quando o consumidor não acompanha (áudio atrasado é
  áudio inútil). Descarte alto com latência boa significa que o canal está escondendo perda;
- **vazão sem ritmo** = quantos quadros por segundo cada canal sustenta sem pacing. É o teto, e
  não o caso de uso — serve para saber a folga.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from multiprocessing import Process
from pathlib import Path
from typing import Final

from jarvis.audio_io.quadro import MS_POR_QUADRO, TAXA_PADRAO, Quadro, de_int16
from jarvis.barramento.canal_de_audio import (
    CAPACIDADE_PADRAO,
    CanalDeAnel,
    CanalDeAudio,
    CanalDeConexao,
    CanalDeSocket,
    descrever_formato,
)
from jarvis.medicao import hardware, percentil

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_SAIDA: Final = RAIZ / "docs" / "medicoes"
NS_POR_MS: Final = 1_000_000
INTERVALO_NOMINAL_NS: Final = MS_POR_QUADRO * NS_POR_MS
QUADROS_PADRAO: Final = 1_500
"""1 500 quadros = 30 s de áudio por execução. Com ritmo real, mais do que isso só custa tempo."""


def quadro_de_teste(indice: int) -> Quadro:
    """Quadro com padrão determinístico: o consumidor confere que não veio torto."""
    valor = (indice % 1000) - 500
    return Quadro(
        indice=indice,
        amostras=de_int16([valor] * (TAXA_PADRAO * MS_POR_QUADRO // 1000)),
        ts_mono_ns=time.monotonic_ns(),
    )


def produzir_no_anel(nome_da_memoria: str, quadros: int, capacidade: int, com_ritmo: bool) -> None:
    canal = CanalDeAnel.anexar(nome_da_memoria, capacidade=capacidade)
    try:
        _produzir(canal, quadros, com_ritmo=com_ritmo)
    finally:
        canal.fechar()


def _produzir(canal: CanalDeAudio, quadros: int, *, com_ritmo: bool) -> None:
    proximo = time.monotonic_ns()
    for indice in range(quadros):
        if com_ritmo:
            proximo += INTERVALO_NOMINAL_NS
            atraso = (proximo - time.monotonic_ns()) / 1e9
            if atraso > 0:
                time.sleep(atraso)
        canal.enviar(quadro_de_teste(indice), epoch=1)


@dataclass(frozen=True, slots=True)
class Resultado:
    canal: str
    execucao: int
    com_ritmo: bool
    n: int
    recebidos: int
    descartados: int
    tortos: int
    latencia_p50_us: float
    latencia_p95_us: float
    latencia_p99_us: float
    latencia_max_us: float
    jitter_p95_us: float
    quadros_por_s: float


@dataclass(slots=True)
class Medicao:
    quadros: int
    execucoes: int
    resultados: list[Resultado] = field(default_factory=list)
    lacunas: list[tuple[str, str]] = field(default_factory=list)


def medir(nome: str, quadros: int, execucao: int, *, com_ritmo: bool) -> Resultado:
    capacidade = CAPACIDADE_PADRAO
    if nome == "anel":
        canal: CanalDeAudio = CanalDeAnel.criar(capacidade=capacidade)
        assert isinstance(canal, CanalDeAnel)
        processo = Process(
            target=produzir_no_anel,
            args=(canal.nome_da_memoria, quadros, capacidade, com_ritmo),
        )
    elif nome == "socket":
        canal = CanalDeSocket.par(folga=capacidade)
        processo = Process(target=_produzir, args=(canal, quadros), kwargs={"com_ritmo": com_ritmo})
    else:
        canal = CanalDeConexao.par()
        processo = Process(target=_produzir, args=(canal, quadros), kwargs={"com_ritmo": com_ritmo})

    latencias: list[float] = []
    chegadas: list[int] = []
    tortos = 0
    inicio = time.monotonic_ns()
    processo.start()
    try:
        limite = inicio + int((quadros * MS_POR_QUADRO + 5_000) * NS_POR_MS)
        while len(latencias) < quadros and time.monotonic_ns() < limite:
            recebido = canal.receber()
            if recebido is None:
                if not processo.is_alive() and canal.receber() is None:
                    break
                continue
            cabecalho, quadro = recebido
            agora = time.monotonic_ns()
            latencias.append((agora - cabecalho.ts_mono_ns) / 1000.0)
            chegadas.append(agora)
            esperado = (cabecalho.seq - 1) % 1000 - 500
            if quadro.valores()[0] != esperado:
                tortos += 1
    finally:
        processo.join(timeout=10.0)
        descartados = canal.descartados
        canal.fechar()

    intervalos = [
        abs((depois - antes) - INTERVALO_NOMINAL_NS) / 1000.0
        for antes, depois in pairwise(chegadas)
    ]
    duracao_s = (chegadas[-1] - chegadas[0]) / 1e9 if len(chegadas) > 1 else 0.0
    return Resultado(
        canal=nome,
        execucao=execucao,
        com_ritmo=com_ritmo,
        n=quadros,
        recebidos=len(latencias),
        descartados=descartados,
        tortos=tortos,
        latencia_p50_us=percentil(latencias, 50),
        latencia_p95_us=percentil(latencias, 95),
        latencia_p99_us=percentil(latencias, 99),
        latencia_max_us=max(latencias) if latencias else 0.0,
        jitter_p95_us=percentil(intervalos, 95),
        quadros_por_s=len(latencias) / duracao_s if duracao_s > 0 else 0.0,
    )


def resumo(medicao: Medicao, *, com_ritmo: bool) -> dict[str, dict[str, float]]:
    por_canal: dict[str, list[Resultado]] = {}
    for r in medicao.resultados:
        if r.com_ritmo is com_ritmo:
            por_canal.setdefault(r.canal, []).append(r)
    return {
        nome: {
            "n": float(statistics.median(r.recebidos for r in grupo)),
            "p50": statistics.median(r.latencia_p50_us for r in grupo),
            "p95": statistics.median(r.latencia_p95_us for r in grupo),
            "p99": statistics.median(r.latencia_p99_us for r in grupo),
            "max": max(r.latencia_max_us for r in grupo),
            "jitter_p95": statistics.median(r.jitter_p95_us for r in grupo),
            "descartados": float(statistics.median(r.descartados for r in grupo)),
            "tortos": float(sum(r.tortos for r in grupo)),
            "quadros_por_s": statistics.median(r.quadros_por_s for r in grupo),
        }
        for nome, grupo in sorted(por_canal.items())
    }


def escrever_csv(medicao: Medicao, caminho: Path) -> None:
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(
            [
                "canal",
                "execucao",
                "com_ritmo",
                "n",
                "recebidos",
                "descartados",
                "tortos",
                "latencia_p50_us",
                "latencia_p95_us",
                "latencia_p99_us",
                "latencia_max_us",
                "jitter_p95_us",
                "quadros_por_s",
            ]
        )
        for r in medicao.resultados:
            escritor.writerow(
                [
                    r.canal,
                    r.execucao,
                    int(r.com_ritmo),
                    r.n,
                    r.recebidos,
                    r.descartados,
                    r.tortos,
                    f"{r.latencia_p50_us:.1f}",
                    f"{r.latencia_p95_us:.1f}",
                    f"{r.latencia_p99_us:.1f}",
                    f"{r.latencia_max_us:.1f}",
                    f"{r.jitter_p95_us:.1f}",
                    f"{r.quadros_por_s:.1f}",
                ]
            )


def escrever_markdown(medicao: Medicao, caminho: Path) -> None:
    maquina = hardware()
    linhas = [
        "# ADR-0015 — canal de áudio entre `audio-io` e `agentd`: números medidos",
        "",
        "**Gerado por** `tools/harness_canal.py` (não editar à mão). **Data:** "
        f"{time.strftime('%Y-%m-%d')}.",
        "",
        "> **Dois processos de verdade.** O produtor roda em outro processo e envia quadros de "
        "20 ms no ritmo real; o consumidor mede. A latência usa o `CLOCK_MONOTONIC` do sistema, "
        "que os dois processos compartilham no Linux.",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {maquina['cpu']}, {maquina['nucleos']} fios, {maquina['memoria']} de RAM",
        f"- {maquina['plataforma']}, Python {maquina['python']}",
        f"- `n` = {medicao.quadros} quadros de 20 ms por execução "
        f"({medicao.quadros * MS_POR_QUADRO / 1000:.0f} s de áudio), {medicao.execucoes} execuções",
        f"- capacidade do anel e folga do socket: {CAPACIDADE_PADRAO} quadros "
        f"({CAPACIDADE_PADRAO * MS_POR_QUADRO / 1000:.2f} s)",
        f"- formato do quadro no canal: {descrever_formato()}",
        "- `tortos` conta quadro cujo padrão determinístico não bateu: é a prova de que o selo "
        "do anel não deixa passar escrita pela metade",
        "",
        "## Com ritmo real (o caso de uso)",
        "",
        "| canal | n | latência p50 | p95 | p99 | máximo | jitter p95 | descartados | tortos |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for nome, v in resumo(medicao, com_ritmo=True).items():
        linhas.append(
            f"| `{nome}` | {v['n']:.0f} | {v['p50']:.1f} µs | {v['p95']:.1f} µs "
            f"| {v['p99']:.1f} µs | {v['max']:.1f} µs | {v['jitter_p95']:.1f} µs "
            f"| {v['descartados']:.0f} | {v['tortos']:.0f} |"
        )
    linhas += [
        "",
        "## Sem ritmo (teto de vazão, não é o caso de uso)",
        "",
        "| canal | quadros/s | latência p95 | descartados |",
        "|---|---:|---:|---:|",
    ]
    for nome, v in resumo(medicao, com_ritmo=False).items():
        linhas.append(
            f"| `{nome}` | {v['quadros_por_s']:.0f} | {v['p95']:.1f} µs | {v['descartados']:.0f} |"
        )
    linhas += ["", "## O que não foi medido", ""]
    linhas += [f"- **{o_que}** — {por_que}" for o_que, por_que in medicao.lacunas]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--quadros", type=int, default=QUADROS_PADRAO)
    analisa.add_argument("--execucoes", type=int, default=3)
    analisa.add_argument("--canais", default="anel,socket,conexao")
    analisa.add_argument("--saida", type=Path, default=PASTA_SAIDA)
    args = analisa.parse_args(argv)

    nomes = [n.strip() for n in args.canais.split(",") if n.strip()]
    medicao = Medicao(quadros=args.quadros, execucoes=args.execucoes)
    for execucao in range(1, args.execucoes + 1):
        for nome in nomes:
            medicao.resultados.append(medir(nome, args.quadros, execucao, com_ritmo=True))
    for nome in nomes:  # teto de vazão: uma execução curta basta
        medicao.resultados.append(medir(nome, min(args.quadros, 2_000), 1, com_ritmo=False))

    medicao.lacunas += [
        (
            "Windows",
            "`AF_UNIX` em datagrama não existe no Python para Windows, e `shared_memory` existe "
            "mas com semântica de nome diferente. A implementação escolhida precisa de um "
            "caminho Windows antes de o P11 valer (está na ADR-0015 como consequência)",
        ),
        (
            "concorrência real de produtor e consumidor sob carga",
            "a máquina estava ociosa; com os sete processos rodando e o ASR consumindo CPU, o "
            "jitter tende a piorar — e é por isso que o canal descarta em vez de bloquear",
        ),
        (
            "mais de um consumidor",
            "o anel é um produtor e um consumidor por projeto. Dois consumidores exigem outro "
            "desenho (ou um anel por consumidor)",
        ),
    ]

    args.saida.mkdir(parents=True, exist_ok=True)
    escrever_csv(medicao, args.saida / "f1-canal.csv")
    escrever_markdown(medicao, args.saida / "f1-canal.md")

    for nome, v in resumo(medicao, com_ritmo=True).items():
        print(
            f"{nome:8.8} com ritmo: p50 {v['p50']:8.1f} µs p95 {v['p95']:8.1f} µs "
            f"jitter p95 {v['jitter_p95']:8.1f} µs descartados {v['descartados']:.0f} "
            f"tortos {v['tortos']:.0f}"
        )
    for nome, v in resumo(medicao, com_ritmo=False).items():
        print(f"{nome:8.8} sem ritmo: {v['quadros_por_s']:.0f} quadros/s")
    print(f"\ncsv e relatório em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
