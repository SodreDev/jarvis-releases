"""Piso do `claude -p` provisório (ADR-0018): o que cada flag tira do spawn até o 1º token.

    uv run --frozen python -m tools.harness_claude_cli            # publica em docs/medicoes
    uv run --frozen python -m tools.harness_claude_cli --rodadas 4

Pedido do dono (2026-10-16): a resposta parece lenta. O caminho medido é o do produto —
`MotorClaudeCli.gerar` em stream, numa pasta vazia, com o prompt de sistema do produto e o
modelo haiku — e cada variante muda **só** o que está na coluna "o que muda". As variantes
rodam intercaladas (A, B, C, A, B, C…) para a rede e a carga da máquina caírem igual nas três.

Trechos, do pedido ao motor (antes do `Popen`):
- **1º token** — o primeiro delta de texto do stream;
- **1ª fronteira** — o primeiro pedaço que o `FatiadorDeFala` solta (é o que vai ao TTS);
- **fim** — o `Fim` do motor.

Com rede e com a conta do dono: é número desta máquina, desta hora, desta rede.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from jarvis.fatiador import FatiadorDeFala
from jarvis.medicao import hardware, percentil
from jarvis.s2.motor import Contexto, Fim, Mensagem, Modo, Texto
from jarvis.s2.motor_claude_cli import MotorClaudeCli

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_SAIDA: Final = RAIZ / "docs" / "medicoes"
NOME: Final = "f2-02-piso-do-claude"
PERGUNTAS: Final = (
    "Que dia da semana vem depois de quinta?",
    "Me dá uma dica rápida para dormir melhor.",
    "Quanto é sete vezes oito?",
    "Diga bom dia em espanhol.",
)


@dataclass(frozen=True, slots=True)
class Variante:
    nome: str
    o_que_muda: str
    modo_seguro: bool
    sem_trafego: bool


def variantes() -> tuple[Variante, ...]:
    return (
        Variante("antes", "o argv de antes desta medição", False, False),
        Variante(
            "safe-mode", "+ --safe-mode (sem CLAUDE.md, skills, plugins, hooks, MCP)", True, False
        ),
        Variante(
            "safe-mode+sem-trafego",
            "+ --safe-mode e CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 (o padrão de agora)",
            True,
            True,
        ),
    )


@dataclass(slots=True)
class Amostra:
    variante: str
    pergunta: str
    primeiro_token_ms: float
    primeira_fronteira_ms: float
    fim_ms: float
    ok: bool


def medir_uma(variante: Variante, pasta: Path, pergunta: str) -> Amostra:
    motor = MotorClaudeCli(
        pasta_de_trabalho=pasta,
        modelo="haiku",
        modo_seguro=variante.modo_seguro,
        sem_trafego_extra=variante.sem_trafego,
    )
    contexto = Contexto(sistema=motor.sistema, mensagens=(Mensagem("dono", pergunta),))
    fatiador = FatiadorDeFala()
    inicio = time.monotonic()
    token = fronteira = 0.0
    ok = False
    for delta in motor.gerar(contexto, Modo.RAPIDO, lambda: False):
        agora = (time.monotonic() - inicio) * 1000.0
        if isinstance(delta, Texto):
            token = token or agora
            if not fronteira and list(fatiador.alimentar(delta.texto)):
                fronteira = agora
        elif isinstance(delta, Fim):
            ok = delta.motivo.value == "concluido"
            fim = agora
            break
    else:
        fim = (time.monotonic() - inicio) * 1000.0
    return Amostra(variante.nome, pergunta, token, fronteira or fim, fim, ok)


def _commit() -> str:
    resultado = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 — git no PATH, argv explícito
        capture_output=True,
        text=True,
        check=False,
        cwd=RAIZ,
    )
    return resultado.stdout.strip() or "?"


def medir(rodadas: int) -> list[Amostra]:
    amostras: list[Amostra] = []
    with tempfile.TemporaryDirectory(prefix="claude-vazio-") as tmp:
        pasta = Path(tmp)
        for rodada in range(rodadas):
            for pergunta in PERGUNTAS:
                for variante in variantes():
                    amostras.append(medir_uma(variante, pasta, pergunta))
                    print(f"rodada {rodada + 1}: {amostras[-1]}", flush=True)
    return amostras


def publicar(amostras: Sequence[Amostra], pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    with (pasta / f"{NOME}.csv").open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(
            [
                "variante",
                "execucao",
                "primeiro_token_p50_ms",
                "primeiro_token_p95_ms",
                "primeira_fronteira_p50_ms",
                "primeira_fronteira_p95_ms",
                "fim_p50_ms",
                "n",
                "falhas",
            ]
        )
        for variante in variantes():
            das = [a for a in amostras if a.variante == variante.nome and a.ok]
            escritor.writerow(
                [
                    variante.nome,
                    1,
                    f"{percentil([a.primeiro_token_ms for a in das], 50):.1f}",
                    f"{percentil([a.primeiro_token_ms for a in das], 95):.1f}",
                    f"{percentil([a.primeira_fronteira_ms for a in das], 50):.1f}",
                    f"{percentil([a.primeira_fronteira_ms for a in das], 95):.1f}",
                    f"{percentil([a.fim_ms for a in das], 50):.1f}",
                    len(das),
                    sum(1 for a in amostras if a.variante == variante.nome and not a.ok),
                ]
            )
    hw = hardware()
    linhas = [
        "# F2-02 — piso do `claude -p` provisório: o que cada flag tira do spawn",
        "",
        f"**Gerado por** `tools/harness_claude_cli.py` (não editar à mão). **Data:** "
        f"{time.strftime('%Y-%m-%d')}. **Commit:** `{_commit()}`.",
        "",
        "> **Com rede e com a conta do dono**: número desta máquina, desta rede, desta hora. As "
        "variantes rodaram intercaladas, então a rede pesa igual nas três.",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {hw['cpu']}, {hw['nucleos']} fios, {hw['memoria']} de RAM; "
        f"{hw['plataforma']}, Python {hw['python']}",
        "- `MotorClaudeCli.gerar` (o do produto), stream-json, modelo `haiku`, esforço `low`, "
        "pasta vazia, prompt de sistema do produto; tempo contado de antes do `Popen`",
        f"- {len(PERGUNTAS)} perguntas curtas × rodadas, intercaladas por variante",
        "",
        "## Resultado",
        "",
        "| variante | o que muda | n | 1º token p50 | 1º token p95 | 1ª fronteira p50 | "
        "1ª fronteira p95 | fim p50 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for variante in variantes():
        das = [a for a in amostras if a.variante == variante.nome and a.ok]
        linhas.append(
            f"| `{variante.nome}` | {variante.o_que_muda} | {len(das)} | "
            f"{percentil([a.primeiro_token_ms for a in das], 50):.0f} ms | "
            f"{percentil([a.primeiro_token_ms for a in das], 95):.0f} ms | "
            f"{percentil([a.primeira_fronteira_ms for a in das], 50):.0f} ms | "
            f"{percentil([a.primeira_fronteira_ms for a in das], 95):.0f} ms | "
            f"{percentil([a.fim_ms for a in das], 50):.0f} ms |"
        )
    linhas += [
        "",
        "## O que já estava no `argv` antes (e por isso não é variante)",
        "",
        '`--tools ""`, `--strict-mcp-config` (nenhum servidor MCP), `--no-session-persistence`, '
        "`--disable-slash-commands`, `--system-prompt` do produto (curto, no lugar do padrão), "
        "`--effort low`. `--bare` ficou fora: ele só autentica por `ANTHROPIC_API_KEY` e não lê "
        "o login OAuth do dono.",
        "",
    ]
    (pasta / f"{NOME}.md").write_text("\n".join(linhas), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--saida", type=Path, default=PASTA_SAIDA)
    parser.add_argument("--rodadas", type=int, default=3)
    args = parser.parse_args(argv)
    publicar(medir(args.rodadas), args.saida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
