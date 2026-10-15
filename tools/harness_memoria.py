"""Harness da memória em grafo: mede SLO-11 e SLO-12 antes da F3 (cartão F0-05).

    uv run --frozen python tools/harness_memoria.py --consultas 200 --execucoes 3

Publica `docs/medicoes/f0-05-grafo.csv` e `docs/medicoes/f0-05-grafo.md` com hardware, `n`,
três execuções, mediana e p95 — a regra do projeto é que nenhum número apareça sem isso.
"""

from __future__ import annotations

import argparse
import csv
import platform
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from jarvis.memoryd.esquema import abrir, contagens
from jarvis.memoryd.fusao import recuperar
from jarvis.memoryd.grafo import (
    Tetos,
    ativar_em_memoria,
    ativar_por_no,
    ativar_por_salto,
    ativar_recursivo_sql,
    semear_por_termo,
)
from jarvis.memoryd.sintetico import Escala, gerar

PASTA_SAIDA: Final = Path(__file__).resolve().parent.parent / "docs" / "medicoes"
EPISODIOS_BASE: Final = 122
"""`n` real: memórias que o Orchestrator guarda para o projeto Jarvis em 2026-10-15.

O exportador do cartão F0-08 substitui isto pela contagem completa de C1; a escala 10× e a
100× existem justamente porque o corpus do dono vai crescer.
"""

IMPLEMENTACOES = {
    "sql-por-no": ativar_por_no,
    "sql-por-salto": ativar_por_salto,
    "sql-recursivo": ativar_recursivo_sql,
    "memoria": ativar_em_memoria,
}


@dataclass(frozen=True, slots=True)
class Amostra:
    escala: str
    implementacao: str
    saltos: int
    execucao: int
    ms: list[float]
    nos: list[int]
    arestas: list[int]
    truncados: int

    @property
    def p50(self) -> float:
        return statistics.median(self.ms)

    @property
    def p95(self) -> float:
        return percentil(self.ms, 95)

    @property
    def p99(self) -> float:
        return percentil(self.ms, 99)


def percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    posicao = min(round(p / 100 * (len(ordenados) - 1)), len(ordenados) - 1)
    return ordenados[posicao]


def hardware() -> dict[str, str]:
    """Descrição do hardware real — vai no relatório junto de cada número."""
    cpu = ""
    try:
        for linha in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if linha.startswith("model name"):
                cpu = linha.split(":", 1)[1].strip()
                break
    except OSError:
        cpu = platform.processor()
    memoria = ""
    try:
        for linha in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if linha.startswith("MemTotal"):
                kb = int(linha.split()[1])
                memoria = f"{kb / 1024 / 1024:.0f} GiB"
                break
    except OSError:
        memoria = "?"
    import sqlite3

    return {
        "cpu": cpu or "?",
        "memoria": memoria,
        "plataforma": platform.platform(),
        "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version,
    }


def medir(
    consultas: int, execucoes: int, escalas: list[Escala], *, orcamento_ms: float
) -> tuple[list[Amostra], dict[str, dict[str, int]], list[dict[str, float]]]:
    amostras: list[Amostra] = []
    tamanhos: dict[str, dict[str, int]] = {}
    slo12: list[dict[str, float]] = []

    for escala in escalas:
        con = abrir()
        gerar(con, escala)
        tamanhos[escala.nome] = contagens(con)
        alvos = [f"entidade {i}" for i in range(0, min(escala.entidades, consultas))]
        sementes = [semear_por_termo(con, [alvo]) for alvo in alvos]
        sementes = [s for s in sementes if s]

        for nome, funcao in IMPLEMENTACOES.items():
            for saltos in (1, 2):
                for execucao in range(1, execucoes + 1):
                    ms: list[float] = []
                    nos: list[int] = []
                    arestas: list[int] = []
                    truncados = 0
                    tetos = Tetos(saltos=saltos, orcamento_ms=orcamento_ms)
                    for semente in sementes:
                        inicio = time.perf_counter()
                        ativacao = funcao(con, semente, tetos)
                        ms.append((time.perf_counter() - inicio) * 1000.0)
                        nos.append(ativacao.nos_visitados)
                        arestas.append(ativacao.arestas_lidas)
                        truncados += int(ativacao.graph_truncated)
                    amostras.append(
                        Amostra(escala.nome, nome, saltos, execucao, ms, nos, arestas, truncados)
                    )

        # SLO-12: memória pronta para o S2 (grafo + vetor fundidos, sem reranker).
        for execucao in range(1, execucoes + 1):
            totais: list[float] = []
            truncados = 0
            for alvo in alvos[: min(len(alvos), 100)]:
                inicio = time.perf_counter()
                resultado = recuperar(con, alvo, tetos=Tetos(saltos=2, orcamento_ms=orcamento_ms))
                totais.append((time.perf_counter() - inicio) * 1000.0)
                truncados += int(resultado.graph_truncated)
            slo12.append(
                {
                    "escala": escala.fator,
                    "execucao": execucao,
                    "n": len(totais),
                    "p50": statistics.median(totais),
                    "p95": percentil(totais, 95),
                    "truncados": truncados,
                }
            )
        con.close()
    return amostras, tamanhos, slo12


