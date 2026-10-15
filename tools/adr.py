"""Confere a procedência das ADRs (cartão F0-10).

    uv run --frozen python tools/adr.py conferir

O que o cartão F0-10 cobra, em forma executável:

* (a) **cada ADR que traz número traz também** hardware, `n`, data e commit — senão o número
  não é reproduzível e não serve de decisão;
* (b) **nenhuma afirmação sem fonte ou sem marca [SUPOSIÇÃO]** — esta parte é verificada no
  que dá para verificar por máquina: toda ADR tem cabeçalho com data, estado e quem decide, e
  nenhuma deixa uma `[SUPOSIÇÃO]` solta sem dizer o que a confirma ou derruba.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_ADR: Final = RAIZ / "docs" / "adr"
TEMPLATE: Final = "0000-template.md"

CABECALHO_DATA = re.compile(r"\*\*Data:\*\*\s*(\d{4}-\d{2}-\d{2})")
CABECALHO_ESTADO = re.compile(r"\*\*Estado:\*\*\s*(\S+)")
CABECALHO_DECIDE = re.compile(r"\*\*Decide:\*\*\s*(.+)")
COMMIT = re.compile(r"`[0-9a-f]{7,40}`")
DECLARA_MEDICAO = re.compile(r"\*\*Mede:\*\*|\*\*Commits? d")
TABELA_DE_MEDICAO = re.compile(r"(?s)\|\s*p50\b.*\|\s*p95\b")
"""Uma ADR é "de medição" quando se declara assim no cabeçalho **ou** publica tabela com
p50 e p95. ADR antiga que apenas cita o orçamento de um SLO não cai nesta regra: ela não
está publicando número nosso."""
SUPOSICAO = re.compile(r"\[SUPOSIÇÃO")
ESTADOS_VALIDOS: Final = frozenset({"proposta", "aceita", "emendada", "revogada"})
PONTUACAO_DO_ESTADO: Final = ".,;:"
"""O cabeçalho das ADRs do arquiteto às vezes continua a frase depois do estado
(`**Estado:** aceita; emendada pela 0008`), então a pontuação é aparada antes de comparar."""


@dataclass(frozen=True, slots=True)
class Problema:
    arquivo: str
    o_que: str

    def __str__(self) -> str:
        return f"{self.arquivo}: {self.o_que}"


def conferir_adr(caminho: Path) -> list[Problema]:
    texto = caminho.read_text(encoding="utf-8")
    problemas: list[Problema] = []
    nome = caminho.name

    if CABECALHO_DATA.search(texto) is None:
        problemas.append(Problema(nome, "sem **Data:** no cabeçalho"))
    estado = CABECALHO_ESTADO.search(texto)
    if estado is None:
        problemas.append(Problema(nome, "sem **Estado:** no cabeçalho"))
    elif estado.group(1).strip().casefold().rstrip(PONTUACAO_DO_ESTADO) not in ESTADOS_VALIDOS:
        problemas.append(Problema(nome, f"estado desconhecido: {estado.group(1)!r}"))
    if CABECALHO_DECIDE.search(texto) is None:
        problemas.append(Problema(nome, "sem **Decide:** no cabeçalho"))

    de_medicao = (
        DECLARA_MEDICAO.search(texto) is not None or TABELA_DE_MEDICAO.search(texto) is not None
    )
    if de_medicao:
        if COMMIT.search(texto) is None:
            problemas.append(
                Problema(nome, "traz número de medição e não cita o commit da medição (F0-10 a)")
            )
        if not re.search(r"(?i)\bhardware\b|\bRyzen\b|\bCPU\b", texto):
            problemas.append(Problema(nome, "traz número e não descreve o hardware (F0-10 a)"))
        if not re.search(
            r"(?i)`?n`?\s*=\s*\d|\b\d[\d\s.]*\s*(frames|episódios|consultas|modelos)\b", texto
        ):
            problemas.append(Problema(nome, "traz número e não publica o `n` (F0-10 a)"))

    # Por parágrafo, não por linha: o markdown do projeto quebra frase no meio.
    for paragrafo in re.split(r"\n\s*\n", texto):
        if SUPOSICAO.search(paragrafo) and not re.search(
            r"(?i)confirma|derruba|harness|cartão|medi|teste|F0-\d\d", paragrafo
        ):
            problemas.append(
                Problema(
                    nome,
                    f"[SUPOSIÇÃO] sem dizer o que a confirma: {paragrafo.strip()[:80]}",
                )
            )
    return problemas


def conferir(pasta: Path = PASTA_ADR) -> list[Problema]:
    arquivos = [a for a in sorted(pasta.glob("*.md")) if a.name != TEMPLATE]
    if not arquivos:
        return [Problema(str(pasta), "nenhuma ADR encontrada")]
    problemas: list[Problema] = []
    for arquivo in arquivos:
        problemas += conferir_adr(arquivo)
    return problemas


def main(argv: list[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("acao", choices=["conferir", "listar"])
    analisa.add_argument("--pasta", type=Path, default=PASTA_ADR)
    args = analisa.parse_args(argv)

    if args.acao == "listar":
        for arquivo in sorted(args.pasta.glob("*.md")):
            if arquivo.name == TEMPLATE:
                continue
            texto = arquivo.read_text(encoding="utf-8")
            estado = CABECALHO_ESTADO.search(texto)
            titulo = texto.splitlines()[0].lstrip("# ")
            print(f"{arquivo.stem:48.48} {estado.group(1) if estado else '?':12.12} {titulo[:60]}")
        return 0

    problemas = conferir(args.pasta)
    for problema in problemas:
        print(f"PROBLEMA {problema}")
    if problemas:
        print(f"\n{len(problemas)} problema(s) de procedência nas ADRs")
        return 1
    print("ADRs com data, estado, decisor e, onde há número, hardware/n/commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
