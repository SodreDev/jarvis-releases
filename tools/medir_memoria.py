"""Mede a consulta da memória como o app a faz, ponta a ponta (auditoria de 2026-10-30).

    uv run --frozen python -m tools.medir_memoria [--consultas 200] [--saida ARQUIVO.md]

Dados sintéticos (`tools/corpus_c2.py`, semente fixa) gravados pela API do livro num SQLite em
pasta temporária, e o índice que o app usa: LanceDB com o embedding local (multilingual-e5-small,
ONNX, do cache do Jarvis) — sem ele, o índice de termos em memória, como o app cai. Nenhum dado
do dono é lido; nada sai da máquina. Mede:

1. **frio:** a primeira consulta (abre o modelo de embedding: o app não aquece);
2. **quente:** `memoria_do_turno.consultar` (o que roda antes de **todo** turno, ADR-0026) e
   `LivroDeMemoria.buscar_historico` (a `memoria.buscar_historico`), p50/p95;
3. **com o indexador:** a mesma consulta enquanto outra linha grava turnos e processa a outbox —
   o livro usa uma trava só para buscar e indexar.

O alvo do pedido do dono: «instantânea» = caminho quente < 150–250 ms.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Final

RAIZ: Final = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ))

from jarvis.memoryd.embedding import ARQUIVO_DO_MODELO, PASTA_DO_MODELO  # noqa: E402
from jarvis.s2.memoria_do_turno import consultar  # noqa: E402
from jarvis.voz.interface import Onde  # noqa: E402
from tools.corpus_c2 import gerar, montar  # noqa: E402

ALVO_MS: Final = 150.0
TETO_MS: Final = 250.0


def _indice(pasta: Path) -> tuple[Any, str]:
    if not (PASTA_DO_MODELO / ARQUIVO_DO_MODELO).is_file():
        from jarvis.memoryd.indice import IndiceEmMemoria

        return IndiceEmMemoria(), "termos em memória (sem o modelo de embedding no cache)"
    from jarvis.memoryd.embedding import EmbedderE5
    from jarvis.memoryd.indice_vetorial import IndiceLance

    return IndiceLance(pasta=pasta, embedder=EmbedderE5()), "LanceDB + multilingual-e5-small"


def _quantis(amostras: Sequence[float]) -> dict[str, float]:
    ordenadas = sorted(amostras)
    return {
        "n": float(len(ordenadas)),
        "p50": statistics.median(ordenadas),
        "p95": ordenadas[max(0, int(0.95 * len(ordenadas)) - 1)],
        "max": ordenadas[-1],
    }


def _cronometrar(funcao: Callable[[], object]) -> float:
    comeco = time.perf_counter()
    funcao()
    return (time.perf_counter() - comeco) * 1000.0


def _modelo_frio() -> float:
    """O que a 1ª consulta de uma sessão paga: abrir o ONNX do embedding e a 1ª inferência (o
    app não aquece o modelo; no `montar` ele já tinha aberto para indexar)."""
    if not (PASTA_DO_MODELO / ARQUIVO_DO_MODELO).is_file():
        return 0.0
    from jarvis.memoryd.embedding import EmbedderE5

    novo = EmbedderE5()
    return _cronometrar(lambda: novo.embed(["onde eu deixei a chave do carro"], "query"))


def _modelo_aquecido() -> float:
    """O mesmo, com o aquecimento que o app agora faz ao abrir o livro: a 1ª consulta paga só a
    inferência."""
    if not (PASTA_DO_MODELO / ARQUIVO_DO_MODELO).is_file():
        return 0.0
    from jarvis.memoryd.embedding import EmbedderE5

    novo = EmbedderE5()
    novo.aquecer_em_segundo_plano().join(30.0)
    return _cronometrar(lambda: novo.embed(["onde eu deixei a chave do carro"], "query"))


def medir(consultas: int) -> dict[str, Any]:
    corpus = gerar()
    pasta = Path(tempfile.mkdtemp(prefix="jarvis-medir-memoria-"))
    indice, nome_do_indice = _indice(pasta / "indice")
    comeco = time.perf_counter()
    montado = montar(corpus, indice, caminho=str(pasta / "livro.sqlite"))
    montar_s = time.perf_counter() - comeco
    livro = montado.livro
    textos = [c.texto for c in corpus.consultas] or ["onde eu moro"]
    perguntas = [textos[i % len(textos)] for i in range(consultas)]

    frio = _cronometrar(lambda: livro.buscar(perguntas[0], k=12))
    abrir_o_modelo = _modelo_frio()
    aquecido = _modelo_aquecido()

    def turno(texto: str) -> None:
        consultar(livro, texto, onde=Onde.NUVEM, motor="claude-cli")

    quente = [_cronometrar(lambda t=t: turno(t)) for t in perguntas]  # type: ignore[misc]
    historico = [
        _cronometrar(lambda t=t: livro.buscar_historico(t, k=5))  # type: ignore[misc]
        for t in perguntas
    ]

    parar = threading.Event()
    gravados = [0]

    def indexador() -> None:
        while not parar.is_set():
            livro.gravar_turno(
                session_id="0193f0a0-0000-7000-8000-0000000000aa",
                papel="dono",
                texto=f"conversa à toa número {gravados[0]} sobre o tempo e o almoço",
                trust="user_voice",
            )
            livro.processar_outbox()
            gravados[0] += 1

    linha = threading.Thread(target=indexador, daemon=True)
    linha.start()
    concorrente = [_cronometrar(lambda t=t: turno(t)) for t in perguntas]  # type: ignore[misc]
    parar.set()
    linha.join(10.0)
    return {
        "indice": nome_do_indice,
        "unidades": len(montado.itens),
        "fatos": len(corpus.fatos),
        "turnos_da_conversa": len(corpus.conversa),
        "montar_s": montar_s,
        "frio_ms": frio,
        "modelo_frio_ms": abrir_o_modelo,
        "modelo_aquecido_ms": aquecido,
        "turno_quente": _quantis(quente),
        "historico_quente": _quantis(historico),
        "turno_com_indexador": _quantis(concorrente),
        "turnos_gravados_durante": gravados[0],
    }


def relatorio(r: dict[str, Any]) -> str:
    def linha(nome: str, q: dict[str, float]) -> str:
        veredito = "sim" if q["p95"] < ALVO_MS else ("no limite" if q["p95"] < TETO_MS else "não")
        return (
            f"| {nome} | {int(q['n'])} | {q['p50']:.1f} | {q['p95']:.1f} | {q['max']:.1f} | "
            f"{veredito} |"
        )

    return "\n".join(
        [
            f"Índice: {r['indice']}; {r['unidades']} itens indexados ({r['fatos']} fatos, "
            f"{r['turnos_da_conversa']} turnos de conversa à toa); montar levou "
            f"{r['montar_s']:.1f} s.",
            "",
            "| caminho | n | p50 (ms) | p95 (ms) | máx (ms) | instantâneo (p95 < 150 ms)? |",
            "|---|---:|---:|---:|---:|---|",
            f"| abrir o modelo + 1ª inferência (a 1ª consulta da sessão) | 1 | "
            f"{r['modelo_frio_ms']:.1f} | — | — | — |",
            f"| 1ª inferência com o modelo aquecido ao abrir o livro (agora) | 1 | "
            f"{r['modelo_aquecido_ms']:.1f} | — | — | — |",
            linha("memória do turno (`consultar`, todo turno)", r["turno_quente"]),
            linha("`memoria.buscar_historico`", r["historico_quente"]),
            linha("memória do turno com o indexador gravando", r["turno_com_indexador"]),
            "",
            f"Durante a medição concorrente o indexador gravou {r['turnos_gravados_durante']} "
            "turnos.",
        ]
    )


def principal(argv: Sequence[str] | None = None) -> int:
    opcoes = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    opcoes.add_argument("--consultas", type=int, default=200)
    opcoes.add_argument("--saida", type=Path, default=None)
    args = opcoes.parse_args(argv)
    resultado = medir(max(10, args.consultas))
    texto = relatorio(resultado)
    if args.saida is not None:
        args.saida.write_text(texto + "\n", encoding="utf-8")
    print(texto)
    print("RELATORIO " + json.dumps(resultado, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
