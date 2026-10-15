"""Roda, na ordem, tudo que o CI roda — o mesmo comando em Linux e Windows (P11).

Uso: ``uv run --frozen python tools/verificar.py``

Cada etapa é um processo com ``argv`` explícito: nada de shell (SPEC §4, CONTRIBUTING 6).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

ETAPAS: tuple[tuple[str, list[str]], ...] = (
    ("formatação", ["ruff", "format", "--check", "."]),
    ("linter", ["ruff", "check", "."]),
    ("tipos", ["mypy"]),
    ("testes", ["pytest"]),
)


def rodar(nome: str, argv: list[str]) -> int:
    print(f"\n=== {nome}: {' '.join(argv)}", flush=True)
    concluido = subprocess.run(argv, cwd=RAIZ, check=False)
    return concluido.returncode


def main() -> int:
    falhas: list[str] = []
    for nome, argv in ETAPAS:
        if rodar(nome, argv) != 0:
            falhas.append(nome)
    print()
    if falhas:
        print(f"FALHOU: {', '.join(falhas)}")
        return 1
    print(f"OK: {', '.join(nome for nome, _ in ETAPAS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
