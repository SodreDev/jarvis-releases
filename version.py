# -*- coding: utf-8 -*-
"""
version.py — Detecção automática da versão do JARVIS.

Lê o arquivo VERSION da raiz do projeto. Funciona tanto no modo .py
quanto dentro do .exe PyInstaller (--onedir), com detecção automática
do caminho — nunca depende de um diretório fixo.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _base_dir() -> Path:
    """Diretório base do projeto, com auto-detecção robusta.

    Ordem de detecção:
      1. Live-source via launcher.py (dist/JARVIS/../../main.py existe).
      2. Diretório do executável (onedir bundle).
      3. Diretório deste arquivo (modo .py).
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        # Padrão dist/JARVIS/JARVIS.exe → live-source dois níveis acima
        live = (exe_dir / ".." / "..").resolve()
        if (live / "main.py").is_file() and (live / "VERSION").is_file():
            return live
        return exe_dir
    return Path(__file__).resolve().parent


def get_version() -> str:
    """Retorna a versão atual lendo o arquivo VERSION.

    Fallback: '0.0.0-dev' se o arquivo não existir.
    Nunca lança exceção — versão é crítica para o updater não travar.
    """
    try:
        vfile = _base_dir() / "VERSION"
        if vfile.is_file():
            v = vfile.read_text(encoding="utf-8").strip()
            return v or "0.0.0-dev"
    except Exception:
        pass
    return "0.0.0-dev"


def version_tuple(v: str | None = None) -> tuple[int, ...]:
    """Converte 'X.Y.Z' em (X, Y, Z) para comparação numérica."""
    v = v or get_version()
    # Remove sufixos tipo "-dev", "-rc1", "+abc"
    base = v.split("-")[0].split("+")[0]
    parts: list[int] = []
    for p in base.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


__version__ = get_version()
__all__ = ["get_version", "version_tuple", "__version__"]


if __name__ == "__main__":
    print(get_version())
