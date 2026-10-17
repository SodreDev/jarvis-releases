"""SLO-5 por trecho, com o cérebro em stream: do turno aceito ao primeiro áudio (ADR-0025, fatia 2).

    uv run --frozen python -m tools.harness_primeira_fala          # publica em docs/medicoes
    uv run --frozen python -m tools.harness_primeira_fala --motores roteirizado --saida /tmp/x

O caminho medido é o de produto, em memória: `Cerebro.responder` numa linha de execução,
publicando `ResponseChunk`; o TTS consumindo o stream (`falar_stream_para`); a fila de playback
dando o primeiro tick. Os trechos, todos contados do **turno aceito** (o início do SLO-5):

- **montagem** — o contexto pronto para o motor (conversa, orçamento de turnos);
- **1ª fronteira** — o primeiro `ResponseChunk` com texto publicado: é o motor + o fatiador;
- **1º áudio** — o primeiro pedaço sintetizado na fila **e** o primeiro tick dela, como no F1-09:
  é **piso de software**, porque a fila do dispositivo não está na conta.

A coluna "desde o fim da fala" soma o atraso de decisão de turno publicado no F1-07 (o limiar do
`silencio_fixo`, que é tempo de áudio, não de CPU) — **não** é remedido aqui.

Motores: `roteirizado` (atraso zero: o que sobra é **nosso** — fatiador, evento, TTS) e
`claude-cli[:modelo]` (o provisório, com rede e conta; D18 manda medir também um local e um de
API, que ainda não têm adaptador).
"""

from __future__ import annotations

import argparse
import csv
import queue
import threading
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from jarvis.agentd.fala_em_stream import falar_stream_para
from jarvis.agentd.tts import MotorDeTts, SintetizadorEmStreaming
from jarvis.audio_io.playback import FilaDePlayback, Pedaco
from jarvis.audio_io.sumidouros import SumidouroEmMemoria
from jarvis.corpus.rotulos import ler_rotulos
from jarvis.medicao import hardware, percentil
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import MotorDeConversa
from jarvis.s2.motor_claude_cli import MotorClaudeCli
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from tools.harness_tts import motor_de as motor_de_tts

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_SAIDA: Final = RAIZ / "docs" / "medicoes"
NOME: Final = "f2-01-primeira-fala"
CORPUS_PADRAO: Final = RAIZ / "corpus" / "turnos"
SESSAO: Final = "0193f0a0-0000-7000-8000-000000000001"
SLO5_P50_MS: Final = 600.0
SLO5_P95_MS: Final = 900.0
ATRASO_DO_DETECTOR_MS: Final = 500.0
"""F1-07 (`docs/medicoes/f1-07-turno.md`): o `silencio_fixo` decide com 500 ms de silêncio — no
corpus sintético, ponto marcado "não utilizável" pelo falso corte. É o que existe hoje entre o fim
da fala do dono e o turno aceito; o número do v1 sai do corpus real (F1-15/F1-16)."""
PERGUNTAS: Final = (
    "Que dia da semana vem depois de quinta?",
    "Me dá uma dica rápida para dormir melhor.",
    "Quanto é dezessete vezes três?",
    "Qual a capital da Austrália?",
    "Fala um sinônimo de rápido.",
    "O que é mais pesado, um quilo de ferro ou um de algodão?",
    "Me sugere um nome para um gato preto.",
    "Explica em uma frase o que é um eclipse.",
)
"""As mesmas perguntas curtas da medição de `docs/medicoes/s2-provisorio-primeira-fala.md`."""
CABECALHO_DO_VEREDITO: Final = "piso cabe no SLO-5?"


@dataclass(frozen=True, slots=True)
class Turno:
    motor: str
    tts: str
    item: str
    montagem_ms: float
    primeira_fronteira_ms: float
    primeiro_audio_ms: float
    fim: str
    pedacos: int


@dataclass(slots=True)
class Medicao:
    turnos: list[Turno] = field(default_factory=list)
    lacunas: list[tuple[str, str]] = field(default_factory=list)


