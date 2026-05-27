"""Padrões regex agrupados por domínio.

Cada domínio vive num próprio módulo (spotify.py, sistema.py, mensageria.py).
Este arquivo expõe apenas helpers comuns.
"""
from __future__ import annotations

import re


def compile_pattern(pattern: str, flags: int = re.IGNORECASE) -> re.Pattern[str]:
    return re.compile(pattern, flags)


def any_match(patterns: list[re.Pattern[str]], text: str) -> re.Match[str] | None:
    for p in patterns:
        m = p.search(text)
        if m:
            return m
    return None


__all__ = ["compile_pattern", "any_match"]
