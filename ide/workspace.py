# -*- coding: utf-8 -*-
"""
ide.workspace — Gerencia projetos isolados do JARVIS.

Cada projeto vive em data/jarvis_workspace/<slug>/. Operações de
leitura/escrita usam security.sanitizer.safe_path para impedir traversal.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import time
from typing import List, Optional

from security.sanitizer import safe_path, UnsafeInput


def _base() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def workspace_root() -> str:
    d = os.path.join(_base(), "data", "jarvis_workspace")
    os.makedirs(d, exist_ok=True)
    return d


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", (name or "").strip().lower()).strip("_")
    return s[:60] or f"proj_{int(time.time())}"


def project_dir(name: str, *, create: bool = False) -> str:
    slug = _slug(name)
    p = os.path.join(workspace_root(), slug)
    if create:
        os.makedirs(p, exist_ok=True)
    return p


def list_projects() -> List[dict]:
    root = workspace_root()
    out = []
    for name in sorted(os.listdir(root)):
        full = os.path.join(root, name)
        if os.path.isdir(full):
            out.append({
                "slug": name,
                "path": full,
                "mtime": os.path.getmtime(full),
                "files": _count_files(full),
            })
    return out


def _count_files(d: str) -> int:
    n = 0
    for root, _, files in os.walk(d):
        n += len(files)
        if n > 5000:
            return n
    return n


def create_project(name: str, *, description: str = "") -> dict:
    p = project_dir(name, create=True)
    readme = os.path.join(p, "README.md")
    if not os.path.exists(readme):
        with open(readme, "w", encoding="utf-8") as fh:
            fh.write(f"# {name}\n\n{description}\n\nCriado por J.A.R.V.I.S em {time.strftime('%Y-%m-%d')}.\n")
    return {"slug": os.path.basename(p), "path": p}


def delete_project(name: str) -> bool:
    p = project_dir(name)
    if os.path.isdir(p) and os.path.commonpath([p, workspace_root()]) == workspace_root() and p != workspace_root():
        shutil.rmtree(p, ignore_errors=True)
        return True
    return False


def list_tree(project: str) -> List[dict]:
    root = project_dir(project)
    if not os.path.isdir(root):
        return []
    out = []
    for cur, dirs, files in os.walk(root):
        rel = os.path.relpath(cur, root)
        for d in sorted(dirs):
            out.append({"type": "dir", "path": os.path.join(rel, d).replace("\\", "/").lstrip("./")})
        for f in sorted(files):
            full = os.path.join(cur, f)
            out.append({
                "type": "file",
                "path": os.path.join(rel, f).replace("\\", "/").lstrip("./"),
                "size": os.path.getsize(full),
            })
    return out


def read_file(project: str, rel_path: str) -> str:
    root = project_dir(project)
    full = safe_path(rel_path, base=root, must_exist=True)
    with open(full, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def write_file(project: str, rel_path: str, content: str) -> str:
    root = project_dir(project, create=True)
    full = safe_path(rel_path, base=root, allow_outside=False)
    os.makedirs(os.path.dirname(full) or root, exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    return full


def delete_file(project: str, rel_path: str) -> bool:
    root = project_dir(project)
    full = safe_path(rel_path, base=root, must_exist=True)
    if os.path.isdir(full):
        shutil.rmtree(full, ignore_errors=True)
        return True
    os.remove(full)
    return True


def mkdir(project: str, rel_path: str) -> str:
    root = project_dir(project, create=True)
    full = safe_path(rel_path, base=root, allow_outside=False)
    os.makedirs(full, exist_ok=True)
    return full


def move_file(project: str, src: str, dst: str) -> str:
    """Move/renomeia src → dst dentro do mesmo projeto."""
    root = project_dir(project)
    src_full = safe_path(src, base=root, must_exist=True)
    dst_full = safe_path(dst, base=root, allow_outside=False)
    os.makedirs(os.path.dirname(dst_full) or root, exist_ok=True)
    shutil.move(src_full, dst_full)
    return os.path.relpath(dst_full, root).replace("\\", "/")


def open_in_explorer(project: str, rel_path: str = "") -> None:
    """Abre o caminho no Explorer do Windows."""
    import subprocess
    root = project_dir(project)
    if rel_path:
        try:
            full = safe_path(rel_path, base=root)
        except Exception:
            full = root
    else:
        full = root
    if os.path.isfile(full):
        subprocess.Popen(["explorer", "/select,", full])
    else:
        subprocess.Popen(["explorer", full])


__all__ = [
    "workspace_root",
    "project_dir",
    "list_projects",
    "create_project",
    "delete_project",
    "list_tree",
    "read_file",
    "write_file",
    "delete_file",
    "mkdir",
    "move_file",
    "open_in_explorer",
]