def medir_turno(motor: MotorDeConversa, tts: MotorDeTts, pergunta: str, item: str) -> Turno | None:
    """Um turno: o cérebro gera numa linha, o TTS consome na outra, o relógio é um só."""
    cerebro = Cerebro(motor=motor)
    pedacos: queue.Queue[dict[str, Any] | None] = queue.Queue()
    resultado: dict[str, Any] = {}
    comeco = time.monotonic()

    def s2() -> None:
        resultado["r"] = cerebro.responder(pergunta, epoch=0, publicar=pedacos.put)
        pedacos.put(None)

    def do_stream() -> Iterator[dict[str, Any]]:
        while (pedaco := pedacos.get()) is not None:
            yield pedaco

    sumidouro = SumidouroEmMemoria()
    fila = FilaDePlayback(sumidouro=sumidouro, session_id=SESSAO)
    sintese = SintetizadorEmStreaming(motor=tts, session_id=SESSAO, epoch=0)
    primeiro_audio: list[float] = []

    def enfileirar(pedaco: Pedaco) -> bool:
        aceito = fila.enfileirar(pedaco)
        if aceito and not primeiro_audio:
            fila.tick()
            primeiro_audio.append((time.monotonic() - comeco) * 1000.0)
        return aceito

    fio = threading.Thread(target=s2, daemon=True)
    fio.start()
    fala = falar_stream_para(sintese, do_stream(), enfileirar)
    fio.join(timeout=60)
    resposta = resultado.get("r")
    if resposta is None or resposta.ms_ate_primeiro_pedaco is None or not primeiro_audio:
        return None
    return Turno(
        motor=motor.nome,
        tts=getattr(tts, "nome", type(tts).__name__),
        item=item,
        montagem_ms=resposta.ms_ate_contexto,
        primeira_fronteira_ms=resposta.ms_ate_primeiro_pedaco,
        primeiro_audio_ms=primeiro_audio[0],
        fim=str(resposta.fim),
        pedacos=len(fala.pedacos),
    )


def motor_de_conversa(nome: str, pasta_vazia: Path, resposta: str) -> MotorDeConversa:
    if nome == "roteirizado":
        return MotorRoteirizado(resposta=resposta)
    if nome.startswith("claude-cli"):
        _, _, modelo = nome.partition(":")
        motor = MotorClaudeCli(pasta_de_trabalho=pasta_vazia, modelo=modelo)
        motor.nome = f"claude-cli{':' + modelo if modelo else ''} (provisório)"
        return motor
    raise ValueError(f"motor desconhecido: {nome!r}")


def resumo(medicao: Medicao) -> dict[tuple[str, str], dict[str, float]]:
    grupos: dict[tuple[str, str], list[Turno]] = {}
    for turno in medicao.turnos:
        grupos.setdefault((turno.motor, turno.tts), []).append(turno)
    saida: dict[tuple[str, str], dict[str, float]] = {}
    for chave, grupo in grupos.items():
        audio = [t.primeiro_audio_ms for t in grupo]
        saida[chave] = {
            "n": float(len(grupo)),
            "montagem_p50": percentil([t.montagem_ms for t in grupo], 50),
            "fronteira_p50": percentil([t.primeira_fronteira_ms for t in grupo], 50),
            "fronteira_p95": percentil([t.primeira_fronteira_ms for t in grupo], 95),
            "audio_p50": percentil(audio, 50),
            "audio_p95": percentil(audio, 95),
            "audio_max": max(audio),
        }
    return saida


def escrever_csv(medicao: Medicao, caminho: Path) -> None:
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(
            [
                "motor",
                "tts",
                "item",
                "montagem_ms",
                "primeira_fronteira_ms",
                "primeiro_audio_ms",
                "desde_fim_da_fala_ms",
                "fim",
                "pedacos",
            ]
        )
        for t in medicao.turnos:
            escritor.writerow(
                [
                    t.motor,
                    t.tts,
                    t.item,
                    f"{t.montagem_ms:.3f}",
                    f"{t.primeira_fronteira_ms:.3f}",
                    f"{t.primeiro_audio_ms:.3f}",
                    f"{t.primeiro_audio_ms + ATRASO_DO_DETECTOR_MS:.3f}",
                    t.fim,
                    t.pedacos,
                ]
            )


