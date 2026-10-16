"""Palavra de ativação medida: falso positivo e falso negativo por limiar (ADR-0021).

    .venv/bin/python tools/harness_palavra.py                  # publica em docs/medicoes
    .venv/bin/python tools/harness_palavra.py --saida /tmp/x   # outra pasta
    .venv/bin/python tools/harness_palavra.py --sem-epitran    # só a redução sem dependência

**O que é medido, e o que não é.** O detector (`jarvis.voz.palavra`) recebe **texto**: o que o
ASR local transcreveu do trecho que o VAD abriu. Esta medição exercita exatamente essa parte,
sobre texto — nenhum áudio é tocado, nenhum microfone aberto, nenhum ASR rodado. Quanto o ASR
de verdade erra o nome "jarvis" na voz do dono é outra pergunta, e ela fica como "não
verificado" no relatório.

Três conjuntos, e cada um responde a uma coisa:

1. **negativos do corpus** — `texto` e `texto_antes` de `corpus/turnos/rotulos.jsonl`, sem
   repetição. Nenhuma frase ali tem a palavra de ativação, então **qualquer** disparo é falso
   positivo: é o "o microfone abriu sozinho com fala comum";
2. **vizinhos** — nomes e palavras que soam perto de "jarvis" (`jarbas`, `marvin`, `travis`,
   `jardim`…), dentro de frase. É o falso positivo difícil, escolhido à mão;
3. **positivos** — grafias que um ASR plausivelmente escreve para "jarvis" (`járvis`,
   `djarvis`, `jar vis`…), sozinhas, antes e depois de um pedido do corpus. **Construídos à
   mão**: o corpus não tem a palavra, e o relatório diz isso.

A varredura vai de 0,60 a 0,95, para os dois fonemizadores, e o limiar sugerido é o **meio do
platô** onde os dois conjuntos negativos têm zero disparo e o falso negativo é o menor — o
meio, e não a borda, porque a similaridade anda em degraus (k/6 para um alvo de seis símbolos)
e a borda é onde uma grafia nova cairia do lado errado.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Final

from jarvis.medicao import hardware, percentil
from jarvis.voz.palavra import DetectorDePalavra, fonetica_simples

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_SAIDA: Final = RAIZ / "docs" / "medicoes"
ROTULOS: Final = RAIZ / "corpus" / "turnos" / "rotulos.jsonl"
NOME: Final = "palavra-de-ativacao"
PALAVRA: Final = "jarvis"
LIMIARES: Final[tuple[float, ...]] = tuple(round(0.60 + 0.01 * i, 2) for i in range(36))

GRAFIAS: Final[tuple[str, ...]] = (
    "jarvis",
    "járvis",
    "djarvis",
    "jarves",
    "jervis",
    "jarviz",
    "jarvas",
    "javis",
    "jarvi",
    "jarbis",
    "jar vis",
    "jár vis",
)
"""O que um ASR pode escrever para "jarvis". Escolhido à mão — não é saída medida de ASR."""

VIZINHOS: Final[tuple[str, ...]] = (
    "jarbas",
    "marvin",
    "charles",
    "carlos",
    "travis",
    "davis",
    "jardim",
    "jarra",
    "chaves",
    "harvey",
    "garcia",
    "service",
    "jovens",
    "já vi",
    "já vou",
    "já disse",
    "james",
    "jair",
)
"""Nomes e palavras que soam perto. Também escolhidos à mão, e é por isso que estão listados."""

MOLDES_DE_VIZINHO: Final[tuple[str, ...]] = (
    "{v}",
    "o {v} ligou ontem",
    "{v}, {pedido}",
    "{pedido} e avisa o {v}",
)
MOLDES_DE_POSITIVO: Final[tuple[str, ...]] = ("{v}", "{v}, {pedido}", "{pedido}, {v}")
PEDIDOS_POR_GRAFIA: Final = 20


@dataclass(frozen=True, slots=True)
class Linha:
    fonemizador: str
    limiar: float
    negativos: int
    fp_corpus: int
    vizinhos: int
    fp_vizinhos: int
    positivos: int
    fn: int
    comando_errado: int
    """Chamou, mas o pedido extraído não é o pedido do molde (só conta nos positivos)."""

    @property
    def taxa_fp_corpus(self) -> float:
        return self.fp_corpus / self.negativos if self.negativos else 0.0

    @property
    def taxa_fp_vizinhos(self) -> float:
        return self.fp_vizinhos / self.vizinhos if self.vizinhos else 0.0

    @property
    def taxa_fn(self) -> float:
        return self.fn / self.positivos if self.positivos else 0.0


@dataclass(slots=True)
class Medicao:
    linhas: list[Linha] = field(default_factory=list)
    tempos_us: dict[str, list[float]] = field(default_factory=dict)
    disparos_corpus: dict[str, list[tuple[float, str, str]]] = field(default_factory=dict)
    """Por fonemizador: (parecença, o que casou, frase) dos negativos mais perto do alvo."""
    perdas: dict[str, dict[str, float]] = field(default_factory=dict)
    """Por fonemizador: a parecença de cada grafia sozinha — é o que explica o degrau."""
    vizinhos_parecenca: dict[str, dict[str, float]] = field(default_factory=dict)


def frases_do_corpus(caminho: Path) -> list[str]:
    vistas: dict[str, None] = {}
    for bruta in caminho.read_text(encoding="utf-8").splitlines():
        if not bruta.strip():
            continue
        rotulo = json.loads(bruta)
        for chave in ("texto", "texto_antes"):
            texto = str(rotulo.get(chave, "")).strip()
            if texto:
                vistas.setdefault(texto, None)
    return list(vistas)


def positivos(pedidos: Sequence[str]) -> list[tuple[str, str]]:
    """(frase, pedido esperado). Sozinha, o pedido esperado é vazio."""
    saida: list[tuple[str, str]] = []
    for grafia in GRAFIAS:
        for pedido in pedidos[:PEDIDOS_POR_GRAFIA]:
            for molde in MOLDES_DE_POSITIVO:
                if molde == "{v}" and pedido is not pedidos[0]:
                    continue  # a grafia sozinha entra uma vez só
                frase = molde.format(v=grafia, pedido=pedido)
                saida.append((frase, "" if molde == "{v}" else pedido))
    return saida


def vizinhos(pedidos: Sequence[str]) -> list[str]:
    saida: list[str] = []
    for indice, vizinho in enumerate(VIZINHOS):
        pedido = pedidos[indice % len(pedidos)]
        saida.extend(molde.format(v=vizinho, pedido=pedido) for molde in MOLDES_DE_VIZINHO)
    return saida


def _normalizado(texto: str) -> str:
    return " ".join(texto.lower().replace(",", " ").split())


def medir(
    nome: str,
    fonetica: Callable[[str], str],
    *,
    negativos: Sequence[str],
    dificeis: Sequence[str],
    chamadas: Sequence[tuple[str, str]],
    medicao: Medicao,
) -> None:
    # A parecença de cada frase é calculada **uma vez**, com limiar mínimo; a varredura só
    # compara contra o corte. Assim a curva sai de uma passada, e o tempo medido é o de um
    # `achar` de verdade por trecho.
    base = DetectorDePalavra(palavra=PALAVRA, limiar=0.50, fonetica=fonetica)
    tempos: list[float] = []
    notas_neg: list[tuple[float, str, str]] = []
    for frase in negativos:
        comeco = time.perf_counter_ns()
        achado = base.achar(frase)
        tempos.append((time.perf_counter_ns() - comeco) / 1000.0)
        notas_neg.append(
            (achado.similaridade, achado.ouvido, frase) if achado else (0.0, "", frase)
        )
    notas_dif = [(a.similaridade if (a := base.achar(f)) else 0.0) for f in dificeis]
    notas_pos: list[tuple[float, bool]] = []
    for frase, esperado in chamadas:
        achado = base.achar(frase)
        if achado is None:
            notas_pos.append((0.0, False))
            continue
        notas_pos.append(
            (achado.similaridade, _normalizado(achado.comando) == _normalizado(esperado))
        )

    for limiar in LIMIARES:
        medicao.linhas.append(
            Linha(
                fonemizador=nome,
                limiar=limiar,
                negativos=len(negativos),
                fp_corpus=sum(1 for nota, _, _ in notas_neg if nota >= limiar),
                vizinhos=len(dificeis),
                fp_vizinhos=sum(1 for nota in notas_dif if nota >= limiar),
                positivos=len(chamadas),
                fn=sum(1 for nota, _ in notas_pos if nota < limiar),
                comando_errado=sum(1 for nota, certo in notas_pos if nota >= limiar and not certo),
            )
        )
    medicao.tempos_us[nome] = tempos
    medicao.disparos_corpus[nome] = sorted(notas_neg, reverse=True)[:5]
    medicao.perdas[nome] = {g: base.parecenca(g.replace(" ", "")) for g in GRAFIAS}
    medicao.vizinhos_parecenca[nome] = {v: base.parecenca(v.replace(" ", "")) for v in VIZINHOS}


def escolher(linhas: Sequence[Linha]) -> float | None:
    """O meio do platô sem falso positivo e com o menor falso negativo."""
    seguras = [linha for linha in linhas if linha.fp_corpus == 0 and linha.fp_vizinhos == 0]
    if not seguras:
        return None
    menor_fn = min(linha.fn for linha in seguras)
    plato = [linha.limiar for linha in seguras if linha.fn == menor_fn]
    return round(statistics.median(plato), 2)


def escrever_csv(medicao: Medicao, caminho: Path) -> None:
    """Dois blocos, separados por linha em branco: a varredura (uma linha por fonemizador e
    limiar) e o tempo por trecho (uma linha por fonemizador). Assim cada número de tempo que a
    ADR publica tem **uma** linha no CSV para o `tools/adr.py` conferir."""
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(
            [
                "caso",
                "fonemizador",
                "limiar",
                "negativos_corpus",
                "fp_corpus",
                "taxa_fp_corpus",
                "vizinhos",
                "fp_vizinhos",
                "taxa_fp_vizinhos",
                "positivos",
                "fn",
                "taxa_fn",
                "comando_errado",
            ]
        )
        for linha in medicao.linhas:
            escritor.writerow(
                [
                    f"{linha.fonemizador}@{linha.limiar:.2f}",
                    linha.fonemizador,
                    f"{linha.limiar:.2f}",
                    linha.negativos,
                    linha.fp_corpus,
                    f"{linha.taxa_fp_corpus:.4f}",
                    linha.vizinhos,
                    linha.fp_vizinhos,
                    f"{linha.taxa_fp_vizinhos:.4f}",
                    linha.positivos,
                    linha.fn,
                    f"{linha.taxa_fn:.4f}",
                    linha.comando_errado,
                ]
            )
        escritor.writerow([])
        escritor.writerow(
            ["fonemizador", "trechos", "tempo_por_trecho_p50_us", "tempo_por_trecho_p95_us"]
        )
        for nome, tempos in medicao.tempos_us.items():
            escritor.writerow(
                [nome, len(tempos), f"{percentil(tempos, 50):.1f}", f"{percentil(tempos, 95):.1f}"]
            )


def ler_varredura(caminho: Path) -> list[dict[str, str]]:
    """O primeiro bloco do CSV (a varredura), como dicionários."""
    texto = caminho.read_text(encoding="utf-8").split("\n\n", 1)[0]
    return list(csv.DictReader(texto.splitlines()))


def escrever_markdown(medicao: Medicao, caminho: Path, nomes: Sequence[str]) -> None:
    maquina = hardware()
    partes = [
        "# Palavra de ativação — falso positivo e falso negativo por limiar",
        "",
        f"**Gerado por** `tools/harness_palavra.py` (não editar à mão). "
        f"**Data:** {date.today().isoformat()}. **Dados:** `{NOME}.csv`.",
        "",
        "> **Só texto.** O detector recebe a transcrição; aqui ele recebe frases escritas. "
        "Nenhum áudio foi tocado, nenhum microfone aberto, nenhum ASR rodado. Quanto o ASR "
        "local erra o nome na voz do dono **não foi medido**.",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {maquina['cpu']}, {maquina['nucleos']} fios, {maquina['memoria']} de RAM",
        f"- {maquina['plataforma']}",
        f"- palavra: `{PALAVRA}`; janelas de uma e duas palavras (`jarvis.voz.palavra`)",
        f"- negativos do corpus: {medicao.linhas[0].negativos} frases distintas de "
        "`corpus/turnos/rotulos.jsonl` (`texto` ∪ `texto_antes`); nenhuma tem a palavra",
        f"- vizinhos: {len(VIZINHOS)} nomes/palavras × {len(MOLDES_DE_VIZINHO)} moldes = "
        f"{medicao.linhas[0].vizinhos} frases (lista no código, escolhida à mão)",
        f"- positivos: {len(GRAFIAS)} grafias × (sozinha + antes e depois de "
        f"{PEDIDOS_POR_GRAFIA} pedidos do corpus) = {medicao.linhas[0].positivos} frases "
        "(**construídos à mão**: o corpus não tem a palavra)",
        "- `comando errado`: chamou, mas o pedido extraído não é o do molde",
        "- tempo: um `achar` por frase negativa, `perf_counter_ns`",
        "",
        "## Limiar sugerido",
        "",
        "| fonemizador | limiar sugerido | FP corpus | FP vizinhos | FN | tempo p50 | tempo p95 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for nome in nomes:
        linhas = [linha for linha in medicao.linhas if linha.fonemizador == nome]
        escolhido = escolher(linhas)
        tempos = medicao.tempos_us[nome]
        if escolhido is None:
            partes.append(f"| `{nome}` | nenhum sem FP | — | — | — | — | — |")
            continue
        linha = next(item for item in linhas if item.limiar == escolhido)
        partes.append(
            f"| `{nome}` | {escolhido:.2f} | {linha.fp_corpus}/{linha.negativos} | "
            f"{linha.fp_vizinhos}/{linha.vizinhos} | {linha.fn}/{linha.positivos} "
            f"({linha.taxa_fn:.1%}) | {percentil(tempos, 50):.0f} µs | "
            f"{percentil(tempos, 95):.0f} µs |"
        )
    partes += [
        "",
        "Regra: o meio do platô de limiares com **zero** disparo nos dois conjuntos negativos e "
        "o menor falso negativo. A curva anda em degraus porque `jarvis` vira seis símbolos e "
        "cada edição custa 1/6: entre 0,67 e 0,83 todo limiar é o mesmo corte — **no máximo uma "
        "edição** —, e o meio do platô é o que fica mais longe das duas bordas.",
        "",
        "## Varredura (de 0,05 em 0,05; a de 0,01 está no CSV)",
        "",
        "| fonemizador | limiar | FP corpus | FP vizinhos | FN | comando errado |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for linha in medicao.linhas:
        if round(linha.limiar * 100) % 5:
            continue
        partes.append(
            f"| `{linha.fonemizador}` | {linha.limiar:.2f} | {linha.fp_corpus} | "
            f"{linha.fp_vizinhos} | {linha.fn} ({linha.taxa_fn:.1%}) | {linha.comando_errado} |"
        )
    partes += ["", "## Parecença de cada grafia e de cada vizinho, sozinhos", ""]
    partes.append("| palavra | conjunto | " + " | ".join(f"`{n}`" for n in nomes) + " |")
    partes.append("|---|---|" + "---:|" * len(nomes))
    for grafia in GRAFIAS:
        valores = " | ".join(f"{medicao.perdas[n][grafia]:.3f}" for n in nomes)
        partes.append(f"| {grafia} | positivo | {valores} |")
    for vizinho in VIZINHOS:
        valores = " | ".join(f"{medicao.vizinhos_parecenca[n][vizinho]:.3f}" for n in nomes)
        partes.append(f"| {vizinho} | vizinho | {valores} |")
    partes += ["", "## Os negativos do corpus mais perto do alvo", ""]
    for nome in nomes:
        perto = [
            f"{nota:.3f} em “{ouvido}” ({frase})"
            for nota, ouvido, frase in medicao.disparos_corpus[nome]
            if nota
        ]
        partes.append(f"- `{nome}`: " + ("; ".join(perto) or "nenhum chega a 0,50"))
    partes += [
        "",
        "## O que esta medição não cobre",
        "",
        "- **áudio real**: nenhuma voz do dono, nenhum ruído da casa, nenhum ASR de verdade "
        "transcrevendo o nome — a taxa de acerto em uso é desconhecida;",
        "- **as grafias positivas e os vizinhos são listas escritas à mão**: o número vale "
        "para estas listas, não para o português inteiro;",
        "- **o corpus é pequeno e de um domínio só** (pedidos de casa e escritório): conversa "
        "livre, TV e música ao fundo não estão aqui;",
        "- **outra palavra escolhida pelo dono** muda o alvo e, com ele, o degrau da curva: o "
        "limiar sugerido é para `jarvis`.",
        "",
    ]
    caminho.write_text("\n".join(partes), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--saida", type=Path, default=PASTA_SAIDA)
    analisa.add_argument("--rotulos", type=Path, default=ROTULOS)
    analisa.add_argument(
        "--sem-epitran", action="store_true", help="mede só a redução sem dependência"
    )
    args = analisa.parse_args(argv)

    negativos = frases_do_corpus(args.rotulos)
    pedidos = negativos
    chamadas = positivos(pedidos)
    dificeis = vizinhos(pedidos)
    fonemizadores: list[tuple[str, Callable[[str], str]]] = [("simples", fonetica_simples)]
    if not args.sem_epitran:
        try:
            from jarvis.voz.fonemizador import FonemizadorEpitran

            epitran = FonemizadorEpitran(com_tonica=False)
            epitran.abrir()
        except Exception as erro:  # sem o grupo `voz`: mede o que dá e diz
            print(f"epitran fora da medição: {erro}")
        else:
            fonemizadores.append(("epitran", epitran))

    medicao = Medicao()
    for nome, fonetica in fonemizadores:
        medir(
            nome,
            fonetica,
            negativos=negativos,
            dificeis=dificeis,
            chamadas=chamadas,
            medicao=medicao,
        )

    nomes = [nome for nome, _ in fonemizadores]
    args.saida.mkdir(parents=True, exist_ok=True)
    escrever_csv(medicao, args.saida / f"{NOME}.csv")
    escrever_markdown(medicao, args.saida / f"{NOME}.md", nomes)
    for nome in nomes:
        escolhido = escolher([linha for linha in medicao.linhas if linha.fonemizador == nome])
        print(f"{nome:10} limiar sugerido: {escolhido}")
    print(f"csv e relatório em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
