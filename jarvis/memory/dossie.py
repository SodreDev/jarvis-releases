# jarvis/memory/dossie.py — J.A.R.V.I.S.
# DOSSIÊ PROVISÓRIO: arquivo de rascunho onde o agente ACUMULA o conteúdo que acha
# (pesquisa web, aprendizados) SEM os caps de contexto, para depois gerar um
# documento RICO a partir de TODO o material — e ZERAR no fim. Pedido do dono:
# "junta o conteúdo num arquivo provisório, usa pra fazer o doc rico, depois zera".
#
# Um dossiê ATIVO por vez (agente single-user). Arquivo: <MEMORY_DIR>/dossie_<slug>.md
# Best-effort: falhas nunca quebram o turno.
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import threading
from pathlib import Path

_lock = threading.Lock()
_active: dict = {"assunto": None}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _dir() -> Path:
    try:
        import config as _c
        base = getattr(_c, "MEMORY_DIR", "data/memory")
    except Exception:
        base = "data/memory"
    bd = Path(base)
    d = bd if bd.is_absolute() else (_project_root() / bd)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(s: str) -> str:
    s = (s or "dossie").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:60] or "dossie"


def _path(assunto: str) -> Path:
    return _dir() / f"dossie_{_slug(assunto)}.md"


def iniciar(assunto: str) -> dict:
    """Cria/zera o dossiê do assunto e o marca como ATIVO."""
    assunto = (assunto or "").strip()
    if not assunto:
        return {"ok": False, "erro": "assunto vazio"}
    with _lock:
        try:
            _path(assunto).write_text(f"# Dossiê: {assunto}\n\n", encoding="utf-8")
            _active["assunto"] = assunto
            return {"ok": True, "assunto": assunto}
        except Exception as e:
            return {"ok": False, "erro": str(e)}


def anexar(fonte: str, texto: str, assunto: str | None = None) -> dict:
    """Anexa um bloco '## fonte\\n texto' ao dossiê ativo (ou ao assunto dado).
    Guarda o texto COMPLETO (sem cap — é a graça do dossiê)."""
    assunto = (assunto or _active.get("assunto") or "").strip()
    if not assunto:
        return {"ok": False, "erro": "nenhum dossiê ativo (chame iniciar antes)"}
    texto = (texto or "").strip()
    if not texto:
        return {"ok": False, "erro": "texto vazio"}
    with _lock:
        try:
            with open(_path(assunto), "a", encoding="utf-8") as f:
                f.write(f"\n## {(fonte or 'fonte').strip()}\n\n{texto}\n")
            return {"ok": True, "assunto": assunto, "chars": len(texto)}
        except Exception as e:
            return {"ok": False, "erro": str(e)}


def ler(assunto: str | None = None) -> str:
    """Conteúdo completo do dossiê (ativo ou pelo assunto). '' se não existir."""
    assunto = (assunto or _active.get("assunto") or "").strip()
    if not assunto:
        return ""
    p = _path(assunto)
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def limpar(assunto: str | None = None) -> dict:
    """Apaga o dossiê (zera o provisório)."""
    assunto = (assunto or _active.get("assunto") or "").strip()
    if not assunto:
        return {"ok": True}
    with _lock:
        try:
            p = _path(assunto)
            if p.exists():
                p.unlink()
        except Exception:
            pass
        if _active.get("assunto") == assunto:
            _active["assunto"] = None
        return {"ok": True, "assunto": assunto}


def ativo() -> str | None:
    """Assunto do dossiê ativo (ou None)."""
    return _active.get("assunto")
