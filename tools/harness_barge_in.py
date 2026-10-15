"""SLO-2 ponta a ponta, com decomposição por salto (cartão F1-10).

    uv run --frozen python tools/harness_barge_in.py              # publica em docs/medicoes
    uv run --frozen python tools/harness_barge_in.py --itens 20 --execucoes 1 --saida /tmp/x

O caminho medido é o da regra 1 da §3.3, inteiro:

    fala do dono → VAD detecta → epoch++ → Cancel P0 → fila vazia → síntese interrompida
                 → s2 cancelado

**Conta-se do início REAL da fala** (o rótulo do corpus sabe onde ela começa), não de quando o
nosso VAD percebeu: o SLO-2 é do ponto de vista de quem fala. O veredito usa o número
conservador — tempo de áudio **mais** o custo de CPU dos saltos.

**Piso de software: a fila do driver não está na conta**, e é exatamente nela que o áudio velho
sobrevive. O SLO-2 de verdade é do F1-16, na máquina do dono.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.agentd.barge_in import (
    SLO2_P50_MS,
    SLO2_P95_MS,
    Interrupcao,
    cenario_para,
    extrair_slo2,
)
from jarvis.agentd.tts import MotorParametrico
from jarvis.audio_io.vad import (
    ARQUIVO_SILERO,
    PASTA_MODELOS_PADRAO,
    Histerese,
    Vad,
    VadDeEnergia,
    VadSilero,
)
from jarvis.corpus.rotulos import ler_rotulos
from jarvis.medicao import hardware

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_SAIDA: Final = RAIZ / "docs" / "medicoes"
CORPUS_PADRAO: Final = RAIZ / "corpus" / "turnos"
MODELO_SILERO: Final = PASTA_MODELOS_PADRAO / ARQUIVO_SILERO


@dataclass(slots=True)
class Medicao:
    itens: int
    execucoes: int
    por_vad: dict[str, list[Interrupcao]] = field(default_factory=dict)
    asr_lento: dict[str, float] = field(default_factory=dict)
    lacunas: list[tuple[str, str]] = field(default_factory=list)


def vads_disponiveis(nomes: Sequence[str]) -> dict[str, Callable[[], Vad]]:
    """As fábricas de VAD disponíveis: o silero só entra se o peso existir na máquina."""
    fabricas: dict[str, Callable[[], Vad]] = {}
    for nome in nomes:
        if nome == "energia":
            fabricas[nome] = lambda: VadDeEnergia(histerese=Histerese())
        elif nome == "silero" and MODELO_SILERO.exists():
            fabricas[nome] = lambda: VadSilero(caminho=MODELO_SILERO, histerese=Histerese())
    return fabricas


def escrever_csv(medicao: Medicao, caminho: Path) -> None:
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(
            [
                "vad",
                "item",
                "slo2_ms",
                "slo2_audio_ms",
                "atraso_vad_ms",
                "codigo_us",
                "amostras_tocadas",
                "amostras_descartadas",
            ]
        )
        for vad, interrupcoes in medicao.por_vad.items():
            for i in interrupcoes:
                escritor.writerow(
                    [
                        vad,
                        i.item,
                        f"{i.slo2_com_codigo_ms:.3f}",
                        f"{i.slo2_ms:.3f}",
                        f"{i.atraso_do_vad_ms:.3f}",
                        f"{i.custo_de_codigo_us:.1f}",
                        i.amostras_tocadas,
                        i.amostras_descartadas,
                    ]
                )


def escrever_markdown(medicao: Medicao, caminho: Path) -> None:
    maquina = hardware()
    linhas = [
        "# F1-10 — barge-in ponta a ponta: SLO-2 e a decomposição por salto",
        "",
        "**Gerado por** `tools/harness_barge_in.py` (não editar à mão). **Data:** "
        f"{time.strftime('%Y-%m-%d')}.",
        "",
        "> **Piso de software, sem dispositivo.** A fila do **driver** não está na conta, e é "
        "nela que o áudio velho sobrevive. O SLO-2 de verdade é o aceite (a) da F1 e sai no "
        "F1-16, na máquina do dono.",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {maquina['cpu']}, {maquina['nucleos']} fios, {maquina['memoria']} de RAM",
        f"- {maquina['plataforma']}, Python {maquina['python']}",
        f"- {medicao.itens} interrupções por execução, {medicao.execucoes} execuções, fonte "
        "`arquivo` (itens do corpus sintético)",
        "- conta-se do **início real da fala** (`inicio_fala_ms` do rótulo), não de quando o VAD "
        "percebeu: o SLO-2 é do ponto de vista de quem fala",
        "- o número do veredito é o **conservador**: tempo de áudio + custo de CPU dos saltos",
        f"- alvo da SPEC §7: p50 ≤ {SLO2_P50_MS:.0f} ms, **p95 ≤ {SLO2_P95_MS:.0f} ms**",
        "",
        "## SLO-2 por VAD",
        "",
        "| VAD | n | SLO-2 p50 | SLO-2 p95 | máximo | só áudio p95 | atraso do VAD p50 | "
        f"custo de código p95 | p50 ≤ {SLO2_P50_MS:.0f}? | p95 ≤ {SLO2_P95_MS:.0f}? (gatilho) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|:--|:--|",
    ]
    for vad, interrupcoes in medicao.por_vad.items():
        r = extrair_slo2(interrupcoes)
        # Dois vereditos, de propósito: a SPEC §7 tem meta (p50) e **limite** (p95), e o
        # gatilho da ADR-0014 é o limite. Misturar os dois faria "passou de 80 ms" soar como
        # "estourou o SLO", que é outra coisa.
        linhas.append(
            f"| `{vad}` | {r['n']:.0f} | {r['slo2_p50']:.1f} ms | {r['slo2_p95']:.1f} ms "
            f"| {r['slo2_max']:.1f} ms | {r['slo2_audio_p95']:.1f} ms | {r['vad_p50']:.1f} ms "
            f"| {r['codigo_us_p95']:.0f} µs "
            f"| {'sim' if r['slo2_p50'] <= SLO2_P50_MS else '**não**'} "
            f"| {'sim' if r['slo2_p95'] <= SLO2_P95_MS else '**NÃO — gatilho aberto**'} |"
        )

    linhas += [
        "",
        "**Quem gasta o SLO-2 é o VAD, não o nosso caminho de cancelamento.** O custo de código "
        "dos cinco saltos depois da detecção fica na casa de 1 a 4 ms; o resto é o tempo que o "
        "VAD leva para ter certeza de que é fala. É aí que está a troca: o limiar de energia "
        "detecta mais rápido (menor p50) e o `silero` não produz falso positivo por quadro "
        "(F1-05, precisão 1,000 contra 0,999). Escolher entre os dois é escolher entre calar "
        "mais rápido e calar por engano — e isso se decide com voz real (F1-16).",
        "",
        "## Decomposição por salto (aceite (c))",
        "",
        "Tempo de **áudio** (o que o dono sente), mediana entre interrupções:",
        "",
        "| VAD | salto | mediana |",
        "|---|---|---:|",
    ]
    for vad, interrupcoes in medicao.por_vad.items():
        if not interrupcoes:
            continue
        chaves = list(interrupcoes[0].decomposicao_ms())
        for chave in chaves:
            valores = [i.decomposicao_ms()[chave] for i in interrupcoes]
            linhas.append(f"| `{vad}` | `{chave}` | {statistics.median(valores):.1f} ms |")
    linhas += [
        "",
        "Custo de **CPU** por salto (o que é nosso para otimizar), mediana:",
        "",
        "| VAD | salto | mediana |",
        "|---|---|---:|",
    ]
    for vad, interrupcoes in medicao.por_vad.items():
        if not interrupcoes:
            continue
        for chave in list(interrupcoes[0].decomposicao_us()):
            valores = [i.decomposicao_us()[chave] for i in interrupcoes]
            linhas.append(f"| `{vad}` | `{chave}` | {statistics.median(valores):.1f} µs |")

    if medicao.asr_lento:
        linhas += [
            "",
            "## Nenhum salto espera o ASR (aceite (b))",
            "",
            "| situação | SLO-2 p50 | SLO-2 p95 |",
            "|---|---:|---:|",
        ]
        linhas += [
            f"| {situacao} | {valor:.1f} ms | — |" for situacao, valor in medicao.asr_lento.items()
        ]
        linhas.append("")
        linhas.append(
            "O transcritor lento avança o relógio em 2 s **dentro** da percepção. O SLO-2 não "
            "muda porque o `Cancel` é o primeiro envelope que a percepção devolve — a ordem da "
            "regra 1 da §3.3 é o que garante isso, e não a velocidade de ninguém."
        )

    linhas += ["", "## O que não foi medido", ""]
    linhas += [f"- **{o_que}** — {por_que}" for o_que, por_que in medicao.lacunas]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--corpus", type=Path, default=CORPUS_PADRAO)
    analisa.add_argument("--itens", type=int, default=200, help="interrupções por execução")
    analisa.add_argument("--execucoes", type=int, default=3)
    analisa.add_argument("--vads", default="energia,silero")
    analisa.add_argument("--saida", type=Path, default=PASTA_SAIDA)
    args = analisa.parse_args(argv)

    rotulos = [r for r in ler_rotulos(args.corpus / "rotulos.jsonl") if r.sintetico][: args.itens]
    faltando = [r.id for r in rotulos if not (args.corpus / r.arquivo).exists()]
    if faltando:
        print(f"FALHOU: {len(faltando)} item(ns) sem áudio em {args.corpus}")
        return 2

    fabricas = vads_disponiveis([n.strip() for n in args.vads.split(",") if n.strip()])
    if not fabricas:
        print("FALHOU: nenhum VAD disponível (o peso do silero não é versionado)")
        return 2

    medicao = Medicao(itens=len(rotulos), execucoes=args.execucoes)
    motor = MotorParametrico()
    for nome, fabrica in fabricas.items():
        interrupcoes: list[Interrupcao] = []
        for _ in range(args.execucoes):
            for rotulo in rotulos:
                cenario = cenario_para(rotulo, args.corpus, motor, vad=fabrica)
                resultado = cenario.rodar()
                if len(resultado.saltos) == len(("fala_comecou",)):
                    continue  # o VAD não viu fala neste item: não é interrupção
                interrupcoes.append(resultado)
        medicao.por_vad[nome] = interrupcoes

    # Aceite (b): o mesmo item, com ASR atrasado em 2 s.
    primeiro = rotulos[0]
    nome, fabrica = next(iter(fabricas.items()))
    normal = cenario_para(primeiro, args.corpus, motor, vad=fabrica).rodar()
    lento = cenario_para(
        primeiro,
        args.corpus,
        motor,
        vad=fabrica,
        transcritor_lento_ms=2000.0,
    ).rodar()
    medicao.asr_lento = {
        f"ASR normal ({nome})": normal.slo2_com_codigo_ms,
        f"ASR atrasado em 2 s ({nome})": lento.slo2_com_codigo_ms,
    }

    medicao.lacunas += [
        (
            "SLO-2 com microfone e alto-falante reais",
            "é o aceite (a) da F1 e sai no F1-16: a fila do driver ignora o nosso Cancel e "
            "continua entregando o que já aceitou",
        ),
        (
            "cancelar tool de efeito já executada",
            "não existe no v1 por especulação (§3.3 regra 3), então não há o que medir",
        ),
        (
            "voz de verdade no playback",
            "o motor de TTS aqui é o paramétrico: o que se mede é o caminho de cancelamento, "
            "não a voz (F1-09 mede a voz)",
        ),
        ("Windows", "a medição rodou só em Linux"),
    ]

    args.saida.mkdir(parents=True, exist_ok=True)
    escrever_csv(medicao, args.saida / "f1-10-barge-in.csv")
    escrever_markdown(medicao, args.saida / "f1-10-barge-in.md")

    pior = 0.0
    for vad, interrupcoes in medicao.por_vad.items():
        r = extrair_slo2(interrupcoes)
        pior = max(pior, r["slo2_p95"])
        print(
            f"{vad:10.10} n={r['n']:.0f} SLO-2 p50 {r['slo2_p50']:6.1f} ms p95 "
            f"{r['slo2_p95']:6.1f} ms (VAD p50 {r['vad_p50']:5.1f} ms, código p95 "
            f"{r['codigo_us_p95']:6.0f} µs)"
        )
    for situacao, valor in medicao.asr_lento.items():
        print(f"{situacao}: SLO-2 {valor:.1f} ms")
    print(f"\ncsv e relatório em {args.saida}")
    if pior > SLO2_P95_MS:
        print(
            f"\nPRECISA_DECISAO: p95 de {pior:.1f} ms estourou o SLO-2 de {SLO2_P95_MS:.0f} ms "
            "no piso de software — o gatilho da ADR-0014 abre (aceite (d))"
        )
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
