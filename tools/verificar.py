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
    # A suíte de cancelamento sai daqui e roda na etapa própria: ela tem fuzz de 1 000
    # execuções, e rodar duas vezes dobraria o tempo do portão sem dobrar a garantia.
    ("testes", ["pytest", "-m", "not cancelamento"]),
    # Cartão F1-11, aceite (d): a suíte de cancelamento é portão próprio, para o aceite (b)
    # da F1 ser regressão e não evento único.
    ("cancelamento (20 pontos)", ["pytest", "-m", "cancelamento", "-q"]),
    ("adrs", ["python", "tools/adr.py", "conferir"]),
    ("corpus", ["python", "tools/corpus.py", "verificar"]),
    ("manifestos", ["python", "tools/manifesto.py", "validar"]),
    ("lint de catálogo", ["python", "tools/manifesto.py", "lint"]),
    ("stubs em dia", ["python", "tools/manifesto.py", "conferir"]),
    (
        "porta de licença",
        ["python", "tools/license_gate.py", "--verificar-tabela", "--verificar-atribuicao"],
    ),
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
