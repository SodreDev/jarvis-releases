"""Ferramentas de linha de comando do Linux (wpctl, wl-paste, xdg-open...).

- ``run_tool``: sem shell, com ``LC_ALL=C`` (saída parseável) e sempre com
  timeout. O processo é curto e aguardado aqui mesmo, então NÃO é registrado
  como filho.
- ``which``: ``shutil.which`` com cache por (nome, PATH); trocar o PATH
  invalida a entrada.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
from typing import Dict, Optional, Sequence, Tuple

DEFAULT_TIMEOUT = 3.0

_WHICH_CACHE: Dict[Tuple[str, str], Optional[str]] = {}
_WHICH_LOCK = threading.Lock()


def which(name: str) -> Optional[str]:
    """Caminho do executável ou None (com cache)."""
    key = (name, os.environ.get("PATH", ""))
    with _WHICH_LOCK:
        if key in _WHICH_CACHE:
            return _WHICH_CACHE[key]
    found = shutil.which(name)
    with _WHICH_LOCK:
        _WHICH_CACHE[key] = found
    return found


def clear_which_cache() -> None:
    """Esquece os caminhos cacheados (ferramenta instalada depois, testes)."""
    with _WHICH_LOCK:
        _WHICH_CACHE.clear()


def run_tool(
    argv: Sequence[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    input: Optional[str] = None,
) -> Optional[subprocess.CompletedProcess]:
    """Roda a ferramenta e devolve o CompletedProcess (stdout/stderr em texto).

    None quando a ferramenta não existe, não executa ou estoura o timeout.
    Código de saída diferente de zero NÃO levanta: quem chama olha returncode.
    """
    if not argv:
        return None
    exe = which(argv[0])
    if exe is None:
        return None
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    kwargs = {}
    if input is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = input
    try:
        return subprocess.run(
            [exe, *argv[1:]],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
            check=False,
            **kwargs,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
