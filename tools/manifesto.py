"""CLI do ferramental de manifesto (SPEC §4; cartão F0-07).

    uv run --frozen python tools/manifesto.py validar     # recusa manifesto incompleto
    uv run --frozen python tools/manifesto.py lint        # regras de catálogo (§4, ADR-0010)
    uv run --frozen python tools/manifesto.py codegen     # (re)gera os stubs tipados
    uv run --frozen python tools/manifesto.py conferir    # falha se o stub estiver velho

`validar`, `lint` e `conferir` rodam no CI: manifesto sem `postcondition`, `risk_class`,
`tests` ou `access_level_min` não entra, e stub desatualizado também não.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jarvis.manifesto.codegen import gerar_stub
from jarvis.manifesto.lint import lintar_catalogo
from jarvis.manifesto.validador import (
    PASTA_CATALOGO,
    ManifestoInvalido,
    carregar_catalogo,
    carregar_manifesto,
)

RAIZ = Path(__file__).resolve().parent.parent
PASTA_STUBS = RAIZ / "src" / "jarvis" / "capacidades"


def caminho_do_stub(identificador: str) -> Path:
    return PASTA_STUBS / f"{identificador.replace('.', '_')}.py"


def validar(pasta: Path) -> int:
    arquivos = sorted(pasta.glob("*.yaml"))
    if not arquivos:
        print(f"nenhum manifesto em {pasta}")
        return 1
    falhas = 0
    for arquivo in arquivos:
        try:
            manifesto = carregar_manifesto(arquivo)
        except ManifestoInvalido as erro:
            print(f"RECUSADO {erro}")
            falhas += 1
        else:
            print(f"ok {manifesto['id']} ({arquivo.name})")
    print(f"\n{len(arquivos) - falhas}/{len(arquivos)} manifestos válidos")
    return 1 if falhas else 0


def lint(pasta: Path) -> int:
    achados = lintar_catalogo(pasta)
    for achado in achados:
        print(f"ACHADO {achado}")
    print(f"\nlint de catálogo: {len(achados)} achado(s)")
    return 1 if achados else 0


def codegen(pasta: Path, *, escrever: bool) -> int:
    try:
        catalogo = carregar_catalogo(pasta)
    except ManifestoInvalido as erro:
        print(f"RECUSADO {erro}")
        return 1
    PASTA_STUBS.mkdir(parents=True, exist_ok=True)
    inicial = PASTA_STUBS / "__init__.py"
    cabecalho = (
        '"""Stubs gerados dos manifestos (SPEC §4). NÃO EDITE À MÃO.\n\n'
        "Gere com `uv run --frozen python tools/manifesto.py codegen`.\n"
        '"""\n'
    )
    desatualizados: list[str] = []
    if escrever:
        inicial.write_text(cabecalho, encoding="utf-8")
    elif not inicial.exists() or inicial.read_text(encoding="utf-8") != cabecalho:
        desatualizados.append(inicial.name)

    for identificador, manifesto in catalogo.items():
        codigo = gerar_stub(manifesto)
        destino = caminho_do_stub(identificador)
        if escrever:
            destino.write_text(codigo, encoding="utf-8")
            print(f"gerado {destino.relative_to(RAIZ)}")
        elif not destino.exists() or destino.read_text(encoding="utf-8") != codigo:
            desatualizados.append(destino.name)

    existentes = {a.name for a in PASTA_STUBS.glob("*.py")} - {"__init__.py"}
    esperados = {caminho_do_stub(i).name for i in catalogo}
    sobrando = sorted(existentes - esperados)
    if escrever:
        for nome in sobrando:
            (PASTA_STUBS / nome).unlink()
            print(f"removido {nome} (manifesto não existe mais)")
        return 0

    desatualizados += sobrando
    if desatualizados:
        print(f"stubs desatualizados: {sorted(desatualizados)}")
        print("rode: uv run --frozen python tools/manifesto.py codegen")
        return 1
    print(f"{len(catalogo)} stub(s) em dia")
    return 0


def main(argv: list[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument(
        "acao", choices=["validar", "lint", "codegen", "conferir"], help="o que fazer"
    )
    analisa.add_argument("--catalogo", type=Path, default=PASTA_CATALOGO)
    args = analisa.parse_args(argv)

    if args.acao == "validar":
        return validar(args.catalogo)
    if args.acao == "lint":
        return lint(args.catalogo)
    if args.acao == "codegen":
        return codegen(args.catalogo, escrever=True)
    return codegen(args.catalogo, escrever=False)


if __name__ == "__main__":
    sys.exit(main())
