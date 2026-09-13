# -*- coding: utf-8 -*-
"""
core/game_library.py
────────────────────
Cache agregado de jogos de TODAS as plataformas suportadas, com TTL.

Uso:
    from core import game_library
    games = game_library.get_all()           # respeita TTL
    games = game_library.get_all(force=True) # refresh agora
    hit = game_library.find("cyberpunk")     # match fuzzy
"""
from __future__ import annotations

import datetime as _dt
import json as _json
import re as _re
import threading as _th
import unicodedata as _ud
from pathlib import Path

try:
    from config import creds_path
except Exception:
    def creds_path(*parts: str) -> str:
        base = Path(__file__).resolve().parent.parent / "credentials"
        base.mkdir(parents=True, exist_ok=True)
        return str(base.joinpath(*parts))

from core import game_platform_detector as _gpd


_LOCK = _th.RLock()
_CACHE_TTL_HOURS = 24


def _store_path() -> Path:
    return Path(creds_path("game_library.json"))


def _load_cache() -> dict | None:
    p = _store_path()
    if not p.is_file():
        return None
    try:
        return _json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(data: dict) -> None:
    p = _store_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_json.dumps(data, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    except Exception:
        pass


def _is_fresh(cache: dict) -> bool:
    ts = cache.get("scanned_at")
    if not ts:
        return False
    try:
        dt = _dt.datetime.fromisoformat(ts)
        delta = _dt.datetime.now() - dt
        return delta.total_seconds() < _CACHE_TTL_HOURS * 3600
    except Exception:
        return False


def _norm(s: str) -> str:
    s = _ud.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if _ud.category(c) != "Mn")
    # remove edição/tags
    s = _re.sub(r"\b(edition|deluxe|premium|standard|goty|complete|ultimate|definitive)\b",
                "", s)
    s = _re.sub(r"[^\w\s]+", " ", s)
    s = _re.sub(r"\s+", " ", s)
    return s.strip()


# ─── API pública ────────────────────────────────────────────────────────────

def refresh(platforms: list[str] | None = None) -> dict:
    """Re-escaneia todas as plataformas (ou subset) e atualiza o cache."""
    with _LOCK:
        games = _gpd.discover_all(platforms)
        cache = {
            "scanned_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "games": [g.to_dict() for g in games],
        }
        _save_cache(cache)
        return cache


def get_all(*, force: bool = False) -> list[dict]:
    """Devolve a lista agregada de jogos. Re-escaneia se TTL expirou ou
    se force=True."""
    with _LOCK:
        cache = _load_cache()
        if cache is None or not _is_fresh(cache) or force:
            cache = refresh()
        return list(cache.get("games") or [])


def by_platform() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for g in get_all():
        out.setdefault(g.get("platform") or "?", []).append(g)
    return out


def find(query: str, *, platform: str | None = None,
          limit: int = 5) -> list[dict]:
    """Match fuzzy do query contra a lista. Retorna até `limit` candidatos
    ordenados por score (maior primeiro)."""
    if not query:
        return []
    q = _norm(query)
    if not q:
        return []
    q_tokens = q.split()
    candidates: list[tuple[int, dict]] = []
    for g in get_all():
        if platform and g.get("platform") != platform:
            continue
        nm = _norm(g.get("name") or "")
        if not nm:
            continue
        # Score: match exato (100), começa com (80), todas as palavras (60),
        # qualquer palavra (30)
        if nm == q:
            score = 100
        elif nm.startswith(q):
            score = 80
        elif q in nm:
            score = 65
        elif all(t in nm for t in q_tokens):
            score = 50
        elif any(t in nm for t in q_tokens if len(t) > 2):
            score = 25
        else:
            continue
        candidates.append((score, g))
    candidates.sort(key=lambda x: -x[0])
    return [g for _, g in candidates[:limit]]
