"""Memória do JARVIS — fatos, notas, embeddings opt-in.

Tier 0 (default): JSON em `data/memory/`.
Tier 1: SQLite.
Tier 2: embeddings locais (opt-in) → `store.MemoryStore` (numpy + MiniLM).
Tier 3: backend externo (futuro).

Implementação ativa (roadmap/14):
- `store.py`      — MemoryStore vetorial em RAM (numpy + MiniLM).
- `retrieval.py`  — score composto (recência+sim+importância+pinned) + MMR.
- `router.py`     — política de RECUPERAÇÃO por situação (read-time).
- `triage.py`     — DISCERNIMENTO de ESCRITA (o que/como memorizar, write-time).
- `compaction.py` — compactação/resumo de conversa p/ gastar menos contexto.
Tudo atrás de toggles em config (MEMORY_*), OFF por padrão.
"""
from __future__ import annotations


def _cfg(name: str, default=False):
    try:
        import config as _c
        return getattr(_c, name, default)
    except Exception:
        return default


def enabled() -> bool:
    return bool(_cfg("MEMORY_ENABLED", False))


def triage_enabled() -> bool:
    return bool(_cfg("MEMORY_TRIAGE_ENABLED", False))


def compaction_enabled() -> bool:
    return bool(_cfg("MEMORY_COMPACTION_ENABLED", False))


def get_store():
    """Acesso lazy ao MemoryStore (importa numpy/embeddings só quando chamado)."""
    from .store import get_store as _gs
    return _gs()


def get_triage():
    from .triage import get_triage as _gt
    return _gt()


def ingest_turn(user_text: str, assistant_text: str = "",
                origem: str = "texto", turn_id=None) -> None:
    """Grava um turno na memória. Com DISCERNIMENTO ligado (MEMORY_TRIAGE_ENABLED),
    decide o que vale a pena lembrar (e PROMOVE fatos/regras), descartando o
    efêmero para gastar menos contexto. Sem triagem, grava o turno cru (Fase 2).
    Best-effort — nunca quebra o turno."""
    try:
        store = get_store()
    except Exception:
        return
    if not triage_enabled():
        try:
            store.record_turn(user_text, assistant_text, origem=origem, turn_id=turn_id)
        except Exception:
            pass
        return
    # ── com discernimento ──
    try:
        d = get_triage().decide(user_text, assistant_text, origem=origem)
    except Exception:
        try:
            store.record_turn(user_text, assistant_text, origem=origem, turn_id=turn_id)
        except Exception:
            pass
        return
    cat, op = d.get("category"), d.get("op")
    # efêmero / NOOP → descarta (economiza contexto e memória)
    if cat == "efemero" or op == "NOOP":
        return
    seg = d.get("segment")
    text = d.get("redacted_text") or user_text
    imp = float(d.get("importance", 0.6))
    try:
        if op == "DELETE":
            store.forget(d.get("value") or d.get("subject") or user_text)
            return
        # grava o turno episódico (a conversa) quando há valor
        store.record_turn(user_text, assistant_text, origem=origem, turn_id=turn_id)
        if seg == "semantic":
            if d.get("subject") and d.get("value"):
                store.upsert_fact(d["subject"], d.get("predicate") or "é",
                                  d["value"], pinned=bool(d.get("pinned")))
            else:
                store.add("semantic", text, importance=imp, source="fact",
                          pinned=bool(d.get("pinned")))
        elif seg == "procedural":
            store.add("procedural", text, importance=imp, source="rule",
                      pinned=bool(d.get("pinned")))
        elif seg == "episodic":
            store.add("episodic", text, importance=imp, source=cat or "evento")
    except Exception:
        pass
