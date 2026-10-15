"""O que toda medição publicada tem de declarar: máquina, `n` e percentis.

Regra do projeto (F1-tarefas, "nenhum número inventado"): medição vem com hardware, `n`, três
execuções, mediana e p95, e vai para arquivo em `docs/medicoes/`. A descrição da máquina é uma
função só, usada por todos os harness — número publicado em formato diferente não se compara.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path


def percentil(valores: list[float], p: float) -> float:
    """Percentil por posição (sem interpolação): `n` pequeno não finge precisão que não tem."""
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    return ordenados[min(round(p / 100 * (len(ordenados) - 1)), len(ordenados) - 1)]


def hardware() -> dict[str, str]:
    """CPU, fios, RAM, plataforma e Python — o cabeçalho de qualquer tabela de latência."""
    cpu = platform.processor()
    try:
        for linha in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if linha.startswith("model name"):
                cpu = linha.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    memoria = "?"
    try:
        for linha in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if linha.startswith("MemTotal"):
                memoria = f"{int(linha.split()[1]) / 1024 / 1024:.0f} GiB"
                break
    except OSError:
        pass
    return {
        "cpu": cpu or "?",
        "nucleos": str(os.cpu_count() or "?"),
        "memoria": memoria,
        "plataforma": platform.platform(),
        "python": platform.python_version(),
    }
