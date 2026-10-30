"""Mede o custo das receitas sob demanda (ADR-0047, emenda de 2026-10-30): quanto cada pedido-tipo
acrescenta ao prompt do turno, em caracteres e tokens, e quanto tempo a escolha leva.

    uv run --frozen python -m tools.medir_receitas [--saida docs/medicoes/receitas-sob-demanda.md]

Sem rede, sem modelo, sem o desktop do dono: o roteador de método é o de sempre (regras locais),
o catálogo é o dos manifestos (`catalogo/`), e os tokens são contados com o tokenizador do
embedding da memória (multilingual-e5-small) quando ele está no cache do Jarvis — a mesma régua do
`tools/medir_prompt.py`; sem ele, a estimativa é caracteres ÷ 3,7. O prompt-base (persona, regras e
catálogo) não muda com as receitas: é o de `docs/medicoes/prompt-do-turno.md`.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

RAIZ: Final = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

from jarvis.politica.metodo import ContextoDoMetodo, escolher_metodo  # noqa: E402
from jarvis.s2.receitas import familias_do_pedido, receitas_do_turno  # noqa: E402

TOKENIZADOR: Final = (
    Path.home()
    / ".cache"
    / "jarvis"
    / "modelos"
    / "intfloat--multilingual-e5-small"
    / "tokenizer.json"
)
PEDIDOS: Final = (
    "abre o canal do Thiago Nigro no YouTube e toca o último vídeo",
    "clica no botão de inscrever",
    "abre o console da página e vê o erro",
    "pesquisa quem ganhou o jogo do Flamengo ontem",
    "abre o Discord",
    "aperta enter",
    "lembra que eu prefiro café sem açúcar",
    "aumenta o volume",
    "calcula 15% de 2380 com um script",
    "usa o preset rápido",
    "aprende que se escreve Kubernetes",
    "delega isso para o Claude Code",
    "bom dia, tudo bem?",
    "me conta uma piada",
)
REPETICOES: Final = 200


def contador_de_tokens() -> tuple[Callable[[str], int], str]:
    try:
        from tokenizers import Tokenizer  # type: ignore[import-untyped, unused-ignore]

        tokenizador = Tokenizer.from_file(str(TOKENIZADOR))
    except Exception:  # sem o tokenizador no cache: estimativa
        return (lambda texto: round(len(texto) / 3.7)), "estimativa (caracteres ÷ 3,7)"
    return (lambda texto: len(tokenizador.encode(texto).ids)), "multilingual-e5-small"


def medir(pedidos: Sequence[str]) -> tuple[list[dict[str, object]], str]:
    contar, regua = contador_de_tokens()
    catalogo = [p.stem for p in (RAIZ / "catalogo").glob("*.yaml")]
    contexto = ContextoDoMetodo(navegador=True, entrada=True, apps=frozenset({"discord"}))
    linhas: list[dict[str, object]] = []
    for pedido in pedidos:
        tempos: list[float] = []
        bloco = ""
        for _ in range(REPETICOES):
            comeco = time.perf_counter()
            escolha = escolher_metodo(pedido, contexto)
            bloco = receitas_do_turno(pedido, escolha, catalogo)
            tempos.append((time.perf_counter() - comeco) * 1e6)
        escolha = escolher_metodo(pedido, contexto)
        linhas.append(
            {
                "pedido": pedido,
                "metodo": str(escolha.metodo),
                "familias": ", ".join(familias_do_pedido(pedido, escolha)) or "—",
                "caracteres": len(bloco),
                "tokens": contar(bloco) if bloco else 0,
                "us_p50": statistics.median(tempos),
                "us_p95": sorted(tempos)[int(0.95 * len(tempos)) - 1],
            }
        )
    return linhas, regua


def relatorio(linhas: Sequence[dict[str, object]], regua: str) -> str:
    com = [linha for linha in linhas if int(str(linha["caracteres"]))]
    media = statistics.mean(int(str(linha["tokens"])) for linha in com) if com else 0.0
    maior = max(float(str(linha["us_p50"])) for linha in linhas) if linhas else 0.0
    partes = [
        "# Receitas sob demanda: o custo por pedido-tipo (2026-10-30)",
        "",
        "Medido por `tools/medir_receitas.py` (sem rede, sem modelo). Tokens: "
        f"{regua}. Tempo: escolher o método e montar o bloco, {REPETICOES} repetições.",
        "",
        "**Antes:** o prompt de sistema de todo turno era só persona + regras + catálogo "
        "(`docs/medicoes/prompt-do-turno.md`: 15 971 caracteres, 4 705 tokens e5 em 30/10). "
        "**Depois:** o mesmo prompt-base em todo turno — as receitas não entram nele — e, só no "
        "turno de um assunto com ferramenta, o bloco abaixo.",
        "",
        "| pedido | método | famílias | caracteres | tokens | escolha p50 (µs) | p95 (µs) |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for linha in linhas:
        partes.append(
            f"| {linha['pedido']} | {linha['metodo']} | {linha['familias']} | "
            f"{linha['caracteres']} | {linha['tokens']} | {float(str(linha['us_p50'])):.0f} | "
            f"{float(str(linha['us_p95'])):.0f} |"
        )
    partes += [
        "",
        f"Média nos turnos com receita: {media:.0f} tokens a mais; conversa: 0. Escolher o método "
        f"e montar o bloco leva no máximo {maior:.0f} µs (p50) — regras locais; o classificador "
        "de decisão só entra no pedido com verbo de ação que as regras não reconheceram, e nunca "
        "no turno de conversa.",
        "",
        "**Latência do modelo:** não medida — nenhuma chamada a modelo de verdade nesta medição. "
        "O que muda para o modelo é só o prefixo de entrada do turno com ferramenta (a tabela).",
        "",
    ]
    return "\n".join(partes)


def principal(argv: Sequence[str] | None = None) -> int:
    opcoes = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    opcoes.add_argument("--saida", type=Path, default=None)
    args = opcoes.parse_args(argv)
    linhas, regua = medir(PEDIDOS)
    texto = relatorio(linhas, regua)
    if args.saida is not None:
        args.saida.write_text(texto, encoding="utf-8")
    print(texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