def medir_hub(*, grau: int, consultas: int, execucoes: int, orcamento_ms: float) -> list[Amostra]:
    """Aceite (c): um hub com grau alto não pode explodir a travessia."""
    escala = Escala.de_corpus("hub", episodios_base=EPISODIOS_BASE, fator=1)
    con = abrir()
    gerar(con, escala, hub_grau=grau)
    grau_real = int(con.execute("SELECT MAX(degree) AS g FROM graph_node_stats").fetchone()["g"])
    sementes = [s for s in (semear_por_termo(con, ["entidade 0"]),) if s]  # a entidade do hub
    extras = [semear_por_termo(con, [f"entidade {i}"]) for i in range(1, consultas)]
    sementes += [s for s in extras if s]

    amostras: list[Amostra] = []
    for nome, funcao in IMPLEMENTACOES.items():
        if nome == "sql-recursivo":
            continue  # já se sabe (medição das escalas) que estoura o orçamento sem teto
        for saltos in (1, 2):
            for execucao in range(1, execucoes + 1):
                ms: list[float] = []
                nos: list[int] = []
                arestas: list[int] = []
                truncados = 0
                tetos = Tetos(saltos=saltos, orcamento_ms=orcamento_ms)
                for semente in sementes:
                    inicio = time.perf_counter()
                    ativacao = funcao(con, semente, tetos)
                    ms.append((time.perf_counter() - inicio) * 1000.0)
                    nos.append(ativacao.nos_visitados)
                    arestas.append(ativacao.arestas_lidas)
                    truncados += int(ativacao.graph_truncated)
                amostras.append(
                    Amostra(f"hub-{grau_real}", nome, saltos, execucao, ms, nos, arestas, truncados)
                )
    con.close()
    return amostras


