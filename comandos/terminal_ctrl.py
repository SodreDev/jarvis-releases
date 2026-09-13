# comandos/terminal_ctrl.py — Execução de comandos de terminal com whitelist
# -*- coding: utf-8 -*-
"""
Executor seguro de comandos de terminal. Apenas comandos da whitelist são
permitidos. Saída truncada em 2000 caracteres.

Whitelist (prefixo do comando completo, case-insensitive):
    git status / git log / git diff / git branch / git remote
    dir / ls / pwd / cd (somente leitura — cd não persiste)
    pytest / python -m pytest / npm test / npm run test
    where / which / echo
    type (Windows cat) / cat
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

# Cada entrada é uma tupla de tokens iniciais que devem casar (case-insensitive).
_WHITELIST: list[tuple[str, ...]] = [
    ("git", "status"),
    ("git", "log"),
    ("git", "diff"),
    ("git", "branch"),
    ("git", "remote"),
    ("git", "show"),
    ("dir",),
    ("ls",),
    ("pwd",),
    ("where",),
    ("which",),
    ("echo",),
    ("type",),
    ("cat",),
    ("pytest",),
    ("python", "-m", "pytest"),
    ("npm", "test"),
    ("npm", "run", "test"),
    ("node", "--version"),
    ("python", "--version"),
]

_MAX_OUTPUT = 2000
_TIMEOUT_S = 20.0


def _eh_permitido(tokens: list[str]) -> bool:
    if not tokens:
        return False
    low = [t.lower() for t in tokens]
    for prefixo in _WHITELIST:
        if len(low) >= len(prefixo) and tuple(low[: len(prefixo)]) == prefixo:
            return True
    return False


def executar(comando: str, cwd: str | None = None) -> str:
    """Executa um comando da whitelist. Retorna stdout/stderr truncado."""
    if not comando or not comando.strip():
        return "ERRO: comando vazio."
    cmd = comando.strip()
    # Bloqueia operadores de shell — tudo deve ser um comando único.
    for proibido in ("&&", "||", ";", "|", ">", "<", "`", "$("):
        if proibido in cmd:
            return f"ERRO: operador '{proibido}' não permitido."
    try:
        tokens = shlex.split(cmd, posix=False)
    except ValueError as e:
        return f"ERRO: parsing — {e}"
    if not _eh_permitido(tokens):
        return (
            f"ERRO: comando '{tokens[0]}' não está na whitelist. "
            "Permitidos: git status/log/diff/branch, dir, ls, pytest, "
            "npm test, where, echo, type, cat, --version."
        )
    workdir = cwd or str(Path.cwd())
    try:
        proc = subprocess.run(
            tokens,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            shell=False,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return f"ERRO: comando excedeu {_TIMEOUT_S:.0f}s."
    except FileNotFoundError:
        return f"ERRO: executável '{tokens[0]}' não encontrado."
    except Exception as e:
        return f"ERRO: {e}"
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    out = out.strip()
    if len(out) > _MAX_OUTPUT:
        out = out[:_MAX_OUTPUT] + f"\n... (truncado, {len(out)} chars)"
    if not out:
        return f"OK (exit={proc.returncode}, sem saída)."
    return f"[exit={proc.returncode}]\n{out}"
