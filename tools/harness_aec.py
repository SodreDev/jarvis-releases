"""ERLE por condição e o A/B que importa: o detector dispara no nosso TTS? (cartão F1-04).

    uv run --frozen python tools/harness_aec.py                      # publica em docs/medicoes
    uv run --frozen python tools/harness_aec.py --segundos 2 --execucoes 1 --saida /tmp/x

As nove condições do aceite (a): nosso TTS atrasado **60/120/240 ms** e atenuado em
**-6/-12/-20 dB**. Para cada uma, três números:

- **ERLE** (dB), total e na metade convergida — é o quanto do eco a cadeia removeu;
- **quadros com fala vistos pelo detector SEM a cadeia** — é o problema existindo;
- **quadros com fala vistos pelo detector COM a cadeia** — é o problema resolvido.

Eco sintético é **limite inferior de dificuldade**: linear, sem distorção de alto-falante, sem
sala e sem duplo-falar real. O que isso significa está escrito em "o que não foi medido".
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
from typing import Any, Final

import numpy as np

from jarvis.audio_io.aec import CadeiaDeAec, quadros_de
from jarvis.audio_io.dsp import erle_db, para_bytes, para_float
from jarvis.audio_io.energia import LIMIAR_PADRAO_DB, DetectorDeEnergia
from jarvis.audio_io.quadro import AMOSTRAS_POR_QUADRO, TAXA_PADRAO
from jarvis.audio_io.sintese import TipoDeTrecho, Trecho, gerar
from jarvis.medicao import hardware

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_SAIDA: Final = RAIZ / "docs" / "medicoes"
ATRASOS_MS: Final = (60, 120, 240)
GANHOS_DB: Final = (-6, -12, -20)
SEGUNDOS_PADRAO: Final = 8.0
CONVERGENCIA_S: Final = 3.0
"""Janela inicial descartada na conta "convergida": o filtro adaptativo precisa aprender."""


@dataclass(frozen=True, slots=True)
class Condicao:
    atraso_ms: int
    ganho_db: int
    execucao: int
    erle_total_db: float
    erle_convergido_db: float
    quadros: int
    fala_sem_aec: int
    fala_com_aec: int
    energia_sem_aec_db: float
    energia_com_aec_db: float
    convergencia_ms: float


@dataclass(slots=True)
class Medicao:
    segundos: float
    execucoes: int
    condicoes: list[Condicao] = field(default_factory=list)
    duplo_falar: list[tuple[int, float, float]] = field(default_factory=list)
    deriva: list[tuple[float, float, bool]] = field(default_factory=list)
    lacunas: list[tuple[str, str]] = field(default_factory=list)


def nosso_tts(segundos: float, semente: int) -> np.ndarray[Any, np.dtype[np.float64]]:
    """O que sairia pelo alto-falante: fala sintética (não é corpus, é referência)."""
    return para_float(gerar((Trecho(TipoDeTrecho.FALA, segundos * 1000),), semente=semente))


def com_eco(
    referencia: np.ndarray[Any, np.dtype[np.float64]], *, atraso_ms: int, ganho_db: int
) -> np.ndarray[Any, np.dtype[np.float64]]:
    atraso = int(TAXA_PADRAO * atraso_ms / 1000)
    atrasada = np.concatenate([np.zeros(atraso), referencia])[: len(referencia)]
    return np.asarray(atrasada * 10.0 ** (ganho_db / 20.0), dtype=np.float64)


def rodar_condicao(
    referencia: np.ndarray[Any, np.dtype[np.float64]],
    *,
    atraso_ms: int,
    ganho_db: int,
    execucao: int,
) -> Condicao:
    microfone = com_eco(referencia, atraso_ms=atraso_ms, ganho_db=ganho_db)
    quadros = quadros_de(para_bytes(microfone))
    pular = int(CONVERGENCIA_S * 50)

    cadeia = CadeiaDeAec()
    detector_com = DetectorDeEnergia()
    detector_sem = DetectorDeEnergia()
    residuos: list[np.ndarray[Any, np.dtype[np.float64]]] = []
    fala_com = fala_sem = 0
    energias_com: list[float] = []
    energias_sem: list[float] = []
    convergencia_ms = float("nan")

    for i, quadro in enumerate(quadros):
        fatia = referencia[i * AMOSTRAS_POR_QUADRO : (i + 1) * AMOSTRAS_POR_QUADRO]
        cadeia.referencia(para_bytes(fatia))
        processado = cadeia.processar(quadro, tocando=True)
        residuos.append(para_float(processado.quadro.amostras))

        detector_sem.ver(quadro)
        detector_com.ver(processado.quadro)
        if i >= pular:
            fala_sem += int(bool(detector_sem.falando))
            fala_com += int(bool(detector_com.falando))
            energias_sem.append(quadro.energia_db)
            energias_com.append(processado.quadro.energia_db)
        if processado.erle_db >= 10.0 and convergencia_ms != convergencia_ms:
            convergencia_ms = (i + 1) * 20.0

    residuo = np.concatenate(residuos)
    metade = len(residuo) // 2
    return Condicao(
        atraso_ms=atraso_ms,
        ganho_db=ganho_db,
        execucao=execucao,
        erle_total_db=erle_db(microfone[: len(residuo)], residuo),
        erle_convergido_db=erle_db(microfone[metade : len(residuo)], residuo[metade:]),
        quadros=len(energias_com),
        fala_sem_aec=fala_sem,
        fala_com_aec=fala_com,
        energia_sem_aec_db=statistics.mean(energias_sem) if energias_sem else 0.0,
        energia_com_aec_db=statistics.mean(energias_com) if energias_com else 0.0,
        convergencia_ms=convergencia_ms,
    )


def rodar_duplo_falar(
    referencia: np.ndarray[Any, np.dtype[np.float64]], semente: int
) -> tuple[int, float, float]:
    """Dono falando em cima do eco: a cadeia tem de preservar a voz dele (sintético)."""
    dono = nosso_tts(len(referencia) / TAXA_PADRAO, semente)
    eco = com_eco(referencia, atraso_ms=120, ganho_db=-12)
    microfone = dono + eco
    cadeia = CadeiaDeAec()
    residuos = []
    for i, quadro in enumerate(quadros_de(para_bytes(microfone))):
        fatia = referencia[i * AMOSTRAS_POR_QUADRO : (i + 1) * AMOSTRAS_POR_QUADRO]
        cadeia.referencia(para_bytes(fatia))
        residuos.append(para_float(cadeia.processar(quadro, tocando=True).quadro.amostras))
    residuo = np.concatenate(residuos)
    n = len(residuo)
    # Quanto da voz do dono sobrou: correlação com o sinal dele, em dB de erro.
    erro = dono[:n] - residuo
    return (
        n // AMOSTRAS_POR_QUADRO,
        erle_db(microfone[:n], residuo),
        erle_db(dono[:n], erro),
    )


def rodar_deriva(
    referencia: np.ndarray[Any, np.dtype[np.float64]], ppm: float
) -> tuple[float, float, bool]:
    """Aceite (d): referência e microfone com relógios diferentes (±100 ppm)."""
    atraso = int(TAXA_PADRAO * 0.12)
    indices = np.arange(len(referencia)) * (1.0 + ppm / 1e6)
    esticada = np.interp(indices, np.arange(len(referencia)), referencia)
    microfone = np.concatenate([np.zeros(atraso), esticada])[: len(referencia)] * 0.25

    cadeia = CadeiaDeAec()
    residuos = []
    for i, quadro in enumerate(quadros_de(para_bytes(microfone))):
        fatia = referencia[i * AMOSTRAS_POR_QUADRO : (i + 1) * AMOSTRAS_POR_QUADRO]
        cadeia.referencia(para_bytes(fatia))
        residuos.append(para_float(cadeia.processar(quadro, tocando=True).quadro.amostras))
    residuo = np.concatenate(residuos)
    finito = bool(np.all(np.isfinite(residuo)))
    return ppm, erle_db(microfone[: len(residuo)], residuo), finito


def mediana_por_condicao(medicao: Medicao) -> dict[tuple[int, int], dict[str, float]]:
    por_condicao: dict[tuple[int, int], list[Condicao]] = {}
    for condicao in medicao.condicoes:
        por_condicao.setdefault((condicao.atraso_ms, condicao.ganho_db), []).append(condicao)
    return {
        chave: {
            "erle_total": statistics.median(c.erle_total_db for c in grupo),
            "erle_convergido": statistics.median(c.erle_convergido_db for c in grupo),
            "quadros": float(statistics.median(c.quadros for c in grupo)),
            "fala_sem": statistics.median(c.fala_sem_aec for c in grupo),
            "fala_com": statistics.median(c.fala_com_aec for c in grupo),
            "energia_sem": statistics.median(c.energia_sem_aec_db for c in grupo),
            "energia_com": statistics.median(c.energia_com_aec_db for c in grupo),
            "convergencia_ms": statistics.median(c.convergencia_ms for c in grupo),
        }
        for chave, grupo in sorted(por_condicao.items())
    }


def escrever_csv(medicao: Medicao, caminho: Path) -> None:
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(
            [
                "atraso_ms",
                "ganho_db",
                "execucao",
                "quadros",
                "erle_total_db",
                "erle_convergido_db",
                "fala_sem_aec",
                "fala_com_aec",
                "energia_sem_aec_db",
                "energia_com_aec_db",
                "convergencia_ms",
            ]
        )
        for c in medicao.condicoes:
            escritor.writerow(
                [
                    c.atraso_ms,
                    c.ganho_db,
                    c.execucao,
                    c.quadros,
                    f"{c.erle_total_db:.3f}",
                    f"{c.erle_convergido_db:.3f}",
                    c.fala_sem_aec,
                    c.fala_com_aec,
                    f"{c.energia_sem_aec_db:.3f}",
                    f"{c.energia_com_aec_db:.3f}",
                    f"{c.convergencia_ms:.1f}",
                ]
            )


def escrever_csv_deriva(medicao: Medicao, caminho: Path) -> None:
    """Deriva e duplo-falar em arquivo próprio: CSV com duas tabelas não se carrega em nada."""
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(["braco", "parametro", "erle_db", "finito", "preservacao_db"])
        for ppm, erle, finito in medicao.deriva:
            escritor.writerow(["deriva_ppm", f"{ppm:.0f}", f"{erle:.3f}", int(finito), ""])
        for quadros, erle, preservacao in medicao.duplo_falar:
            escritor.writerow(
                ["duplo_falar_quadros", quadros, f"{erle:.3f}", 1, f"{preservacao:.3f}"]
            )


def escrever_markdown(medicao: Medicao, caminho: Path) -> None:
    maquina = hardware()
    resumo = mediana_por_condicao(medicao)
    linhas = [
        "# F1-04 — AEC/NR/AGC: ERLE por condição e o A/B do detector",
        "",
        "**Gerado por** `tools/harness_aec.py` (não editar à mão). **Data:** "
        f"{time.strftime('%Y-%m-%d')}.",
        "",
        "> **Eco sintético, linear: limite inferior de dificuldade.** Sem sala, sem distorção "
        "de alto-falante, sem duplo-falar real. Nenhum dispositivo foi aberto.",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {maquina['cpu']}, {maquina['nucleos']} fios, {maquina['memoria']} de RAM",
        f"- {maquina['plataforma']}, Python {maquina['python']}",
        f"- {medicao.segundos:.0f} s de áudio por condição ({medicao.segundos * 50:.0f} quadros "
        f"de 20 ms), {medicao.execucoes} execuções, nove condições",
        "- a referência é **o nosso próprio playback** (fala sintética do F1-01); o microfone é "
        "essa referência atrasada e atenuada",
        f"- as colunas de detector contam quadros com fala **depois** dos primeiros "
        f"{CONVERGENCIA_S:.0f} s (o filtro adaptativo precisa aprender), com o "
        f"`DetectorDeEnergia` em {LIMIAR_PADRAO_DB:.0f} dBFS — que **não** é o VAD (F1-05)",
        "- cadeia completa: AEC → NR → AGC, a mesma que o `audio-io` usa",
        "",
        "## ERLE e o A/B do detector (mediana das execuções)",
        "",
        "| atraso | eco | ERLE total | ERLE convergido | converge em | quadros com fala "
        "SEM AEC | COM AEC |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for (atraso, ganho), valores in resumo.items():
        linhas.append(
            f"| {atraso} ms | {ganho} dB | {valores['erle_total']:.1f} dB "
            f"| {valores['erle_convergido']:.1f} dB | {valores['convergencia_ms']:.0f} ms "
            f"| {valores['fala_sem']:.0f}/{valores['quadros']:.0f} "
            f"| {valores['fala_com']:.0f}/{valores['quadros']:.0f} |"
        )
    linhas += [
        "",
        "Energia média do que o detector vê (mediana das execuções):",
        "",
        "| atraso | eco | sem AEC | com AEC |",
        "|---:|---:|---:|---:|",
    ]
    for (atraso, ganho), valores in resumo.items():
        linhas.append(
            f"| {atraso} ms | {ganho} dB | {valores['energia_sem']:.1f} dBFS "
            f"| {valores['energia_com']:.1f} dBFS |"
        )
    if medicao.duplo_falar:
        linhas += [
            "",
            "## Duplo-falar sintético (dono falando em cima do eco)",
            "",
            "| quadros | ERLE sobre o microfone | preservação da voz do dono |",
            "|---:|---:|---:|",
        ]
        linhas += [
            f"| {quadros} | {erle:.1f} dB | {preservacao:.1f} dB |"
            for quadros, erle, preservacao in medicao.duplo_falar
        ]
    if medicao.deriva:
        linhas += [
            "",
            "## Deriva de relógio (aceite (d))",
            "",
            "| deriva | ERLE | saída finita (sem NaN/inf) |",
            "|---:|---:|:--|",
        ]
        linhas += [
            f"| {ppm:+.0f} ppm | {erle:.1f} dB | {'sim' if finito else 'NÃO'} |"
            for ppm, erle, finito in medicao.deriva
        ]
    linhas += ["", "## O que não foi medido", ""]
    linhas += [f"- **{o_que}** — {por_que}" for o_que, por_que in medicao.lacunas]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--segundos", type=float, default=SEGUNDOS_PADRAO)
    analisa.add_argument("--execucoes", type=int, default=3)
    analisa.add_argument("--saida", type=Path, default=PASTA_SAIDA)
    args = analisa.parse_args(argv)

    medicao = Medicao(segundos=args.segundos, execucoes=args.execucoes)
    for execucao in range(1, args.execucoes + 1):
        referencia = nosso_tts(args.segundos, semente=100 + execucao)
        for atraso_ms in ATRASOS_MS:
            for ganho_db in GANHOS_DB:
                medicao.condicoes.append(
                    rodar_condicao(
                        referencia, atraso_ms=atraso_ms, ganho_db=ganho_db, execucao=execucao
                    )
                )
    referencia = nosso_tts(args.segundos, semente=101)
    medicao.duplo_falar.append(rodar_duplo_falar(referencia, semente=777))
    medicao.deriva += [rodar_deriva(referencia, ppm) for ppm in (-100.0, 100.0)]

    medicao.lacunas += [
        (
            "eco real de alto-falante aberto, no volume de uso",
            "sala, volume e caminho acústico são do dono; eco sintético é linear e por isso "
            "mais fácil (F1-16, na máquina dele)",
        ),
        (
            "duplo-falar real",
            "os dois falando junto, com voz humana: o duplo-falar aqui é fala sintética somada, "
            "e o congelamento do passo é proteção simples, não o detector do WebRTC",
        ),
        (
            "diferença entre headset e alto-falante, e cauda longa da sala",
            "exigem o ambiente do dono",
        ),
        (
            "distorção não linear do alto-falante",
            "a cadeia é linear: alto-falante barato em volume alto distorce, e isso nenhum "
            "filtro linear cancela",
        ),
        ("Windows", "numpy tem roda para os dois sistemas, mas o harness rodou só em Linux"),
    ]

    args.saida.mkdir(parents=True, exist_ok=True)
    escrever_csv(medicao, args.saida / "f1-04-aec.csv")
    escrever_csv_deriva(medicao, args.saida / "f1-04-aec-deriva.csv")
    escrever_markdown(medicao, args.saida / "f1-04-aec.md")

    print(f"\n{'atraso':>7} {'eco':>6} {'ERLE':>8} {'convergido':>11} {'fala sem':>9} {'com':>5}")
    for (atraso, ganho), valores in mediana_por_condicao(medicao).items():
        print(
            f"{atraso:5d}ms {ganho:5d}dB {valores['erle_total']:7.1f}dB "
            f"{valores['erle_convergido']:10.1f}dB {valores['fala_sem']:9.0f} "
            f"{valores['fala_com']:5.0f}"
        )
    for ppm, erle, finito in medicao.deriva:
        print(f"deriva {ppm:+.0f} ppm: ERLE {erle:.1f} dB, finito: {finito}")
    for o_que, _ in medicao.lacunas:
        print(f"não medido: {o_que}")
    print(f"\ncsv e relatório em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