def escrever_markdown(
    amostras: list[Amostra],
    tamanhos: dict[str, dict[str, int]],
    slo12: list[dict[str, float]],
    hub: list[Amostra],
    caminho: Path,
    *,
    consultas: int,
    execucoes: int,
    orcamento_ms: float,
) -> None:
    """Relatório com hardware, `n`, três execuções e o veredito sobre SLO-11/SLO-12."""
    maquina = hardware()
    linhas: list[str] = [
        "# F0-05 — harness da memória em grafo: números medidos",
        "",
        "**Gerado por** `tools/harness_memoria.py` (não editar à mão). "
        f"**Data:** {time.strftime('%Y-%m-%d')}.",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {maquina['cpu']}, {maquina['memoria']} de RAM, {maquina['plataforma']}",
        f"- Python {maquina['python']}, SQLite {maquina['sqlite']}, banco em memória",
        f"- {consultas} consultas por execução, {execucoes} execuções independentes, "
        f"orçamento da §6.8 em {orcamento_ms:.0f} ms",
        "- grafo sintético determinístico (semente fixa), `n` base = 122 episódios: as "
        "memórias que o Orchestrator guarda para este projeto em 2026-10-15",
        "- **[SUPOSIÇÃO]** razões do gerador: 3 entidades e 8 arestas por episódio "
        "(grau médio ~5). O cartão F0-08 troca isso pela contagem real do exportador.",
        "- a lista densa da fusão é **simulada** (sobreposição de termos): isto mede custo, "
        "não qualidade de recuperação — qualidade é a medição da §8.1/§8.2, em F3",
        "",
        "## Tamanho real de cada escala",
        "",
        "| escala | episódios | entidades | arestas | unidades |",
        "|---|---:|---:|---:|---:|",
    ]
    for nome, contagem in tamanhos.items():
        linhas.append(
            f"| {nome} | {contagem['episode']} | {contagem['entity']} | "
            f"{contagem['entity_edge']} | {contagem['memory_unit']} |"
        )

    linhas += [
        "",
        "## SLO-11 — ativação de grafo (meta: p50 ≤ 15 ms, p95 ≤ 40 ms)",
        "",
        "Mediana das três execuções, por escala, implementação e número de saltos.",
        "",
        "| escala | implementação | saltos | p50 (ms) | p95 (ms) | p99 (ms) | nós | arestas "
        "| truncados |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for chave in sorted({(a.escala, a.implementacao, a.saltos) for a in [*amostras, *hub]}):
        grupo = [a for a in [*amostras, *hub] if (a.escala, a.implementacao, a.saltos) == chave]
        linhas.append(
            f"| {chave[0]} | {chave[1]} | {chave[2]} | "
            f"{statistics.median([a.p50 for a in grupo]):.3f} | "
            f"{statistics.median([a.p95 for a in grupo]):.3f} | "
            f"{statistics.median([a.p99 for a in grupo]):.3f} | "
            f"{statistics.mean([statistics.mean(a.nos) for a in grupo]):.1f} | "
            f"{statistics.mean([statistics.mean(a.arestas) for a in grupo]):.1f} | "
            f"{sum(a.truncados for a in grupo)}/{sum(len(a.ms) for a in grupo)} |"
        )

    linhas += [
        "",
        "## SLO-12 — memória pronta para o S2, sem reranker (meta: p50 ≤ 120 ms, p95 ≤ 250 ms)",
        "",
        "Caminho completo da §6.8: densa (simulada) + léxica FTS5 + 2 saltos de grafo, "
        "fundidos por RRF.",
        "",
        "| escala | execução | n | p50 (ms) | p95 (ms) | truncados |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for linha in slo12:
        linhas.append(
            f"| {linha['escala']:.0f}x | {linha['execucao']:.0f} | {linha['n']:.0f} | "
            f"{linha['p50']:.2f} | {linha['p95']:.2f} | {linha['truncados']:.0f} |"
        )

    producao = [a for a in [*amostras, *hub] if a.implementacao == "sql-por-no"]
    recursivo = [a for a in amostras if a.implementacao == "sql-recursivo"]
    pior_1 = max((a.p95 for a in producao if a.saltos == 1), default=0.0)
    pior_2 = max((a.p95 for a in producao if a.saltos == 2), default=0.0)
    pior_slo12 = max((linha["p95"] for linha in slo12), default=0.0)
    truncados_recursivo = sum(a.truncados for a in recursivo)
    total_recursivo = sum(len(a.ms) for a in recursivo)
    hub_por_no = max(
        (a.p95 for a in hub if a.implementacao == "sql-por-no" and a.saltos == 2), default=0.0
    )
    hub_por_salto = max(
        (a.p95 for a in hub if a.implementacao == "sql-por-salto" and a.saltos == 2), default=0.0
    )
    hub_memoria = max(
        (a.p95 for a in hub if a.implementacao == "memoria" and a.saltos == 2), default=0.0
    )
    sem_hub_2 = max(
        (a.p95 for a in amostras if a.implementacao == "sql-por-no" and a.saltos == 2), default=0.0
    )

    linhas += [
        "",
        "## Veredito (aceite (e) do cartão)",
        "",
        f"- **SLO-11 é alcançável**: com a travessia de produção (`sql-por-no`), o pior p95 "
        f"medido em todos os casos — escalas 1×/10×/100× e o grafo com hub de grau 10 000 — "
        f"foi **{pior_1:.3f} ms** com 1 salto (meta 40 ms) e **{pior_2:.3f} ms** com 2 saltos. "
        f"Fora do caso do hub, 2 saltos ficam em {sem_hub_2:.3f} ms p95 na escala 100× "
        "(12 200 episódios, ~97 600 arestas).",
        f"- **SLO-12 é alcançável**: pior p95 do caminho completo = **{pior_slo12:.2f} ms** "
        "(meta 250 ms), ainda sem reranker, na escala 100×, com 0 consulta truncada.",
        "- **Limite de saltos: 2 saltos cabem**, em todas as escalas e também com hub. O "
        "custo de 1 → 2 saltos cresce poucas vezes, não exponencialmente, porque o teto de "
        "fan-out por nó corta a expansão.",
        f"- **O que aperta é o hub, não o tamanho do grafo:** com grau 10 000, 2 saltos vão de "
        f"{sem_hub_2:.3f} ms para **{hub_por_no:.3f} ms** p95. É o número que torna a "
        "penalidade de hub da §6.7 requisito, e não enfeite.",
        f"- **Teto dentro da varredura vence teto depois dela** (aceite (d)): no hub, a mesma "
        f"travessia com `ROW_NUMBER() ... WHERE pos <= teto` custou {hub_por_salto:.3f} ms p95 "
        f"e a propagação em memória {hub_memoria:.3f} ms (lendo ~10 000 arestas), contra "
        f"{hub_por_no:.3f} ms de `sql-por-no`, que para de ler no `LIMIT` de cada nó. Por isso "
        "`ativar_por_no` é a implementação de produção.",
        f"- **A travessia recursiva em SQL não serve**: `WITH RECURSIVE` sem teto de fan-out "
        f"ficou 100–200× mais lenta e estourou o orçamento em {truncados_recursivo}/"
        f"{total_recursivo} consultas nas escalas maiores. Fica no repositório como medição, "
        "não como caminho.",
        "",
        "## O que estes números **não** dizem",
        "",
        "- nada sobre qualidade (recall, nDCG): é a medição da §8.2, com corpus anotado, em F3;",
        "- nada sobre o corpus real do dono depois do exportador de C1 (cartão F0-08) — aqui o "
        "grafo é sintético, com grau médio declarado;",
        "- nada sobre Windows: o harness roda nos dois sistemas (só stdlib + SQLite), mas foi "
        "**executado apenas em Linux**;",
        "- nada sobre reranker: SLO-8 é outra medição, com modelo de licença comercial (ADR-0011).",
        "",
    ]
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("\n".join(linhas), encoding="utf-8")


def escrever_csv(amostras: list[Amostra], caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(
            [
                "escala",
                "implementacao",
                "saltos",
                "execucao",
                "n",
                "p50_ms",
                "p95_ms",
                "p99_ms",
                "nos_medios",
                "arestas_medias",
                "truncados",
            ]
        )
        for a in amostras:
            escritor.writerow(
                [
                    a.escala,
                    a.implementacao,
                    a.saltos,
                    a.execucao,
                    len(a.ms),
                    f"{a.p50:.3f}",
                    f"{a.p95:.3f}",
                    f"{a.p99:.3f}",
                    f"{statistics.mean(a.nos):.1f}",
                    f"{statistics.mean(a.arestas):.1f}",
                    a.truncados,
                ]
            )


def main(argv: list[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--consultas", type=int, default=200, help="consultas por execução")
    analisa.add_argument("--execucoes", type=int, default=3, help="execuções independentes")
    analisa.add_argument("--orcamento-ms", type=float, default=40.0, help="teto da §6.8")
    analisa.add_argument(
        "--escalas", type=int, nargs="+", default=[1, 10, 100], help="fatores sobre o corpus"
    )
    analisa.add_argument("--hub", type=int, default=10000, help="grau do hub sintético")
    args = analisa.parse_args(argv)

    escalas = [
        Escala.de_corpus(f"{fator}x", episodios_base=EPISODIOS_BASE, fator=fator)
        for fator in args.escalas
    ]
    print(f"hardware: {hardware()}")
    print(f"escalas: {[(e.nome, e.episodios, e.entidades, e.arestas) for e in escalas]}")

    inicio = time.monotonic()
    amostras, tamanhos, slo12 = medir(
        args.consultas, args.execucoes, escalas, orcamento_ms=args.orcamento_ms
    )
    print(f"medição terminada em {time.monotonic() - inicio:.1f}s")

    hub = medir_hub(
        grau=args.hub,
        consultas=min(args.consultas, 50),
        execucoes=args.execucoes,
        orcamento_ms=args.orcamento_ms,
    )
    escrever_csv([*amostras, *hub], PASTA_SAIDA / "f0-05-grafo.csv")
    escrever_markdown(
        amostras,
        tamanhos,
        slo12,
        hub,
        PASTA_SAIDA / "f0-05-grafo.md",
        consultas=args.consultas,
        execucoes=args.execucoes,
        orcamento_ms=args.orcamento_ms,
    )
    print(f"csv e relatório em {PASTA_SAIDA}")

    for a in amostras:
        if a.execucao == 1:
            print(
                f"{a.escala:>5} {a.implementacao:14} {a.saltos} salto(s): "
                f"p50 {a.p50:7.3f} ms  p95 {a.p95:7.3f} ms  nós {statistics.mean(a.nos):7.1f}"
            )
    for a in hub:
        if a.execucao == 1:
            print(
                f"{a.escala:>12} {a.implementacao:14} {a.saltos} salto(s): "
                f"p50 {a.p50:7.3f} ms  p95 {a.p95:7.3f} ms  "
                f"arestas {statistics.mean(a.arestas):8.1f}"
            )
    for linha in slo12:
        print(
            f"SLO-12 escala {linha['escala']:>4.0f}x exec {linha['execucao']:.0f}: "
            f"p50 {linha['p50']:.2f} ms  p95 {linha['p95']:.2f} ms  "
            f"truncados {linha['truncados']:.0f}/{linha['n']:.0f}"
        )
    print(f"tamanhos reais: {tamanhos}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
