"""Intenções do JARVIS — detectores de comando baseados em regex.

Status: estrutura criada, migração incremental do `main.py`.

Sub-módulos:
- `patterns`  — regex compilados, agrupados por domínio.
- `registry`  — `IntentRegistry` para registrar detectores e roteá-los.
- `spotify`   — primeiro domínio migrado (proof of concept).
"""

from .registry import IntentRegistry, IntentMatch, get_registry

__all__ = ["IntentRegistry", "IntentMatch", "get_registry"]
