"""Harness de acerto em pt-BR (ADR-0064): roda os cenários e, com `--gate`, reprova a regressão.

Uso:
    uv run python tools/harness_acerto.py            # a tabela por categoria e o que errou
    uv run python tools/harness_acerto.py --gate     # sai com 1 se piorou contra a linha de base
    uv run python tools/harness_acerto.py --gravar-base   # a linha de base passa a ser a de agora

Só o código do Jarvis responde aqui, sem rede e sem chave: atalho, roteador de método, sim/não,
teto e nota. Os cenários de motor só rodam quando um motor é passado por código
(`jarvis.acerto.rodar(..., motor=...)`) — este script nunca chama modelo de verdade.
"""

from __future__ import annotations

import argparse
import json
import sys

from jarvis.acerto import LINHA_DE_BASE, carregar, gate, ler_base, rodar, tabela


def main(argv: list[str] | None = None) -> int:
    partes = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    partes.add_argument("--gate", action="store_true", help="reprova se piorou contra a base")
    partes.add_argument("--gravar-base", action="store_true", help="grava a linha de base")
    opcoes = partes.parse_args(argv)

    placar = rodar(carregar())
    for linha in tabela(placar):
        print(linha)
    for erro in placar.erros:
        print(f"  {erro.pontos}/2 {erro.cenario.id}: «{erro.cenario.fala}» → {erro.obtido}")
    if opcoes.gravar_base:
        texto = json.dumps(placar.para_json(), ensure_ascii=False, indent=2) + "\n"
        LINHA_DE_BASE.write_text(texto, "utf-8")
        print(f"linha de base gravada: {placar.total:.1%}")
        return 0
    if opcoes.gate:
        problemas = gate(placar, ler_base())
        for problema in problemas:
            print(f"PIOROU: {problema}")
        if problemas:
            return 1
        print("gate de acerto: nada piorou contra a linha de base")
    return 0


if __name__ == "__main__":
    sys.exit(main())
