"""Tempo até o primeiro pedaço e piso do SLO-5, por candidato de voz (cartão F1-09).

    uv run --frozen python tools/harness_tts.py                     # publica em docs/medicoes
    uv run --frozen python tools/harness_tts.py --motores parametrico --itens 10 --saida /tmp/x

O que cada número é:

- **até o primeiro pedaço**: do pedido de fala até existir o primeiro `Pedaco` pronto para a
  fila. É o que o SLO-5 sente primeiro, e é por isso que o primeiro pedaço é curto;
- **piso do SLO-5** (fim de turno aceito → primeiro áudio): o mesmo tempo **mais** o primeiro
  tick da fila de playback, sobre sumidouro de memória. A SPEC §7 pede p50 ≤ 600 ms e
  p95 ≤ 900 ms; aqui é **piso de software**, porque a fila do dispositivo não está na conta;
- **RTF**: tempo de síntese por segundo de áudio produzido. Acima de 1,0 a voz não acompanha a
  própria fala.

**O fonemizador é injetado**, e é aí que mora a pendência de licença do caminho de produto: as
quatro vozes pt-BR do piper usam fonemas do espeak-ng (GPL-3.0). Aqui ele roda como ferramenta
de medição, como no F1-02; no produto, não pode. A decisão é do dono (F1-16) e está nas notas.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.agentd.tts import (
    MotorDeTts,
    MotorParametrico,
    MotorPiperOnnx,
    SintetizadorEmStreaming,
    VozRecusada,
)
from jarvis.audio_io.playback import FilaDePlayback
from jarvis.audio_io.sumidouros import SumidouroEmMemoria
from jarvis.corpus.rotulos import ler_rotulos
from jarvis.medicao import hardware, percentil

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_SAIDA: Final = RAIZ / "docs" / "medicoes"
CORPUS_PADRAO: Final = RAIZ / "corpus" / "turnos"
PASTA_VOZES: Final = Path.home() / ".cache" / "jarvis" / "vozes"
VOZ_PIPER: Final = "pt_BR-faber-medium"
ID_REGISTRADO: Final = "rhasspy/piper-voices:pt_BR-faber-medium"
SESSAO: Final = "0193f0a0-0000-7000-8000-000000000000"
SLO5_P50_MS: Final = 600.0
SLO5_P95_MS: Final = 900.0


def fonemizar_com_espeak(texto: str) -> str:
    """O pedaço GPL, que mora em `tools/` e entra no motor por injeção (SPEC §4: argv fixo).

    O caminho do binário é **resolvido** por `shutil.which` em vez de passado por nome: nome
    parcial depende do `PATH` de quem chama, e a mensagem de erro de binário ausente vale mais
    do que um `FileNotFoundError` cru.
    """
    caminho = shutil.which("espeak-ng")
    if caminho is None:
        raise VozRecusada(
            "espeak-ng não está instalado: é o fonemizador da MEDIÇÃO (GPL-3.0, fora do "
            "produto). No Fedora/Nobara: `sudo dnf install espeak-ng`."
        )
    concluido = subprocess.run(
        [caminho, "-v", "pt-br", "-q", "--ipa"],
        input=texto,
        capture_output=True,
        text=True,
        check=True,
    )
    return " ".join(parte.strip() for parte in concluido.stdout.split("\n") if parte.strip())


@dataclass(frozen=True, slots=True)
class Resultado:
    motor: str
    voz: str
    licenca: str
    item: str
    palavras: int
    primeiro_pedaco_ms: float
    piso_slo5_ms: float
    total_ms: float
    amostras: int
    pedacos: int

    @property
    def rtf(self) -> float:
        segundos = self.amostras / 16_000
        return (self.total_ms / 1000) / segundos if segundos else 0.0


@dataclass(slots=True)
class Medicao:
    itens: int
    resultados: list[Resultado] = field(default_factory=list)
    lacunas: list[tuple[str, str]] = field(default_factory=list)


def motor_de(nome: str) -> MotorDeTts:
    if nome == "parametrico":
        return MotorParametrico()
    motor = MotorPiperOnnx(
        caminho=PASTA_VOZES / VOZ_PIPER / f"{VOZ_PIPER}.onnx",
        fonemizar=fonemizar_com_espeak,
        voz=VOZ_PIPER,
        identificador_registrado=ID_REGISTRADO,
    )
    motor.abrir()
    return motor


def medir_item(motor: MotorDeTts, texto: str, item: str) -> Resultado:
    """Mede o caminho `agentd → audio-io`: síntese por pedaços e o primeiro tick da fila."""
    sumidouro = SumidouroEmMemoria()
    fila = FilaDePlayback(sumidouro=sumidouro, session_id=SESSAO)
    sintetizador = SintetizadorEmStreaming(motor=motor, session_id=SESSAO, epoch=1)

    inicio = time.perf_counter_ns()
    primeiro: float | None = None
    piso: float | None = None
    pedacos = 0
    amostras = 0
    for pedaco, _ in sintetizador.pedacos(texto, chunk_id=item):
        if primeiro is None:
            primeiro = (time.perf_counter_ns() - inicio) / 1e6
        fila.enfileirar(pedaco)
        pedacos += 1
        amostras += pedaco.n_amostras
        if piso is None:
            fila.tick()  # primeiro áudio saindo para o sumidouro
            piso = (time.perf_counter_ns() - inicio) / 1e6
    total = (time.perf_counter_ns() - inicio) / 1e6
    return Resultado(
        motor=motor.nome,
        voz=motor.voz,
        licenca=motor.licenca,
        item=item,
        palavras=len(texto.split()),
        primeiro_pedaco_ms=primeiro or 0.0,
        piso_slo5_ms=piso or 0.0,
        total_ms=total,
        amostras=amostras,
        pedacos=pedacos,
    )


def resumo(medicao: Medicao) -> dict[str, dict[str, float | str]]:
    por_motor: dict[str, list[Resultado]] = {}
    for r in medicao.resultados:
        por_motor.setdefault(r.motor, []).append(r)
    saida: dict[str, dict[str, float | str]] = {}
    for nome, grupo in sorted(por_motor.items()):
        primeiros = [r.primeiro_pedaco_ms for r in grupo]
        pisos = [r.piso_slo5_ms for r in grupo]
        saida[nome] = {
            "voz": grupo[0].voz,
            "licenca": grupo[0].licenca,
            "n": float(len(grupo)),
            "primeiro_p50": percentil(primeiros, 50),
            "primeiro_p95": percentil(primeiros, 95),
            "piso_p50": percentil(pisos, 50),
            "piso_p95": percentil(pisos, 95),
            "rtf_p50": percentil([r.rtf for r in grupo], 50),
            "atinge_slo5": (
                percentil(pisos, 50) <= SLO5_P50_MS and percentil(pisos, 95) <= SLO5_P95_MS
            ),
        }
    return saida


def escrever_csv(medicao: Medicao, caminho: Path) -> None:
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(
            [
                "motor",
                "voz",
                "licenca",
                "item",
                "palavras",
                "primeiro_pedaco_ms",
                "piso_slo5_ms",
                "total_ms",
                "amostras",
                "pedacos",
                "rtf",
            ]
        )
        for r in medicao.resultados:
            escritor.writerow(
                [
                    r.motor,
                    r.voz,
                    r.licenca,
                    r.item,
                    r.palavras,
                    f"{r.primeiro_pedaco_ms:.3f}",
                    f"{r.piso_slo5_ms:.3f}",
                    f"{r.total_ms:.3f}",
                    r.amostras,
                    r.pedacos,
                    f"{r.rtf:.3f}",
                ]
            )


def escrever_markdown(medicao: Medicao, caminho: Path) -> None:
    maquina = hardware()
    tabela = resumo(medicao)
    linhas = [
        "# F1-09 — TTS em streaming: primeiro pedaço, piso do SLO-5 e licença da voz",
        "",
        "**Gerado por** `tools/harness_tts.py` (não editar à mão). **Data:** "
        f"{time.strftime('%Y-%m-%d')}.",
        "",
        "> **Piso de software, sem dispositivo.** A fila do driver não está na conta, e é "
        "justamente ela que atrasa o primeiro áudio de verdade. SLO-5 real e qualidade da voz "
        "são julgamento do dono (F1-16).",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {maquina['cpu']}, {maquina['nucleos']} fios, {maquina['memoria']} de RAM",
        f"- {maquina['plataforma']}, Python {maquina['python']}",
        f"- {medicao.itens} textos do corpus de turnos, um turno por item",
        "- primeiro pedaço = 3 palavras (ou até a primeira pontuação); demais, 8",
        f"- alvo da SPEC §7 para o SLO-5: p50 ≤ {SLO5_P50_MS:.0f} ms, p95 ≤ {SLO5_P95_MS:.0f} ms",
        "- o fonemizador do piper é o `espeak-ng` (GPL-3.0), **injetado** pela ferramenta de "
        "medição: no produto ele não pode entrar (ver notas do executor)",
        "",
        "## Resultado por candidato",
        "",
        "| motor | voz | licença | n | 1º pedaço p50 | 1º pedaço p95 | piso SLO-5 p50 | "
        "piso SLO-5 p95 | atinge SLO-5? | RTF p50 |",
        "|---|---|---|---:|---:|---:|---:|---:|:--|---:|",
    ]
    for nome, v in tabela.items():
        linhas.append(
            f"| `{nome}` | `{v['voz']}` | {v['licenca']} | {v['n']:.0f} "
            f"| {float(v['primeiro_p50']):.1f} ms | {float(v['primeiro_p95']):.1f} ms "
            f"| {float(v['piso_p50']):.1f} ms | {float(v['piso_p95']):.1f} ms "
            f"| {'sim' if v['atinge_slo5'] else '**não**'} | {float(v['rtf_p50']):.3f}× |"
        )
    linhas += ["", "## O que não foi medido", ""]
    linhas += [f"- **{o_que}** — {por_que}" for o_que, por_que in medicao.lacunas]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--corpus", type=Path, default=CORPUS_PADRAO)
    analisa.add_argument("--itens", type=int, default=40)
    analisa.add_argument("--motores", default="parametrico,piper")
    analisa.add_argument("--saida", type=Path, default=PASTA_SAIDA)
    args = analisa.parse_args(argv)

    rotulos = [r for r in ler_rotulos(args.corpus / "rotulos.jsonl") if r.sintetico][: args.itens]
    if not rotulos:
        print(f"FALHOU: sem rótulos em {args.corpus}")
        return 2

    medicao = Medicao(itens=len(rotulos))
    for nome in (m.strip() for m in args.motores.split(",") if m.strip()):
        try:
            motor = motor_de(nome)
        except (VozRecusada, FileNotFoundError) as erro:
            print(f"FALHOU ({nome}): {erro}")
            return 2
        for rotulo in rotulos:
            medicao.resultados.append(medir_item(motor, rotulo.texto, rotulo.id))

    medicao.lacunas += [
        (
            "SLO-5 de verdade",
            "a fila do dispositivo entra na conta e não está aqui: o primeiro áudio audível "
            "depende do driver (F1-16, máquina do dono)",
        ),
        (
            "qualidade e naturalidade da voz pt-BR",
            "é julgamento do dono, não teste: ele escolhe a voz no F1-16",
        ),
        (
            "fonemização permissiva para pt-BR",
            "as quatro vozes pt-BR do piper usam espeak-ng (GPL-3.0), verificado voz por voz. "
            "No produto isso não entra; a decisão (G2P próprio, modelo que aceite grafema, ou "
            "outra família de voz) é do dono",
        ),
        (
            "Kokoro-82M",
            "registrado (Apache-2.0) e **não** executado: também depende de fonemizador externo "
            "para pt-BR, então não resolve a pendência de licença",
        ),
        ("Windows", "a medição rodou só em Linux"),
    ]

    args.saida.mkdir(parents=True, exist_ok=True)
    escrever_csv(medicao, args.saida / "f1-09-tts.csv")
    escrever_markdown(medicao, args.saida / "f1-09-tts.md")

    for nome, v in resumo(medicao).items():
        print(
            f"{nome:34.34} 1º pedaço p50 {float(v['primeiro_p50']):7.1f} ms "
            f"piso SLO-5 p50 {float(v['piso_p50']):7.1f} ms p95 {float(v['piso_p95']):7.1f} ms "
            f"RTF {float(v['rtf_p50']):.3f}x"
        )
    print(f"\ncsv e relatório em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
