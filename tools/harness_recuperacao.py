"""SPEC §8.2 — vetor puro × híbrido × grafo+vetor, no livro de verdade (fatia 7).

    uv run --frozen python -m tools.harness_recuperacao                 # publica em docs/medicoes
    uv run --frozen python -m tools.harness_recuperacao --saida /tmp/x

Mesmo livro (o corpus C2 sintético gravado pela API do `LivroDeMemoria`, num arquivo com cofre),
mesmo índice (LanceDB, ADR-0005 item 5), mesmo embedding (e5-small local), mesmo `k`, mesmo
filtro de status/tempo, para os três braços de `jarvis.memoryd.recuperacao`:

- **A** — só a densa; **B** — densa ∪ léxica (FTS5) → RRF; **C** — B + ativação por propagação.
  Sem reranker e sem MMR: o SLO-12 é sem reranker, e nenhum reranker comercial está baixado.

Regra 7 da §8.2: os parâmetros (limiar de abstinência; saltos e soma × máximo no C) são
escolhidos nas consultas de **calibração** (70%) e os números saem das **retidas** (30%). O que
a calibração escolhe vai para `src/jarvis/memoryd/parametros.toml`, com o hash do corpus, a data
e o commit — é o arquivo que o cérebro lê.

Latência: cada consulta inteira, **com** o embedding da pergunta (é o que o turno paga), 3
execuções sobre as 175 consultas; percentil por execução, publicada a mediana.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any, Final

from jarvis.medicao import hardware, percentil
from jarvis.memoryd.embedding import EmbedderE5
from jarvis.memoryd.grafo import Tetos
from jarvis.memoryd.indice_vetorial import IndiceLance
from jarvis.memoryd.recuperacao import ARQUIVO_DE_PARAMETROS, Braco, Lembranca, Parametros, lembrar
from tools.corpus_c2 import Consulta, Montado, gerar, montar
from tools.harness_indice import calibrar_limiar, ndcg, recall

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_SAIDA: Final = RAIZ / "docs" / "medicoes"
NOME: Final = "f3-02-grafo"
EXECUCOES: Final = 3
K: Final = 20
EVIDENCIAS_NO_PROMPT: Final = 8
SLO12_P95_MS: Final = 250.0
ORCAMENTO_DO_GRAFO_MS: Final = 40.0
"""SLO-11 (p95 ≤ 40 ms com 1 salto): o teto do braço C é o mesmo da §6.8."""


@dataclass(frozen=True, slots=True)
class Configuracao:
    braco: Braco
    saltos: int = 0
    acumular: bool = False

    @property
    def nome(self) -> str:
        if self.braco != "C":
            return self.braco
        return f"C-{self.saltos}s-{'soma' if self.acumular else 'max'}"

    def parametros(self, limiar: float = 0.0) -> Parametros:
        return Parametros(
            braco=self.braco,
            limiar=limiar,
            acumular=self.acumular,
            tetos=Tetos(saltos=max(self.saltos, 1), orcamento_ms=ORCAMENTO_DO_GRAFO_MS),
        )


CONFIGURACOES: Final = (
    Configuracao("A"),
    Configuracao("B"),
    *(Configuracao("C", s, a) for s, a in product((1, 2), (False, True))),
)


@dataclass(slots=True)
class Rodada:
    """O que uma consulta devolveu numa configuração (com limiar zero: abstinência é offline)."""

    lista: list[str]
    melhor: float
    novas_do_grafo: bool
    truncado: bool
    caminhos_ok: bool


def _rodar(montado: Montado, indice: IndiceLance, consulta: str, cfg: Configuracao) -> Lembranca:
    return lembrar(
        montado.livro.con,
        indice,
        consulta,
        instante=montado.instante,
        parametros=cfg.parametros(),
        evidencias=K,
    )


def coletar(
    montado: Montado, indice: IndiceLance, consultas: Sequence[Consulta]
) -> dict[str, dict[str, Rodada]]:
    saida: dict[str, dict[str, Rodada]] = {}
    for cfg in CONFIGURACOES:
        saida[cfg.nome] = {}
        for c in consultas:
            lembranca = _rodar(montado, indice, c.texto, cfg)
            saida[cfg.nome][c.id] = Rodada(
                lista=[e.memory_unit_id for e in lembranca.evidencias],
                melhor=lembranca.melhor_cosseno,
                novas_do_grafo=lembranca.grafo_trouxe_novas,
                truncado=lembranca.graph_truncated,
                caminhos_ok=all(e.caminho for e in lembranca.evidencias),
            )
    return saida


def _abstem(rodada: Rodada, limiar: float) -> bool:
    return rodada.melhor < limiar and not rodada.novas_do_grafo


def calibrar(rodadas: dict[str, Rodada], consultas: Sequence[Consulta], ids: set[str]) -> float:
    """Limiar da abstinência só nas consultas de calibração. No braço C o grafo pode vetar a
    abstinência (passo 5); o limiar é escolhido com essa regra já valendo."""
    pares = [
        (rodadas[c.id].melhor if not rodadas[c.id].novas_do_grafo else 9.9, c.subconjunto == "C2d")
        for c in consultas
        if c.id in ids
    ]
    return calibrar_limiar(pares)


def qualidade(
    rodadas: dict[str, Rodada],
    consultas: Sequence[Consulta],
    montado: Montado,
    ids: set[str],
    limiar: float,
) -> dict[str, float]:
    escolhidas = [c for c in consultas if c.id in ids]
    saida: dict[str, float] = {"limiar": limiar, "n": float(len(escolhidas))}
    grupos = {
        "C2a": ("C2a",),
        "C2b": ("C2b",),
        "C2c": ("C2c",),
        "C2bc": ("C2b", "C2c"),
        "positivas": ("C2a", "C2b", "C2c"),
    }
    for nome, subs in grupos.items():
        do_grupo = [c for c in escolhidas if c.subconjunto in subs]
        saida[f"recall20_{nome}"] = statistics.fmean(
            recall(rodadas[c.id].lista, montado.gabarito(c)) for c in do_grupo
        )
        saida[f"ndcg10_{nome}"] = statistics.fmean(
            ndcg(rodadas[c.id].lista, montado.gabarito(c)) for c in do_grupo
        )
    positivas = [c for c in escolhidas if c.subconjunto != "C2d"]
    negativas = [c for c in escolhidas if c.subconjunto == "C2d"]
    saida["abstencao_correta"] = statistics.fmean(_abstem(rodadas[c.id], limiar) for c in negativas)
    saida["abstencao_indevida"] = statistics.fmean(
        _abstem(rodadas[c.id], limiar) for c in positivas
    )
    saida["sustentada"] = statistics.fmean(
        not _abstem(rodadas[c.id], limiar)
        and montado.gabarito(c) <= set(rodadas[c.id].lista[:EVIDENCIAS_NO_PROMPT])
        for c in positivas
    )
    saida["vencido_nas_evidencias"] = float(
        sum(
            bool(montado.vencidos(c) & set(rodadas[c.id].lista[:EVIDENCIAS_NO_PROMPT]))
            for c in escolhidas
        )
    )
    saida["sem_caminho"] = float(sum(not rodadas[c.id].caminhos_ok for c in escolhidas))
    saida["truncado"] = statistics.fmean(rodadas[c.id].truncado for c in escolhidas)
    return saida


def latencias(
    montado: Montado, indice: IndiceLance, consultas: Sequence[Consulta], cfg: Configuracao
) -> list[float]:
    tempos = []
    for c in consultas:
        inicio = time.monotonic()
        _rodar(montado, indice, c.texto, cfg)
        tempos.append((time.monotonic() - inicio) * 1000.0)
    return tempos


def decidir(b: dict[str, float], c: dict[str, float], p95: dict[str, float], nome_c: str) -> str:
    """§8.2, regras 1–4, na ordem. A regra 5 (precisão de aresta) não tem número aqui."""
    if p95[nome_c] > SLO12_P95_MS or c["vencido_nas_evidencias"] or c["sem_caminho"]:
        return "regra 1 (veto): C fora do caminho da voz"
    ganho = (c["recall20_C2bc"] - b["recall20_C2bc"]) * 100
    ganho_ndcg = c["ndcg10_C2bc"] - b["ndcg10_C2bc"]
    piora_abstencao = (b["abstencao_correta"] - c["abstencao_correta"]) * 100
    if (ganho >= 5 or ganho_ndcg >= 0.05) and piora_abstencao <= 2:
        return "regra 2: C vira o padrão"
    if 2 <= ganho < 5:
        return "regra 3: C como degrau adaptativo, não padrão"
    if ganho >= 5:
        return (
            f"inconclusivo: C ganha {ganho:.1f} pontos, mas a abstinência correta cai "
            f"{piora_abstencao:.0f} pontos (> 2), então a regra 2 não se cumpre, e a regra 3 só "
            "cobre ganho de 2 a 5 — fica o mais simples, B, e o grafo fora do caminho da voz"
        )
    return "regra 4: ganho < 2 pontos — o grafo não entra no caminho crítico"


def medir(pasta_saida: Path, arquivo_de_parametros: Path) -> dict[str, Any]:
    corpus = gerar()
    calibracao, retidas = corpus.dividir()
    with tempfile.TemporaryDirectory(prefix="harness-recuperacao-") as tmp:
        embedder = EmbedderE5()
        indice = IndiceLance(pasta=Path(tmp) / "indice", embedder=embedder)
        inicio = time.monotonic()
        montado = montar(corpus, indice, caminho=str(Path(tmp) / "memoria.sqlite"))
        montar_s = time.monotonic() - inicio
        indice.compactar()
        coletado = coletar(montado, indice, corpus.consultas)

        resumo: dict[str, Any] = {"configuracoes": {}, "latencia": []}
        for cfg in CONFIGURACOES:
            limiar = calibrar(coletado[cfg.nome], corpus.consultas, calibracao)
            resumo["configuracoes"][cfg.nome] = {
                "calibracao": qualidade(
                    coletado[cfg.nome], corpus.consultas, montado, calibracao, limiar
                ),
                "retidas": qualidade(
                    coletado[cfg.nome], corpus.consultas, montado, retidas, limiar
                ),
            }
        # o C que vai à regra é o melhor na CALIBRAÇÃO (recall@20 em C2b+C2c, depois nDCG)
        candidatos_c = [cfg for cfg in CONFIGURACOES if cfg.braco == "C"]
        melhor_c = max(
            candidatos_c,
            key=lambda cfg: (
                resumo["configuracoes"][cfg.nome]["calibracao"]["recall20_C2bc"],
                resumo["configuracoes"][cfg.nome]["calibracao"]["ndcg10_C2bc"],
                -cfg.saltos,
            ),
        )
        for execucao in range(1, EXECUCOES + 1):
            for cfg in CONFIGURACOES:
                tempos = latencias(montado, indice, corpus.consultas, cfg)
                resumo["latencia"].append(
                    {
                        "configuracao": cfg.nome,
                        "execucao": execucao,
                        "consulta_p50_ms": percentil(tempos, 50),
                        "consulta_p95_ms": percentil(tempos, 95),
                        "consulta_max_ms": max(tempos),
                        "n": len(tempos),
                    }
                )
        contagens = {
            tabela: int(montado.livro.con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0])  # noqa: S608
            for tabela in (
                "episode",
                "assertion",
                "memory_unit",
                "entity",
                "entity_edge",
                "entity_mention",
            )
        }
        montado.livro.con.close()

    p95 = {
        cfg.nome: statistics.median(
            linha["consulta_p95_ms"]
            for linha in resumo["latencia"]
            if linha["configuracao"] == cfg.nome
        )
        for cfg in CONFIGURACOES
    }
    retida = {nome: v["retidas"] for nome, v in resumo["configuracoes"].items()}
    regra = decidir(retida["B"], retida[melhor_c.nome], p95, melhor_c.nome)
    escolhido = melhor_c if regra.startswith("regra 2") else Configuracao("B")
    negativas_retidas = sum(
        1 for c in corpus.consultas if c.id in retidas and c.subconjunto == "C2d"
    )
    if retida["B"]["recall20_C2b"] < retida["A"]["recall20_C2b"]:
        regra += " — ATENÇÃO regra 6: B perdeu de A em C2b (provável bug; reexecutar com revisão)"
    resumo.update(
        {
            "corpus_hash": corpus.hash,
            "n_consultas": len(corpus.consultas),
            "n_calibracao": len(calibracao),
            "n_retidas": len(retidas),
            "n_negativas_retidas": negativas_retidas,
            "contagens": contagens,
            "montar_s": montar_s,
            "hardware": hardware(),
            "melhor_c": melhor_c.nome,
            "regra": regra,
            "escolhido": escolhido.nome,
            "p95": p95,
            "commit": _commit(),
            "data": time.strftime("%Y-%m-%d"),
        }
    )
    limiar = resumo["configuracoes"][escolhido.nome]["calibracao"]["limiar"]
    escrever_parametros(arquivo_de_parametros, escolhido, limiar, resumo)
    publicar(resumo, pasta_saida)
    return resumo


def escrever_parametros(
    arquivo: Path, cfg: Configuracao, limiar: float, resumo: dict[str, Any]
) -> None:
    arquivo.write_text(
        "# Parâmetros da recuperação da memória (SPEC §6.8). GERADO por\n"
        "# `tools/harness_recuperacao.py` — mudar é rodar a medição de novo e commitar, nunca\n"
        '# editar à mão ("nada de parâmetro mágico"). Calibrado em '
        f"{resumo['n_calibracao']} consultas do C2\n"
        f"# sintético `{resumo['corpus_hash']}`; números nas {resumo['n_retidas']} retidas em\n"
        f"# docs/medicoes/{NOME}.md.\n"
        f'data = "{resumo["data"]}"\n'
        f'commit = "{resumo["commit"]}"\n'
        f'corpus = "{resumo["corpus_hash"]}"\n'
        f'regra = "{resumo["regra"]}"\n'
        "\n[recuperacao]\n"
        f'braco = "{cfg.braco}"\n'
        "k_lista = 40\n"
        f"limiar = {limiar:.4f}\n"
        f"saltos = {max(cfg.saltos, 1)}\n"
        f"acumular = {'true' if cfg.acumular else 'false'}\n"
        f"orcamento_ms = {ORCAMENTO_DO_GRAFO_MS:.1f}\n",
        encoding="utf-8",
    )


def _commit() -> str:
    resultado = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 — git no PATH, argv explícito
        capture_output=True,
        text=True,
        check=False,
        cwd=RAIZ,
    )
    return resultado.stdout.strip() or "?"


METRICAS: Final = (
    "recall20_C2a",
    "recall20_C2b",
    "recall20_C2c",
    "recall20_C2bc",
    "ndcg10_C2bc",
    "recall20_positivas",
    "abstencao_correta",
    "abstencao_indevida",
    "sustentada",
    "vencido_nas_evidencias",
    "sem_caminho",
    "truncado",
    "limiar",
)


def publicar(resumo: dict[str, Any], pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    with (pasta / f"{NOME}.csv").open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.writer(arquivo)
        colunas = ["consulta_p50_ms", "consulta_p95_ms", "consulta_max_ms", "n"]
        escritor.writerow(["configuracao", "execucao", *colunas])
        for linha in resumo["latencia"]:
            escritor.writerow(
                [linha["configuracao"], linha["execucao"], *(_fmt(linha[c]) for c in colunas)]
            )
        escritor.writerow([])
        escritor.writerow(["configuracao_conjunto", *METRICAS])
        for nome, valores in resumo["configuracoes"].items():
            for conjunto in ("calibracao", "retidas"):
                escritor.writerow(
                    [f"{nome}:{conjunto}", *(_fmt(valores[conjunto][m]) for m in METRICAS)]
                )
    (pasta / f"{NOME}.md").write_text(relatorio(resumo), encoding="utf-8")


def _fmt(valor: Any) -> str:
    return f"{valor:.4f}" if isinstance(valor, float) else str(valor)


def _linha(*celulas: str) -> str:
    return "| " + " | ".join(celulas) + " |"


def relatorio(resumo: dict[str, Any]) -> str:
    hw = resumo["hardware"]
    medianas = {
        nome: {
            campo: statistics.median(
                linha[campo] for linha in resumo["latencia"] if linha["configuracao"] == nome
            )
            for campo in ("consulta_p50_ms", "consulta_p95_ms", "consulta_max_ms")
        }
        for nome in resumo["configuracoes"]
    }
    contagens = ", ".join(f"{k} {v}" for k, v in resumo["contagens"].items())
    linhas = [
        "# F3-02 — recuperação: vetor × híbrido × grafo+vetor (SPEC §8.2)",
        "",
        "**Gerado por** `tools/harness_recuperacao.py` (não editar à mão). **Data:** "
        f"{resumo['data']}. **Commit:** `{resumo['commit']}`.",
        "",
        "> **Corpus sintético** (`tools/corpus_c2.py`, hash "
        f"`{resumo['corpus_hash']}`), com gabarito por construção. Ele compara os braços no "
        "mesmo corpus; não mede o Jarvis na vida do dono. A decisão abaixo é provisória até o C2 "
        "real.",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {hw['cpu']}, {hw['nucleos']} fios, {hw['memoria']} de RAM; "
        f"{hw['plataforma']}, Python {hw['python']}",
        f"- livro em arquivo, com cofre, montado pela API do produto em {resumo['montar_s']:.1f} s "
        f"(inclui o embedding de todas as unidades): {contagens}",
        "- índice LanceDB (ADR-0005 item 5), embedding `intfloat/multilingual-e5-small` local; "
        "`k` = 40 por lista, top-20 para recall, top-8 para o que iria ao prompt; filtro "
        "`status=active` e validade no instante da pergunta",
        f"- {resumo['n_consultas']} consultas: parâmetros escolhidos em {resumo['n_calibracao']} "
        f"(calibração) e números das {resumo['n_retidas']} retidas (regra 7)",
        "- braço C: sementes por apelido exato na pergunta (1a) e pelas entidades dos 8 melhores "
        f"acertos densos (1b); orçamento do grafo {ORCAMENTO_DO_GRAFO_MS:.0f} ms; testados 1 e 2 "
        "saltos, energia por máximo e por soma",
        "- latência: consulta inteira **com** o embedding da pergunta, 3 execuções sobre todas as "
        "consultas; percentil por execução, publicada a mediana",
        "",
        "## Qualidade nas consultas retidas",
        "",
        _linha(
            "configuração",
            "recall@20 C2a",
            "recall@20 C2b",
            "recall@20 C2c",
            "recall@20 C2b+C2c",
            "nDCG@10 C2b+C2c",
            "abstinência correta",
            "abstinência indevida",
            "sustentada",
            "vencido nas evidências",
            "sem caminho",
            "limiar",
        ),
        "|---|" + "---:|" * 11,
    ]
    for nome, valores in resumo["configuracoes"].items():
        r = valores["retidas"]
        linhas.append(
            _linha(
                f"`{nome}`",
                f"{r['recall20_C2a']:.3f}",
                f"{r['recall20_C2b']:.3f}",
                f"{r['recall20_C2c']:.3f}",
                f"{r['recall20_C2bc']:.3f}",
                f"{r['ndcg10_C2bc']:.3f}",
                f"{r['abstencao_correta']:.2f}",
                f"{r['abstencao_indevida']:.2f}",
                f"{r['sustentada']:.2f}",
                f"{r['vencido_nas_evidencias']:.0f}",
                f"{r['sem_caminho']:.0f}",
                f"{r['limiar']:.4f}",
            )
        )
    linhas += [
        "",
        '"Sustentada" aqui é um substituto mecânico do anotado da SPEC: a consulta não absteve e '
        '**todo** o gabarito está nas 8 evidências que iriam ao prompt. "Vencido nas evidências" '
        'conta consultas em que uma memória substituída apareceu (gate 4); "sem caminho", '
        "evidências sem o porquê (gate 6).",
        "",
        "## Latência (mediana das 3 execuções)",
        "",
        _linha("configuração", "consulta p50", "consulta p95", "consulta máx", "cabe no SLO-12?"),
        "|---|---:|---:|---:|:--|",
    ]
    for nome, m in medianas.items():
        linhas.append(
            _linha(
                f"`{nome}`",
                f"{m['consulta_p50_ms']:.1f} ms",
                f"{m['consulta_p95_ms']:.1f} ms",
                f"{m['consulta_max_ms']:.1f} ms",
                "sim" if m["consulta_p95_ms"] <= SLO12_P95_MS else "**não**",
            )
        )
    b = resumo["configuracoes"]["B"]["retidas"]
    c = resumo["configuracoes"][resumo["melhor_c"]]["retidas"]
    linhas += [
        "",
        "## Decisão pela regra da §8.2 (fechada antes de medir)",
        "",
        f"- C comparado: `{resumo['melhor_c']}` (o melhor na **calibração** em recall@20 de "
        "C2b+C2c)",
        f"- recall@20 C2b+C2c: B {b['recall20_C2bc']:.3f} → C {c['recall20_C2bc']:.3f} "
        f"({(c['recall20_C2bc'] - b['recall20_C2bc']) * 100:+.1f} pontos); nDCG@10: "
        f"{b['ndcg10_C2bc']:.3f} → {c['ndcg10_C2bc']:.3f}; abstinência correta: "
        f"{b['abstencao_correta']:.2f} → {c['abstencao_correta']:.2f} (sobre "
        f"{resumo['n_negativas_retidas']} negativas retidas: cada uma vale "
        f"{100 / resumo['n_negativas_retidas']:.0f} pontos); abstinência indevida: "
        f"{b['abstencao_indevida']:.2f} → {c['abstencao_indevida']:.2f}",
        f"- **{resumo['regra']}** → no caminho da voz: **`{resumo['escolhido']}`**, gravado em "
        "`src/jarvis/memoryd/parametros.toml`",
        "- regra 5 (precisão de aresta ≥ 80% em 100 arestas revisadas): **não medida** — aqui as "
        "arestas vêm do gabarito do gerador, não de um extrator; no produto, aresta só nasce "
        "ativa pela mão do dono (ADR-0026). Sem esse número, C não vira padrão mesmo que a "
        "regra 2 dissesse que sim",
        "",
        "## O que não foi medido",
        "",
        '- **C2 real** anotado pelo dono; **datas relativas** ("terça passada") resolvidas para '
        "o instante — o corpus não cobre",
        "- **reranker e MMR** (braço B completo da §8.2): sem reranker comercial baixado",
        "- **precisão de aresta** (regra 5), ver acima",
        "- custo de extração do grafo: as arestas do corpus vêm prontas",
        "",
    ]
    return "\n".join(linhas)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--saida", type=Path, default=PASTA_SAIDA)
    parser.add_argument("--parametros", type=Path, default=ARQUIVO_DE_PARAMETROS)
    args = parser.parse_args(argv)
    resumo = medir(args.saida, args.parametros)
    print(resumo["regra"], "→", resumo["escolhido"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
