"""WER/CER de pt-BR, SLO-3 e o custo real do ASR incremental (cartão F1-06).

    uv run --frozen python tools/harness_asr.py                 # publica em docs/medicoes
    uv run --frozen python tools/harness_asr.py --itens 8 --motores oraculo --saida /tmp/x

**Ressalva que vale para toda a tabela:** o corpus é **TTS sintético** — material fácil. Voz
sem sotaque, sem ruído de casa, sem nome próprio difícil, com prosódia limpa. WER aqui é piso
otimista, e WER na voz do dono é F1-15/F1-16. Quem citar este número sem a ressalva está
citando errado.

O que cada coluna é:

- **WER/CER**: erro do `FinalTranscript` contra o `texto` do rótulo, com a normalização de
  `jarvis.corpus.metricas` (minúsculas, sem pontuação, **acento preservado**);
- **áudio até o 1º parcial utilizável**: o SLO-3 em tempo de áudio — quanto o dono precisa ter
  falado antes de existir parcial com `stability >= 0,6` (limiar escrito antes de medir);
- **custo de CPU e RTF**: quanto de processador a estratégia de janela crescente gasta por
  segundo de áudio. RTF acima de 1,0 significa que **não dá** para rodar ao vivo nesta máquina
  com este modelo — e isso é resultado, não detalhe.
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

from jarvis.agentd.asr import (
    ESTABILIDADE_MINIMA,
    PASSO_PADRAO_MS,
    MotorDeAsr,
    MotorDeReferencia,
    MotorWhisper,
    TranscritorIncremental,
)
from jarvis.audio_io.aec import quadros_de
from jarvis.audio_io.quadro import BYTES_POR_AMOSTRA, TAXA_PADRAO
from jarvis.corpus.metricas import cer, wer
from jarvis.corpus.rotulos import Rotulo, ler_rotulos
from jarvis.medicao import hardware, percentil

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_SAIDA: Final = RAIZ / "docs" / "medicoes"
CORPUS_PADRAO: Final = RAIZ / "corpus" / "turnos"
PASTA_WHISPER: Final = Path.home() / ".cache" / "jarvis" / "modelos" / "whisper"
SESSAO: Final = "0193f0a0-0000-7000-8000-000000000000"
SLO3_P50_MS: Final = 250.0
SLO3_P95_MS: Final = 450.0
"""Alvo da SPEC §7. A tabela diz, por implementação, se foi atingido — sem reescrever o alvo."""


@dataclass(frozen=True, slots=True)
class Resultado:
    """O que um motor fez com um item."""

    item: str
    motor: str
    passo_ms: float
    modelo: str
    licenca: str
    referencia: str
    hipotese: str
    wer: float
    cer: float
    passos: int
    audio_ms: float
    audio_ate_utilizavel_ms: float | None
    cpu_ms: float
    parede_ms: float

    @property
    def rtf_cpu(self) -> float:
        """CPU somada entre threads por segundo de áudio."""
        return self.cpu_ms / self.audio_ms if self.audio_ms else 0.0

    @property
    def rtf_parede(self) -> float:
        """Tempo de parede por segundo de áudio: é este que responde "dá para rodar ao vivo?"."""
        return self.parede_ms / self.audio_ms if self.audio_ms else 0.0


@dataclass(slots=True)
class Medicao:
    itens: int
    resultados: list[Resultado] = field(default_factory=list)
    lacunas: list[tuple[str, str]] = field(default_factory=list)


def ler_wav(caminho: Path) -> bytes:
    with wave.open(str(caminho), "rb") as arquivo:
        return arquivo.readframes(arquivo.getnframes())


def motor_de(nome: str, rotulo: Rotulo, amostras: bytes) -> MotorDeAsr:
    if nome == "oraculo":
        duracao = 1000.0 * (len(amostras) // BYTES_POR_AMOSTRA) / TAXA_PADRAO
        return MotorDeReferencia(texto=rotulo.texto, duracao_ms=duracao)
    tamanho = nome.removeprefix("whisper-")
    return MotorWhisper(tamanho=tamanho, pasta=str(PASTA_WHISPER))


def rodar_item(
    rotulo: Rotulo, amostras: bytes, nome_motor: str, *, passo_ms: float = PASSO_PADRAO_MS
) -> Resultado:
    motor = motor_de(nome_motor, rotulo, amostras)
    transcritor = TranscritorIncremental(motor=motor, passo_ms=passo_ms)
    transcritor.comecar(session_id=SESSAO, epoch=1)

    inicio_cpu = time.process_time_ns()
    inicio_parede = time.monotonic_ns()
    for quadro in quadros_de(amostras):
        transcritor.ouvir(quadro)
    finais = transcritor.fechar()
    cpu_ms = (time.process_time_ns() - inicio_cpu) / 1e6
    parede_ms = (time.monotonic_ns() - inicio_parede) / 1e6

    hipotese = str(finais[0].payload["text"]) if finais else ""
    utilizavel = transcritor.primeiro_utilizavel_ms()
    return Resultado(
        item=rotulo.id,
        motor=f"{transcritor.nome} passo={passo_ms:.0f}ms",
        passo_ms=passo_ms,
        modelo=motor.modelo,
        licenca=motor.licenca,
        referencia=rotulo.texto,
        hipotese=hipotese,
        wer=wer(rotulo.texto, hipotese).taxa,
        cer=cer(rotulo.texto, hipotese).taxa,
        passos=len(transcritor.passos),
        audio_ms=transcritor.ouvido_ms,
        audio_ate_utilizavel_ms=(
            None if utilizavel is None else utilizavel - rotulo.inicio_fala_ms
        ),
        cpu_ms=cpu_ms,
        parede_ms=parede_ms,
    )


def amostra_equilibrada(rotulos: Sequence[Rotulo], quantos: int) -> list[Rotulo]:
    """Metade fim de turno, metade meio de frase — a mesma proporção do corpus."""
    fins = [r for r in rotulos if r.fim_de_turno]
    meios = [r for r in rotulos if not r.fim_de_turno]
    metade = quantos // 2
    return fins[:metade] + meios[: quantos - metade]


def resumo(medicao: Medicao) -> dict[str, dict[str, float | str]]:
    por_motor: dict[str, list[Resultado]] = {}
    for resultado in medicao.resultados:
        por_motor.setdefault(resultado.motor, []).append(resultado)
    saida: dict[str, dict[str, float | str]] = {}
    for nome, grupo in sorted(por_motor.items()):
        utilizaveis = [
            r.audio_ate_utilizavel_ms for r in grupo if r.audio_ate_utilizavel_ms is not None
        ]
        saida[nome] = {
            "modelo": grupo[0].modelo,
            "licenca": grupo[0].licenca,
            "n": float(len(grupo)),
            "wer_medio": statistics.mean(r.wer for r in grupo),
            "wer_p50": percentil([r.wer for r in grupo], 50),
            "cer_medio": statistics.mean(r.cer for r in grupo),
            "sem_utilizavel": float(len(grupo) - len(utilizaveis)),
            "slo3_p50": percentil(utilizaveis, 50),
            "slo3_p95": percentil(utilizaveis, 95),
            "rtf_cpu_p50": percentil([r.rtf_cpu for r in grupo], 50),
            "rtf_parede_p50": percentil([r.rtf_parede for r in grupo], 50),
            "rtf_parede_p95": percentil([r.rtf_parede for r in grupo], 95),
            "passos_p50": percentil([float(r.passos) for r in grupo], 50),
            "atinge_slo3": (
                percentil(utilizaveis, 50) <= SLO3_P50_MS
                and percentil(utilizaveis, 95) <= SLO3_P95_MS
            ),
        }
    return saida


def escrever_csv(medicao: Medicao, caminho: Path) -> None:
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(
            [
                "item",
                "motor",
                "passo_ms",
                "modelo",
                "licenca",
                "wer",
                "cer",
                "passos",
                "audio_ms",
                "audio_ate_utilizavel_ms",
                "cpu_ms",
                "parede_ms",
                "rtf_cpu",
                "rtf_parede",
                "referencia",
                "hipotese",
            ]
        )
        for r in medicao.resultados:
            escritor.writerow(
                [
                    r.item,
                    r.motor,
                    f"{r.passo_ms:.0f}",
                    r.modelo,
                    r.licenca,
                    f"{r.wer:.4f}",
                    f"{r.cer:.4f}",
                    r.passos,
                    f"{r.audio_ms:.0f}",
                    "" if r.audio_ate_utilizavel_ms is None else f"{r.audio_ate_utilizavel_ms:.0f}",
                    f"{r.cpu_ms:.1f}",
                    f"{r.parede_ms:.1f}",
                    f"{r.rtf_cpu:.3f}",
                    f"{r.rtf_parede:.3f}",
                    r.referencia,
                    r.hipotese,
                ]
            )


def escrever_markdown(medicao: Medicao, caminho: Path) -> None:
    maquina = hardware()
    tabela = resumo(medicao)
    linhas = [
        "# F1-06 — ASR incremental: WER de pt-BR, SLO-3 e o custo da janela crescente",
        "",
        "**Gerado por** `tools/harness_asr.py` (não editar à mão). **Data:** "
        f"{time.strftime('%Y-%m-%d')}.",
        "",
        "> **Ressalva obrigatória: o corpus é TTS sintético, material fácil.** Sem sotaque, sem "
        "ruído de casa, sem nome próprio difícil, prosódia limpa. O WER daqui é piso otimista; "
        "WER na voz do dono é F1-15/F1-16.",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {maquina['cpu']}, {maquina['nucleos']} fios, {maquina['memoria']} de RAM",
        f"- {maquina['plataforma']}, Python {maquina['python']}",
        f"- {medicao.itens} itens do split `calibracao` (metade fim de turno, metade hesitação)",
        f"- alvo da SPEC §7 para o SLO-3: **p50 ≤ {SLO3_P50_MS:.0f} ms, p95 ≤ "
        f"{SLO3_P95_MS:.0f} ms** (marcado lá como hipótese, não compromisso)",
        "- estratégia incremental: janela crescente a cada passo declarado + acordo de prefixo; "
        f"**utilizável** = `stability >= {ESTABILIDADE_MINIMA}`, limiar escrito antes de medir",
        "- normalização de WER/CER: minúsculas, sem pontuação, **acento preservado** "
        "(`jarvis.corpus.metricas`)",
        "- `oráculo` não é ASR: devolve o texto do rótulo e serve para separar o custo do "
        "**encanamento** do custo do **modelo**",
        "",
        "## Resultado por implementação",
        "",
        "| motor | modelo | licença | n | WER médio | WER p50 | CER médio | SLO-3 p50 | "
        "SLO-3 p95 | atinge o SLO-3? | sem parcial utilizável |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|:--|---:|",
    ]
    for nome, valores in tabela.items():
        linhas.append(
            f"| `{nome}` | `{valores['modelo']}` | {valores['licenca']} | {valores['n']:.0f} "
            f"| {float(valores['wer_medio']):.3f} | {float(valores['wer_p50']):.3f} "
            f"| {float(valores['cer_medio']):.3f} | {float(valores['slo3_p50']):.0f} ms "
            f"| {float(valores['slo3_p95']):.0f} ms "
            f"| {'sim' if valores['atinge_slo3'] else '**não**'} "
            f"| {valores['sem_utilizavel']:.0f} |"
        )
    linhas += [
        "",
        "## Custo de CPU da janela crescente",
        "",
        "| motor | passos p50 | RTF de parede p50 | RTF de parede p95 | RTF de CPU p50 |",
        "|---|---:|---:|---:|---:|",
    ]
    for nome, valores in tabela.items():
        linhas.append(
            f"| `{nome}` | {float(valores['passos_p50']):.0f} "
            f"| {float(valores['rtf_parede_p50']):.2f}× "
            f"| {float(valores['rtf_parede_p95']):.2f}× "
            f"| {float(valores['rtf_cpu_p50']):.2f}× |"
        )
    linhas += [
        "",
        "RTF (*real-time factor*) é tempo gasto por segundo de áudio. O de **parede** é o que "
        'responde "dá para rodar ao vivo?": acima de 1,0, **não dá** nesta máquina com este '
        "modelo. O de **CPU** soma as threads e mostra quanto da máquina o ASR consome. A "
        "janela crescente re-transcreve o turno inteiro a cada passo, então o custo cresce com "
        "o quadrado da duração — o caminho para o v1 é modelo *streaming* (um transducer como "
        "o `parakeet-tdt` decodifica por quadro, sem refazer o passado) ou GPU.",
        "",
        "## O que não foi medido",
        "",
    ]
    linhas += [f"- **{o_que}** — {por_que}" for o_que, por_que in medicao.lacunas]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--corpus", type=Path, default=CORPUS_PADRAO)
    analisa.add_argument("--itens", type=int, default=40)
    analisa.add_argument(
        "--motores",
        default="oraculo,whisper-small",
        help="implementações a medir, separadas por vírgula",
    )
    analisa.add_argument("--saida", type=Path, default=PASTA_SAIDA)
    analisa.add_argument(
        "--prefixo",
        default="f1-06-asr",
        help="prefixo dos arquivos publicados (um estudo separado não sobrescreve o principal)",
    )
    analisa.add_argument(
        "--passos-ms",
        default=str(int(PASSO_PADRAO_MS)),
        help="passos do incremental a medir, separados por vírgula (ex.: 100,200)",
    )
    args = analisa.parse_args(argv)

    rotulos = [
        r
        for r in ler_rotulos(args.corpus / "rotulos.jsonl")
        if r.sintetico and r.split == "calibracao"
    ]
    escolhidos = amostra_equilibrada(rotulos, args.itens)
    faltando = [r.id for r in escolhidos if not (args.corpus / r.arquivo).exists()]
    if faltando:
        print(f"FALHOU: {len(faltando)} item(ns) sem áudio em {args.corpus}")
        return 2

    passos = [float(p) for p in args.passos_ms.split(",") if p.strip()]
    medicao = Medicao(itens=len(escolhidos))
    for nome in (m.strip() for m in args.motores.split(",") if m.strip()):
        for passo in passos:
            for rotulo in escolhidos:
                try:
                    medicao.resultados.append(
                        rodar_item(
                            rotulo,
                            ler_wav(args.corpus / rotulo.arquivo),
                            nome,
                            passo_ms=passo,
                        )
                    )
                except RuntimeError as erro:
                    print(f"FALHOU ({nome}): {erro}")
                    return 2

    medicao.lacunas += [
        (
            "WER na voz do dono",
            "com o microfone e o ruído dele, sotaque, nome próprio e termo do domínio: é "
            "F1-15 (corpus real) e F1-16 (aceite)",
        ),
        (
            "SLO-3 ao vivo",
            "aqui é tempo de áudio sobre arquivo; ao vivo entram captura, AEC, VAD e a fila do "
            "driver",
        ),
        (
            "nvidia/parakeet-tdt-0.6b-v3",
            "registrado e verificado na origem (CC-BY-4.0, 25 idiomas com pt), mas NÃO "
            "executado: o runtime é o NeMo, pesado e orientado a GPU. A comparação com o "
            "whisper em pt-BR real é do F1-16",
        ),
        (
            "whisper-large-v3",
            "3 GB: o que rodou foi o `small`, mesma família e mesma licença (Apache-2.0)",
        ),
        ("Windows", "a medição rodou só em Linux"),
    ]

    args.saida.mkdir(parents=True, exist_ok=True)
    escrever_csv(medicao, args.saida / f"{args.prefixo}.csv")
    escrever_markdown(medicao, args.saida / f"{args.prefixo}.md")

    for nome, valores in resumo(medicao).items():
        print(
            f"{nome:28.28} WER {float(valores['wer_medio']):.3f} "
            f"CER {float(valores['cer_medio']):.3f} "
            f"SLO-3 p50 {float(valores['slo3_p50']):.0f} ms p95 {float(valores['slo3_p95']):.0f} "
            f"ms RTF parede {float(valores['rtf_parede_p50']):.2f}x "
            f"CPU {float(valores['rtf_cpu_p50']):.2f}x"
        )
    print(f"\ncsv e relatório em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