def escrever_markdown(medicao: Medicao, caminho: Path, commit: str) -> None:
    maquina = hardware()
    linhas = [
        "# F2-01 — primeira fala com o cérebro em stream: SLO-5 por trecho",
        "",
        "**Gerado por** `tools/harness_primeira_fala.py` (não editar à mão). **Data:** "
        f"{time.strftime('%Y-%m-%d')}. **Commit:** `{commit}`.",
        "",
        "> **Piso de software, sem dispositivo.** O 1º áudio é o primeiro pedaço na fila de "
        "playback e o primeiro tick dela; a fila do driver não está na conta. O SLO-5 de verdade "
        "é medido na máquina do dono com o dispositivo (F1-16).",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {maquina['cpu']}, {maquina['nucleos']} fios, {maquina['memoria']} de RAM",
        f"- {maquina['plataforma']}, Python {maquina['python']}",
        "- caminho: `Cerebro.responder` (s2) numa linha de execução → `ResponseChunk` → "
        "`falar_stream_para` (TTS) → `FilaDePlayback.tick`, tudo em memória, sem barramento entre "
        "processos",
        '- tempos contados do **turno aceito**; "desde o fim da fala" soma os '
        f"{ATRASO_DO_DETECTOR_MS:.0f} ms de decisão de turno do `silencio_fixo` publicados no "
        "F1-07 (tempo de áudio, não remedido)",
        "- `roteirizado`: resposta do corpus de turnos, sem atraso de motor — o que sobra é o "
        "nosso lado; `claude-cli`: as 8 perguntas curtas da medição do S2 provisório, com rede",
        f"- alvo da SPEC §7 para o SLO-5: p50 ≤ {SLO5_P50_MS:.0f} ms, p95 ≤ {SLO5_P95_MS:.0f} ms",
        "",
        "## Resultado",
        "",
        "| motor | TTS | n | montagem p50 | 1ª fronteira p50 | 1ª fronteira p95 | 1º áudio p50 "
        f"| 1º áudio p95 | 1º áudio máx | desde o fim da fala p50 | {CABECALHO_DO_VEREDITO} |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|:--|",
    ]
    for (motor, tts), v in resumo(medicao).items():
        cabe = v["audio_p50"] <= SLO5_P50_MS and v["audio_p95"] <= SLO5_P95_MS
        linhas.append(
            f"| `{motor}` | `{tts}` | {v['n']:.0f} | {v['montagem_p50']:.2f} ms "
            f"| {v['fronteira_p50']:.1f} ms | {v['fronteira_p95']:.1f} ms "
            f"| {v['audio_p50']:.1f} ms | {v['audio_p95']:.1f} ms | {v['audio_max']:.1f} ms "
            f"| {v['audio_p50'] + ATRASO_DO_DETECTOR_MS:.1f} ms "
            f"| {'piso cabe' if cabe else '**piso excede**'} |"
        )
    linhas += ["", "## O que não foi medido", ""]
    linhas += [f"- **{o_que}** — {por_que}" for o_que, por_que in medicao.lacunas]
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def _commit() -> str:
    import subprocess

    saida = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 — git no PATH, argv explícito
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
    )
    return saida.stdout.strip() or "desconhecido"


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--corpus", type=Path, default=CORPUS_PADRAO)
    analisa.add_argument("--itens", type=int, default=40, help="turnos por motor roteirizado")
    analisa.add_argument(
        "--itens-de-rede", type=int, default=10, help="turnos por motor com rede (custa)"
    )
    analisa.add_argument("--motores", default="roteirizado,claude-cli:haiku")
    analisa.add_argument("--tts", default="parametrico,piper")
    analisa.add_argument("--saida", type=Path, default=PASTA_SAIDA)
    analisa.add_argument(
        "--pasta-vazia", type=Path, default=Path.home() / ".cache" / "jarvis" / "s2-vazia"
    )
    args = analisa.parse_args(argv)

    rotulos = [r for r in ler_rotulos(args.corpus / "rotulos.jsonl") if r.sintetico][: args.itens]
    if not rotulos:
        print(f"FALHOU: sem rótulos em {args.corpus}")
        return 2
    args.pasta_vazia.mkdir(parents=True, exist_ok=True)
    medicao = Medicao()
    for nome_tts in (t.strip() for t in args.tts.split(",") if t.strip()):
        tts = motor_de_tts(nome_tts)
        for nome in (m.strip() for m in args.motores.split(",") if m.strip()):
            com_rede = nome != "roteirizado"
            itens = range(args.itens_de_rede if com_rede else len(rotulos))
            for i in itens:
                pergunta = PERGUNTAS[i % len(PERGUNTAS)]
                resposta = rotulos[i % len(rotulos)].texto
                motor = motor_de_conversa(nome, args.pasta_vazia, resposta)
                turno = medir_turno(motor, tts, pergunta, f"{nome}-{i:03d}")
                if turno is None:
                    print(f"FALHOU ({nome}, item {i}): o turno não chegou ao primeiro áudio")
                    return 2
                medicao.turnos.append(turno)

    medicao.lacunas += [
        (
            "fila do dispositivo",
            "o primeiro áudio audível depende do driver; aqui é o primeiro tick sobre sumidouro "
            "de memória (F1-16, máquina do dono)",
        ),
        (
            "barramento entre processos",
            "o `ResponseChunk` vai de linha para linha de execução, não por IPC: o custo por "
            "evento medido na F0-04 (0,384 ms p95) fica de fora, uma vez por pedaço",
        ),
        (
            "motor local e motor de API",
            "D18 manda medir os dois; ainda não há adaptador — este harness já os aceita pela "
            "interface `MotorDeConversa`",
        ),
        (
            "decisão de turno no corpus real",
            "o atraso somado é o do `silencio_fixo` no corpus sintético (F1-07); o número do v1 "
            "sai do F1-15/F1-16",
        ),
        (
            "percentis altos do motor com rede",
            f"{args.itens_de_rede} turnos por configuração não sustentam p95 de verdade; servem "
            "para a ordem de grandeza",
        ),
    ]
    args.saida.mkdir(parents=True, exist_ok=True)
    escrever_csv(medicao, args.saida / f"{NOME}.csv")
    escrever_markdown(medicao, args.saida / f"{NOME}.md", _commit())
    print(f"publicado em {args.saida / NOME}.{{csv,md}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
