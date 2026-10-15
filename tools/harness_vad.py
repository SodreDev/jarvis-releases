"""VAD medido contra os marcos do corpus, e o piso de SLO-1 com a cadeia real (cartão F1-05).

    uv run --frozen python tools/harness_vad.py                       # publica em docs/medicoes
    uv run --frozen python tools/harness_vad.py --itens 20 --execucoes 1 --saida /tmp/x

Três coisas, nesta ordem de importância:

1. **Acerto do início de fala** (aceite (a)): atraso de detecção por item e matriz de confusão
   por quadro, contra o `inicio_fala_ms` que o gerador do corpus gravou no rótulo — não contra
   um palpite nosso sobre onde a fala começa.
2. **Piso de SLO-1** (aceite (c)): `quadro → AudioActivity` com a cadeia **real** (AEC → NR →
   AGC → VAD → envelope validado), p50/p95/p99, três execuções.
3. **Reconfirmação da F0-04** (aceite (d)): a F0-04 mediu VAD 0,1129 ms p95 e evento
   0,3842 ms p95 em braços separados. Aqui a cadeia inteira é medida junta, e a decomposição
   sai da diferença entre o braço com evento e o braço sem evento.

**A matriz por quadro só cobre a região até o início da pausa.** Depois dela o VAD continua
dizendo "fala" de propósito (histerese e *hangover*): pausa entre palavras não é fim de fala, e
fim de **turno** é outro componente (F1-07). Contar hangover como erro seria medir o VAD contra
um trabalho que não é dele — então o hangover aparece como **caracterização** (quantos ms o VAD
segura depois do início da pausa), não como falso positivo.
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
from typing import Final

from jarvis.audio_io.aec import CadeiaDeAec, quadros_de
from jarvis.audio_io.captura import Captura
from jarvis.audio_io.fontes import FonteDeArquivo
from jarvis.audio_io.quadro import MS_POR_QUADRO
from jarvis.audio_io.vad import (
    Histerese,
    Vad,
    VadDeEnergia,
    VadSilero,
    vad_do_ambiente,
)
from jarvis.barramento.envelope import uuid7
from jarvis.corpus.rotulos import Rotulo, ler_rotulos
from jarvis.medicao import hardware, percentil
from jarvis.relogio import RelogioFalso

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_SAIDA: Final = RAIZ / "docs" / "medicoes"
CORPUS_PADRAO: Final = RAIZ / "corpus" / "turnos"
TOLERANCIA_ANTES_MS: Final = 100.0
"""Disparar antes disso do início verdadeiro é falso positivo, não acerto adiantado."""
TOLERANCIA_DEPOIS_MS: Final = 500.0
"""Depois disso, o início não foi detectado (para o SLO-1, 500 ms já é atraso absurdo)."""
SLO1_MS: Final = 80.0
"""SLO-1 (SPEC §7). Se o piso passar daqui, o cartão termina em `precisa_decisao` (ADR-0014)."""


@dataclass(frozen=True, slots=True)
class Acerto:
    """O que o VAD fez com um item do corpus."""

    item: str
    vad: str
    inicio_verdadeiro_ms: int
    inicio_detectado_ms: float | None
    atraso_ms: float | None
    verdadeiro_positivo: int
    falso_positivo: int
    falso_negativo: int
    verdadeiro_negativo: int
    hangover_ms: float | None


@dataclass(frozen=True, slots=True)
class Braco:
    nome: str
    execucao: int
    n: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    observacao: str = ""


@dataclass(slots=True)
class Medicao:
    itens: int
    execucoes: int
    acertos: list[Acerto] = field(default_factory=list)
    bracos: list[Braco] = field(default_factory=list)
    lacunas: list[tuple[str, str]] = field(default_factory=list)


def ler_wav(caminho: Path) -> bytes:
    with wave.open(str(caminho), "rb") as arquivo:
        return arquivo.readframes(arquivo.getnframes())


def verdade_por_quadro(rotulo: Rotulo, quadros: int) -> list[bool]:
    """Fala ou silêncio em cada quadro, a partir dos marcos que o gerador gravou."""
    fim_da_pausa = rotulo.inicio_pausa_ms + rotulo.pausa_ms
    verdade: list[bool] = []
    for indice in range(quadros):
        inicio_ms = indice * MS_POR_QUADRO
        if inicio_ms < rotulo.inicio_fala_ms:
            verdade.append(False)
        elif inicio_ms < rotulo.inicio_pausa_ms:
            verdade.append(True)
        elif inicio_ms < fim_da_pausa:
            verdade.append(False)
        else:
            verdade.append(bool(rotulo.texto_depois))
    return verdade


def avaliar_item(rotulo: Rotulo, amostras: bytes, vad: Vad) -> Acerto:
    """Roda o VAD no item inteiro e compara com os marcos."""
    quadros = quadros_de(amostras)
    verdade = verdade_por_quadro(rotulo, len(quadros))
    inicio_detectado: float | None = None
    estados: list[bool] = []
    for indice, quadro in enumerate(quadros):
        mudou = vad.ver(quadro)
        if mudou is True and inicio_detectado is None:
            inicio_detectado = indice * MS_POR_QUADRO
        estados.append(bool(vad.falando))

    limite = min(
        len(quadros), max(1, int(rotulo.inicio_pausa_ms / MS_POR_QUADRO))
    )  # região sem ambiguidade
    vp = sum(1 for i in range(limite) if verdade[i] and estados[i])
    fp = sum(1 for i in range(limite) if not verdade[i] and estados[i])
    fn = sum(1 for i in range(limite) if verdade[i] and not estados[i])
    vn = sum(1 for i in range(limite) if not verdade[i] and not estados[i])

    atraso = None if inicio_detectado is None else inicio_detectado - rotulo.inicio_fala_ms
    # Hangover é a TRANSIÇÃO para silêncio depois do início da pausa, não "o primeiro quadro
    # em que o estado é falso": o VAD de energia oscila entre sílabas, e tratar um vale como
    # desligamento daria 0 ms. `None` quando o arquivo acabou antes de o VAD desligar — que é
    # diferente de desligar na hora, e a primeira versão desta conta confundia as duas coisas.
    hangover: float | None = None
    for indice in range(max(1, limite), len(quadros)):
        if estados[indice - 1] and not estados[indice]:
            hangover = indice * MS_POR_QUADRO - rotulo.inicio_pausa_ms
            break
    return Acerto(
        item=rotulo.id,
        vad=vad.nome,
        inicio_verdadeiro_ms=rotulo.inicio_fala_ms,
        inicio_detectado_ms=inicio_detectado,
        atraso_ms=atraso,
        verdadeiro_positivo=vp,
        falso_positivo=fp,
        falso_negativo=fn,
        verdadeiro_negativo=vn,
        hangover_ms=hangover,
    )


def novo_vad(nome: str, caminho_modelo: Path | None) -> Vad:
    if nome == "energia":
        return VadDeEnergia(histerese=Histerese())
    if caminho_modelo is not None:
        return VadSilero(caminho=caminho_modelo, histerese=Histerese())
    return vad_do_ambiente()


def medir_acertos(
    rotulos: Sequence[Rotulo], pasta: Path, *, vads: Sequence[str], caminho_modelo: Path | None
) -> list[Acerto]:
    acertos: list[Acerto] = []
    for nome in vads:
        for rotulo in rotulos:
            vad = novo_vad(nome, caminho_modelo)
            acertos.append(avaliar_item(rotulo, ler_wav(pasta / rotulo.arquivo), vad))
    return acertos


def medir_piso(
    caminhos: Sequence[Path],
    *,
    nome_vad: str,
    caminho_modelo: Path | None,
    execucao: int,
    com_evento: bool,
) -> Braco:
    """Tempo de `tick` com a cadeia real, acumulado em vários itens.

    Vários itens porque o evento sai nas **transições**: um item dá dois ou três
    `AudioActivity`, e p95 de três amostras não é p95. A cadeia é recriada por item, como
    acontece numa sessão nova.
    """
    com: list[float] = []
    sem: list[float] = []
    vad = novo_vad(nome_vad, caminho_modelo)
    for caminho in caminhos:
        relogio = RelogioFalso()
        captura = Captura(
            fonte=FonteDeArquivo(caminho=caminho, relogio=relogio),
            relogio=relogio,
            session_id=uuid7(),
            detector=novo_vad(nome_vad, caminho_modelo),
            cadeia=CadeiaDeAec(),
            tocando=lambda: False,
        )
        captura.abrir()
        try:
            while True:
                vistos = captura.quadros
                antes = time.perf_counter_ns()
                eventos = captura.tick()
                gasto = (time.perf_counter_ns() - antes) / 1e6
                if captura.quadros == vistos:
                    break
                (com if eventos else sem).append(gasto)
        finally:
            captura.fechar()
    tempos = com if com_evento else sem
    rotulo = "com evento" if com_evento else "sem evento"
    return Braco(
        nome=f"cadeia AEC+{vad.nome} ({rotulo})",
        execucao=execucao,
        n=len(tempos),
        p50_ms=percentil(tempos, 50),
        p95_ms=percentil(tempos, 95),
        p99_ms=percentil(tempos, 99),
        max_ms=max(tempos) if tempos else 0.0,
        observacao=(
            "AEC → NR → AGC → VAD → envelope da §3.1 validado na borda"
            if com_evento
            else "AEC → NR → AGC → VAD, sem publicar evento"
        ),
    )


def resumo_de_acertos(acertos: Sequence[Acerto]) -> dict[str, dict[str, float]]:
    por_vad: dict[str, list[Acerto]] = {}
    for acerto in acertos:
        por_vad.setdefault(acerto.vad, []).append(acerto)
    resumo: dict[str, dict[str, float]] = {}
    for nome, grupo in sorted(por_vad.items()):
        no_prazo = [
            a
            for a in grupo
            if a.atraso_ms is not None
            and -TOLERANCIA_ANTES_MS <= a.atraso_ms <= TOLERANCIA_DEPOIS_MS
        ]
        cedo = [a for a in grupo if a.atraso_ms is not None and a.atraso_ms < -TOLERANCIA_ANTES_MS]
        atrasos = [a.atraso_ms for a in no_prazo if a.atraso_ms is not None]
        vp = sum(a.verdadeiro_positivo for a in grupo)
        fp = sum(a.falso_positivo for a in grupo)
        fn = sum(a.falso_negativo for a in grupo)
        vn = sum(a.verdadeiro_negativo for a in grupo)
        resumo[nome] = {
            "itens": float(len(grupo)),
            "no_prazo": float(len(no_prazo)),
            "cedo": float(len(cedo)),
            "nao_detectou": float(len(grupo) - len(no_prazo) - len(cedo)),
            "recall_inicio": len(no_prazo) / len(grupo) if grupo else 0.0,
            "precisao_inicio": len(no_prazo) / max(1, len(no_prazo) + len(cedo)),
            "atraso_p50_ms": percentil(atrasos, 50),
            "atraso_p95_ms": percentil(atrasos, 95),
            "vp": float(vp),
            "fp": float(fp),
            "fn": float(fn),
            "vn": float(vn),
            "recall_quadro": vp / max(1, vp + fn),
            "precisao_quadro": vp / max(1, vp + fp),
            "hangover_p50_ms": percentil(
                [a.hangover_ms for a in grupo if a.hangover_ms is not None], 50
            ),
            "nunca_desligou": float(sum(1 for a in grupo if a.hangover_ms is None)),
        }
    return resumo


def resumo_de_bracos(medicao: Medicao) -> dict[str, dict[str, float]]:
    por_nome: dict[str, list[Braco]] = {}
    for braco in medicao.bracos:
        por_nome.setdefault(braco.nome, []).append(braco)
    return {
        nome: {
            "n": float(statistics.median(b.n for b in grupo)),
            "p50": statistics.median(b.p50_ms for b in grupo),
            "p95": statistics.median(b.p95_ms for b in grupo),
            "p99": statistics.median(b.p99_ms for b in grupo),
            "max": max(b.max_ms for b in grupo),
        }
        for nome, grupo in sorted(por_nome.items())
    }


def escrever_csv(medicao: Medicao, pasta: Path) -> None:
    with (pasta / "f1-05-vad.csv").open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(["braco", "execucao", "n", "p50_ms", "p95_ms", "p99_ms", "max_ms"])
        for b in medicao.bracos:
            escritor.writerow(
                [
                    b.nome,
                    b.execucao,
                    b.n,
                    f"{b.p50_ms:.6f}",
                    f"{b.p95_ms:.6f}",
                    f"{b.p99_ms:.6f}",
                    f"{b.max_ms:.6f}",
                ]
            )
    with (pasta / "f1-05-vad-acertos.csv").open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(
            [
                "item",
                "vad",
                "inicio_verdadeiro_ms",
                "inicio_detectado_ms",
                "atraso_ms",
                "vp",
                "fp",
                "fn",
                "vn",
                "hangover_ms",
            ]
        )
        for a in medicao.acertos:
            escritor.writerow(
                [
                    a.item,
                    a.vad,
                    a.inicio_verdadeiro_ms,
                    "" if a.inicio_detectado_ms is None else f"{a.inicio_detectado_ms:.0f}",
                    "" if a.atraso_ms is None else f"{a.atraso_ms:.0f}",
                    a.verdadeiro_positivo,
                    a.falso_positivo,
                    a.falso_negativo,
                    a.verdadeiro_negativo,
                    "" if a.hangover_ms is None else f"{a.hangover_ms:.0f}",
                ]
            )


def escrever_markdown(medicao: Medicao, caminho: Path) -> None:
    maquina = hardware()
    acertos = resumo_de_acertos(medicao.acertos)
    bracos = resumo_de_bracos(medicao)
    pior_p95 = max((v["p95"] for v in bracos.values()), default=0.0)
    linhas = [
        "# F1-05 — VAD: acerto de início de fala e piso de SLO-1",
        "",
        "**Gerado por** `tools/harness_vad.py` (não editar à mão). **Data:** "
        f"{time.strftime('%Y-%m-%d')}.",
        "",
        "> **Corpus sintético e piso de software.** Nenhum microfone foi aberto. VAD em ruído "
        "real da casa do dono e SLO-1 com captura de verdade são o F1-16.",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {maquina['cpu']}, {maquina['nucleos']} fios, {maquina['memoria']} de RAM",
        f"- {maquina['plataforma']}, Python {maquina['python']}",
        f"- {medicao.itens} itens do corpus sintético, {medicao.execucoes} execuções do piso",
        "- verdade de referência: `inicio_fala_ms` e `inicio_pausa_ms` do rótulo, que o gerador "
        "gravou (não é estimativa nossa sobre o áudio)",
        f"- acerto de início: detectar entre -{TOLERANCIA_ANTES_MS:.0f} ms e "
        f"+{TOLERANCIA_DEPOIS_MS:.0f} ms do início verdadeiro; antes disso é falso positivo",
        "- a matriz por quadro cobre só a região **até o início da pausa**: depois dela o VAD "
        "segura fala por projeto (histerese e hangover), e isso aparece como caracterização",
        "- `hangover` é a **transição** para silêncio depois do início da pausa; quando o "
        'arquivo acaba antes de o VAD desligar, o item entra na coluna "não desligou" em vez '
        "de virar 0 ms",
        "- o piso roda a cadeia real (AEC → NR → AGC → VAD → envelope validado), com relógio "
        "falso na fonte e `perf_counter_ns` no cronômetro",
        "",
        "## Acerto de início de fala (aceite (a))",
        "",
        "| VAD | itens | no prazo | cedo | não detectou | recall | precisão | atraso p50 | "
        "atraso p95 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for nome, valores in acertos.items():
        linhas.append(
            f"| `{nome}` | {valores['itens']:.0f} | {valores['no_prazo']:.0f} "
            f"| {valores['cedo']:.0f} | {valores['nao_detectou']:.0f} "
            f"| {valores['recall_inicio']:.3f} | {valores['precisao_inicio']:.3f} "
            f"| {valores['atraso_p50_ms']:.0f} ms | {valores['atraso_p95_ms']:.0f} ms |"
        )
    linhas += [
        "",
        "Matriz de confusão por quadro (até o início da pausa) e hangover:",
        "",
        "| VAD | VP | FP | FN | VN | recall | precisão | hangover p50 | não desligou no arquivo |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for nome, valores in acertos.items():
        linhas.append(
            f"| `{nome}` | {valores['vp']:.0f} | {valores['fp']:.0f} | {valores['fn']:.0f} "
            f"| {valores['vn']:.0f} | {valores['recall_quadro']:.3f} "
            f"| {valores['precisao_quadro']:.3f} | {valores['hangover_p50_ms']:.0f} ms "
            f"| {valores['nunca_desligou']:.0f}/{valores['itens']:.0f} |"
        )
    linhas += [
        "",
        "## Piso de SLO-1 (aceites (c) e (d))",
        "",
        "| caminho | n | p50 (ms) | p95 (ms) | p99 (ms) | máximo (ms) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for nome, valores in bracos.items():
        linhas.append(
            f"| `{nome}` | {valores['n']:.0f} | {valores['p50']:.4f} | {valores['p95']:.4f} "
            f"| {valores['p99']:.4f} | {valores['max']:.4f} |"
        )
    linhas += [
        "",
        f"**Veredito do gatilho da ADR-0014:** pior p95 medido = {pior_p95:.4f} ms contra o "
        f"orçamento de {SLO1_MS:.0f} ms do SLO-1 — "
        + (
            "dentro do orçamento, D1 não reabre."
            if pior_p95 < SLO1_MS
            else "**ESTOUROU**: o cartão termina em `precisa_decisao` e o gatilho da ADR-0014 "
            "abre. Não se ajusta o SLO."
        ),
        "",
        "## O que não foi medido",
        "",
    ]
    linhas += [f"- **{o_que}** — {por_que}" for o_que, por_que in medicao.lacunas]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--corpus", type=Path, default=CORPUS_PADRAO)
    analisa.add_argument("--itens", type=int, default=100, help="quantos itens do corpus")
    analisa.add_argument("--execucoes", type=int, default=3)
    analisa.add_argument("--saida", type=Path, default=PASTA_SAIDA)
    analisa.add_argument(
        "--vads",
        default="silero,energia",
        help="quais VADs medir, separados por vírgula (silero exige o peso baixado)",
    )
    analisa.add_argument("--modelo", type=Path, default=None, help="caminho do silero_vad.onnx")
    args = analisa.parse_args(argv)

    rotulos = [r for r in ler_rotulos(args.corpus / "rotulos.jsonl") if r.sintetico][: args.itens]
    faltando = [r.id for r in rotulos if not (args.corpus / r.arquivo).exists()]
    if faltando:
        print(
            f"FALHOU: {len(faltando)} item(ns) sem áudio em {args.corpus} (o áudio é derivado: "
            "regere com tools/corpus_sintetico.py)"
        )
        return 2

    vads = [nome.strip() for nome in args.vads.split(",") if nome.strip()]
    medicao = Medicao(itens=len(rotulos), execucoes=args.execucoes)
    try:
        medicao.acertos = medir_acertos(rotulos, args.corpus, vads=vads, caminho_modelo=args.modelo)
        caminhos = [args.corpus / r.arquivo for r in rotulos]
        for execucao in range(1, args.execucoes + 1):
            for nome in vads:
                for com_evento in (True, False):
                    medicao.bracos.append(
                        medir_piso(
                            caminhos,
                            nome_vad=nome,
                            caminho_modelo=args.modelo,
                            execucao=execucao,
                            com_evento=com_evento,
                        )
                    )
    except Exception as erro:
        print(f"FALHOU: {type(erro).__name__}: {erro}")
        return 2

    medicao.lacunas += [
        (
            "SLO-1 com microfone",
            "é o aceite (a) da F1 e sai no F1-16, na máquina do dono: jitter, período do driver "
            "e ruído de entrada são do hardware",
        ),
        (
            "VAD em ruído real da casa do dono",
            "o corpus tem ruído rosa sintético em ~30% dos itens; sala, televisão e conversa ao "
            "fundo são outra coisa",
        ),
        (
            "fim de turno",
            "o VAD não decide turno (§2): isso é o cartão F1-07, e o hangover desta tabela é "
            "política de fala, não de turno",
        ),
        ("Windows", "o código roda nos dois sistemas, mas a medição foi feita só em Linux"),
    ]

    args.saida.mkdir(parents=True, exist_ok=True)
    escrever_csv(medicao, args.saida)
    escrever_markdown(medicao, args.saida / "f1-05-vad.md")

    for nome, valores in resumo_de_acertos(medicao.acertos).items():
        print(
            f"{nome:22.22} recall {valores['recall_inicio']:.3f} "
            f"precisão {valores['precisao_inicio']:.3f} "
            f"atraso p50 {valores['atraso_p50_ms']:.0f} ms p95 {valores['atraso_p95_ms']:.0f} ms "
            f"hangover {valores['hangover_p50_ms']:.0f} ms "
            f"(não desligou em {valores['nunca_desligou']:.0f})"
        )
    for nome, valores in resumo_de_bracos(medicao).items():
        print(f"{nome:46.46} p50 {valores['p50']:.4f} ms p95 {valores['p95']:.4f} ms")
    print(f"\ncsv e relatório em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
