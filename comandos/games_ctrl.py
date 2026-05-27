# -*- coding: utf-8 -*-
"""
comandos/games_ctrl.py
──────────────────────
Controle de jogos via launcher (Steam, Epic, EA, Battle.net, Ubisoft, Xbox).

Funções:
    abrir_jogo(nome, plataforma=None)   → tenta launch URI → exe → falha
    instalar_jogo(nome, plataforma)     → abre tela de install no launcher
    listar_jogos(plataforma=None)       → resumo textual / dict
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from core import game_library


# ─── helpers ────────────────────────────────────────────────────────────────

def _shell_open(target: str) -> bool:
    """os.startfile com try/except. True se chamada não levantou."""
    try:
        os.startfile(target)  # type: ignore[attr-defined]
        return True
    except Exception:
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", target],
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except Exception:
            return False


def _format_game(g: dict) -> str:
    return f"{g.get('name','?')} ({g.get('platform','?')})"


# ─── API ────────────────────────────────────────────────────────────────────

def listar_jogos(plataforma: str | None = None,
                 *, force_refresh: bool = False) -> str:
    if force_refresh:
        game_library.refresh()
    if plataforma:
        items = [g for g in game_library.get_all()
                 if (g.get("platform") or "").lower() == plataforma.lower()]
    else:
        items = game_library.get_all()
    if not items:
        return ("Nenhum jogo encontrado"
                + (f" em {plataforma}." if plataforma else "."))
    items.sort(key=lambda g: (g.get("platform"), (g.get("name") or "").lower()))
    by_plat: dict[str, list[str]] = {}
    for g in items:
        by_plat.setdefault(g.get("platform") or "?", []).append(
            g.get("name") or "?")
    lines = [f"Total: {len(items)} jogo(s)."]
    for plat, names in by_plat.items():
        lines.append(f"\n• {plat.upper()} ({len(names)}):")
        for n in names[:30]:
            lines.append(f"   – {n}")
        if len(names) > 30:
            lines.append(f"   … +{len(names) - 30}")
    return "\n".join(lines)


def abrir_jogo(nome: str, plataforma: str | None = None) -> str:
    if not (nome or "").strip():
        return "Diga o nome do jogo, sir."
    matches = game_library.find(nome, platform=plataforma, limit=5)
    if not matches:
        # tenta refresh + 2ª busca
        game_library.refresh()
        matches = game_library.find(nome, platform=plataforma, limit=5)
    if not matches:
        plats = f" na plataforma {plataforma}" if plataforma else ""
        return f"Não encontrei nenhum jogo parecido com '{nome}'{plats}."
    if len(matches) > 1 and matches[0]["name"].lower() != nome.lower():
        # ambiguidade — mostra top 3
        alt = ", ".join(_format_game(g) for g in matches[:3])
        chosen = matches[0]
        print(f"[games_ctrl] match ambíguo, escolhendo {chosen['name']}; alts: {alt}")
    g = matches[0]
    # 1) URI scheme
    uri = g.get("launch_uri") or ""
    if uri and _shell_open(uri):
        return f"Abrindo {g['name']} via {g['platform']}…"
    # 2) exe direto
    exe = g.get("exe_path") or ""
    if exe and Path(exe).is_file() and _shell_open(exe):
        return f"Lançando {g['name']} direto do executável…"
    # 3) pasta de install (último recurso)
    inst = g.get("install_path") or ""
    if inst and Path(inst).is_dir() and _shell_open(inst):
        return (f"Não consegui lançar {g['name']} diretamente; "
                f"abri a pasta de instalação.")
    return f"Encontrei {g['name']} mas não consegui abri-lo."


def instalar_jogo(nome: str, plataforma: str | None = None) -> str:
    if not (nome or "").strip():
        return "Diga o nome do jogo a instalar."
    matches = game_library.find(nome, platform=plataforma, limit=3)
    if matches:
        g = matches[0]
        uri = g.get("install_uri") or g.get("launch_uri")
        if uri and _shell_open(uri):
            return f"Abri a página de instalação de {g['name']} no {g['platform']}."
        return f"Jogo {g['name']} já está instalado pela {g['platform']}."
    # Sem match → abre store do launcher informado
    fallback_uri = {
        "steam":     "steam://store/",
        "epic":      "com.epicgames.launcher://store/",
        "ea":        "ealink://library",
        "battlenet": "battlenet://",
        "ubisoft":   "uplay://store/",
        "xbox":      "ms-windows-store://home",
    }.get((plataforma or "").lower(), "")
    if fallback_uri and _shell_open(fallback_uri):
        return f"Abri a loja do {plataforma} para você procurar '{nome}'."
    return f"Não encontrei '{nome}' instalado e não sei em qual loja procurar."
