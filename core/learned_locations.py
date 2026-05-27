# -*- coding: utf-8 -*-
"""
core/learned_locations.py
─────────────────────────
Cache persistente de locais (pastas, executáveis, jogos) que o JARVIS
aprendeu durante o uso. Cada vez que um caminho é resolvido com sucesso
(via voz/comando), gravamos aqui para que próximas consultas sejam
instantâneas.

Formato:
    {
        "cyberpunk 2077": {
            "path": "C:/Games/Cyberpunk 2077",
            "kind": "game",            # "game" | "folder" | "file" | "exe"
            "platform": "steam",       # opcional
            "count": 7,                # quantas vezes foi resolvido
            "last_seen": "2026-05-27T22:15:00",
            "aliases": ["cyberpunk", "cp77"]
        },
        ...
    }

Persistência: credentials/learned_locations.json
"""
from __future__ import annotations

import datetime as _dt
import json as _json
import re as _re
import threading as _th
import unicodedata as _ud
from pathlib import Path
from typing import Optional

try:
    from config import creds_path
except Exception:  # fallback se rodando fora do contexto da app
    def creds_path(*parts: str) -> str:
        base = Path(__file__).resolve().parent.parent / "credentials"
        base.mkdir(parents=True, exist_ok=True)
        return str(base.joinpath(*parts))


_LOCK = _th.RLock()
_CACHE: dict | None = None  # carregado lazy


def _store_path() -> Path:
    return Path(creds_path("learned_locations.json"))


def _normalize(key: str) -> str:
    """Normaliza chave: lowercase, sem acentos, espaços únicos."""
    if not key:
        return ""
    s = _ud.normalize("NFD", key.strip().lower())
    s = "".join(c for c in s if _ud.category(c) != "Mn")
    s = _re.sub(r"\s+", " ", s)
    return s


def _load() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    p = _store_path()
    if not p.is_file():
        _CACHE = {}
        return _CACHE
    try:
        _CACHE = _json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(_CACHE, dict):
            _CACHE = {}
    except Exception:
        _CACHE = {}
    return _CACHE


def _save() -> None:
    if _CACHE is None:
        return
    p = _store_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_json.dumps(_CACHE, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    except Exception:
        pass


# ─── API pública ────────────────────────────────────────────────────────────

def remember(name: str, path: str, *, kind: str = "folder",
             platform: str = "", aliases: list[str] | None = None) -> None:
    """Grava (ou atualiza) um local aprendido. Idempotente."""
    if not name or not path:
        return
    key = _normalize(name)
    if not key:
        return
    with _LOCK:
        data = _load()
        entry = data.get(key) or {}
        entry["path"] = str(path)
        entry["kind"] = kind or entry.get("kind") or "folder"
        if platform:
            entry["platform"] = platform
        entry["count"] = int(entry.get("count") or 0) + 1
        entry["last_seen"] = _dt.datetime.now().isoformat(timespec="seconds")
        # Mescla aliases
        existing_aliases = set(entry.get("aliases") or [])
        if aliases:
            for a in aliases:
                an = _normalize(a)
                if an and an != key:
                    existing_aliases.add(an)
        if existing_aliases:
            entry["aliases"] = sorted(existing_aliases)
        data[key] = entry
        _save()


def lookup(query: str) -> Optional[dict]:
    """Busca um local pelo nome ou alias. Retorna a entrada (dict) ou None."""
    if not query:
        return None
    q = _normalize(query)
    if not q:
        return None
    with _LOCK:
        data = _load()
        # Match direto
        entry = data.get(q)
        if entry:
            return {"key": q, **entry}
        # Match por alias
        for key, entry in data.items():
            if q in (entry.get("aliases") or []):
                return {"key": key, **entry}
        # Match parcial (substring)
        for key, entry in data.items():
            if q in key or key in q:
                return {"key": key, **entry}
            for a in (entry.get("aliases") or []):
                if q in a or a in q:
                    return {"key": key, **entry}
        return None


def all_entries(*, kind: str | None = None,
                platform: str | None = None) -> list[dict]:
    """Retorna lista de entradas, opcionalmente filtradas."""
    with _LOCK:
        data = _load()
        out = []
        for key, entry in data.items():
            if kind and entry.get("kind") != kind:
                continue
            if platform and entry.get("platform") != platform:
                continue
            out.append({"key": key, **entry})
        out.sort(key=lambda x: (-int(x.get("count") or 0),
                                 x.get("key", "")))
        return out


def forget(name: str) -> bool:
    """Remove uma entrada. Retorna True se removido."""
    key = _normalize(name)
    if not key:
        return False
    with _LOCK:
        data = _load()
        if key in data:
            del data[key]
            _save()
            return True
        return False
