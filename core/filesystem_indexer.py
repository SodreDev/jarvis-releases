# -*- coding: utf-8 -*-
"""
core/filesystem_indexer.py
──────────────────────────
Descoberta híbrida de pastas e arquivos no PC do usuário.

Estratégia em camadas (ordem de prioridade):

  1. `learned_locations` — cache aprendido (instantâneo, alimentado pelo uso)
  2. Quick scan — pastas típicas de jogos/apps (Steam libs, ProgramFiles,
     raízes de SSDs não-sistema, pasta Games/Jogos), profundidade limitada
  3. Walk on-demand — `os.walk` limitado em escopo, só se nada acima retornar

NÃO faz background scan completo (custoso) — somente quando solicitado.
"""
from __future__ import annotations

import os as _os
import re as _re
import unicodedata as _ud
from pathlib import Path
from typing import Iterable

try:
    from core import learned_locations as _ll
except Exception:  # pragma: no cover
    _ll = None

try:
    import psutil as _psutil
except Exception:
    _psutil = None


_MAX_DEPTH_QUICK = 3
_MAX_RESULTS = 30


def _norm(s: str) -> str:
    s = _ud.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if _ud.category(c) != "Mn")
    return _re.sub(r"\s+", " ", s).strip()


# ─── Drives ─────────────────────────────────────────────────────────────────

def list_drives() -> list[dict]:
    """Lista todas as letras de drive presentes no sistema (Windows).

    Retorna: [{letter, mountpoint, fstype, total_gb, free_gb, removable}]
    """
    out: list[dict] = []
    if _psutil is not None:
        try:
            for p in _psutil.disk_partitions(all=False):
                try:
                    u = _psutil.disk_usage(p.mountpoint)
                    out.append({
                        "letter":     p.device.rstrip("\\"),
                        "mountpoint": p.mountpoint,
                        "fstype":     p.fstype or "",
                        "total_gb":   round(u.total / (1024 ** 3), 1),
                        "free_gb":    round(u.free  / (1024 ** 3), 1),
                        "removable":  "removable" in (p.opts or ""),
                    })
                except Exception:
                    pass
            return out
        except Exception:
            pass
    # Fallback puro Windows
    if _os.name == "nt":
        import string as _s
        try:
            import ctypes
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for i, letter in enumerate(_s.ascii_uppercase):
                if bitmask & (1 << i):
                    out.append({
                        "letter":     f"{letter}:",
                        "mountpoint": f"{letter}:\\",
                        "fstype":     "",
                        "total_gb":   0.0,
                        "free_gb":    0.0,
                        "removable":  False,
                    })
        except Exception:
            pass
    return out


def system_drive() -> str:
    """Letra do drive do Windows (ex: 'C:')."""
    return (_os.environ.get("SystemDrive") or "C:").upper()


# ─── Roots típicos para descoberta rápida ───────────────────────────────────

def candidate_roots(*, include_user_dirs: bool = True) -> list[Path]:
    """Pastas onde tipicamente vivem jogos/projetos/apps."""
    roots: list[Path] = []

    # Drives não-sistema (raiz e pasta Games/Jogos)
    sysd = system_drive()
    for d in list_drives():
        letter = (d.get("letter") or "").upper()
        mp = d.get("mountpoint") or ""
        if not mp or letter == sysd:
            continue
        p = Path(mp)
        if p.is_dir():
            roots.append(p)
            for sub in ("Games", "Jogos", "SteamLibrary", "Epic Games",
                        "Riot Games", "Battle.net"):
                cand = p / sub
                if cand.is_dir():
                    roots.append(cand)

    # Pastas conhecidas no drive do sistema
    sys_root = Path(sysd + "\\")
    for env_var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        v = _os.environ.get(env_var)
        if v and Path(v).is_dir():
            roots.append(Path(v))
    for sub in ("Games", "Jogos"):
        cand = sys_root / sub
        if cand.is_dir():
            roots.append(cand)

    # Pastas do usuário
    if include_user_dirs:
        home = Path(_os.path.expanduser("~"))
        for sub in ("Desktop", "Documents", "Downloads", "Music",
                    "Pictures", "Videos"):
            cand = home / sub
            if cand.is_dir():
                roots.append(cand)

    # Dedupe preservando ordem
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        rs = str(r.resolve()).lower()
        if rs not in seen:
            seen.add(rs)
            out.append(r)
    return out


# ─── Quick scan ─────────────────────────────────────────────────────────────

def quick_scan(query: str, *, max_depth: int = _MAX_DEPTH_QUICK,
                max_results: int = _MAX_RESULTS,
                roots: Iterable[Path] | None = None) -> list[Path]:
    """Procura `query` (substring case-insensitive) nas pastas candidatas.
    Profundidade limitada. Retorna lista de Paths que matcham.
    """
    if not query:
        return []
    q = _norm(query)
    if not q:
        return []
    results: list[Path] = []
    seen: set[str] = set()

    base_roots = list(roots) if roots is not None else candidate_roots()

    for root in base_roots:
        if len(results) >= max_results:
            break
        if not root.is_dir():
            continue
        try:
            root_str = str(root)
            base_depth = root_str.count(_os.sep)
            for dirpath, dirnames, filenames in _os.walk(root_str):
                depth = dirpath.count(_os.sep) - base_depth
                if depth > max_depth:
                    dirnames.clear()
                    continue
                # Tira pastas inúteis
                dirnames[:] = [d for d in dirnames
                               if not d.startswith(".") and
                               d.lower() not in {"node_modules", "__pycache__",
                                                  "$recycle.bin", "system volume information"}]
                # Match em diretórios
                for d in list(dirnames):
                    if q in _norm(d):
                        p = Path(dirpath) / d
                        key = str(p).lower()
                        if key not in seen:
                            seen.add(key)
                            results.append(p)
                            if len(results) >= max_results:
                                break
                if len(results) >= max_results:
                    break
        except (PermissionError, OSError):
            continue
    return results


# ─── Find principal (combina camadas) ───────────────────────────────────────

def find_path(query: str, *, kind: str | None = None) -> dict | None:
    """Localiza um caminho.

    Retorna: {path, source, kind, score} ou None.
    `source` ∈ {"learned", "quick_scan"}.
    """
    if not query:
        return None

    # 1) Cache aprendido
    if _ll is not None:
        try:
            hit = _ll.lookup(query)
            if hit and Path(hit["path"]).exists():
                return {
                    "path": hit["path"],
                    "source": "learned",
                    "kind": hit.get("kind") or "folder",
                    "platform": hit.get("platform") or "",
                    "score": 100,
                }
        except Exception:
            pass

    # 2) Quick scan
    matches = quick_scan(query)
    if matches:
        # Prefere match cujo nome final seja igual à query normalizada
        q = _norm(query)
        matches.sort(key=lambda p: (0 if _norm(p.name) == q else 1,
                                     len(str(p))))
        best = matches[0]
        result = {
            "path": str(best),
            "source": "quick_scan",
            "kind": "folder" if best.is_dir() else "file",
            "platform": "",
            "score": 60 if _norm(best.name) == _norm(query) else 30,
        }
        # Aprende para futuro
        if _ll is not None:
            try:
                _ll.remember(query, str(best), kind=result["kind"])
            except Exception:
                pass
        return result

    return None
