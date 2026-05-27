# comandos/macro_ctrl.py — J.A.R.V.I.S.
# Atalhos de voz personalizados (macros)
# -*- coding: utf-8 -*-

from __future__ import annotations
import json, os

_MACRO_FILE = "macros.json"


def _load() -> dict:
    if not os.path.exists(_MACRO_FILE):
        return {}
    try:
        with open(_MACRO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(macros: dict):
    with open(_MACRO_FILE, "w", encoding="utf-8") as f:
        json.dump(macros, f, ensure_ascii=False, indent=2)


def criar_macro(nome: str, apps: list[str]) -> str:
    macros = _load()
    key    = nome.lower().strip()
    macros[key] = [a.strip() for a in apps if a.strip()]
    _save(macros)
    return f"Atalho '{nome}' criado, senhor. Apps: {', '.join(macros[key])}."


def executar_macro(nome: str) -> list[str] | None:
    """Retorna lista de apps para abrir, ou None se não encontrado."""
    return _load().get(nome.lower().strip())


def listar_macros() -> str:
    macros = _load()
    if not macros:
        return "Nenhum atalho personalizado configurado, senhor."
    linhas = ["⚡ Atalhos personalizados:"]
    for nome, apps in macros.items():
        linhas.append(f"  '{nome}' → {', '.join(apps)}")
    return "\n".join(linhas)


def remover_macro(nome: str) -> str:
    macros = _load()
    key    = nome.lower().strip()
    if key not in macros:
        return f"Atalho '{nome}' não encontrado, senhor."
    del macros[key]
    _save(macros)
    return f"Atalho '{nome}' removido, senhor."


def detectar_macro(texto: str) -> str | None:
    """Verifica se o texto corresponde a algum macro definido. Retorna nome ou None."""
    macros = _load()
    tl     = texto.lower().strip().rstrip("?.!")
    for nome in macros:
        if tl == nome or tl == f"ativar {nome}" or tl == f"modo {nome}" or nome in tl:
            return nome
    return None
