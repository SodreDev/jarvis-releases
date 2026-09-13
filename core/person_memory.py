"""Memória por pessoa — threads de conversa + facts persistentes.

Estrutura (Fase 5):
  data/people_memory/<person_id>/
      facts.json                                     # fatos compartilhados (por person_id)
      threads/<platform>__<profile>.jsonl            # uma thread por canal

Cada **fato** é um objeto:
  {"id": uuid, "text": "...", "source": "manual|chat|extracted",
   "platform": "...", "profile": "...", "ts": iso}

Cada **mensagem da thread** é um objeto JSONL:
  {"id": uuid, "role": "incoming|outgoing|system",
   "platform": "...", "profile": "...",
   "sender": "...", "content": "...",
   "ts": iso, "msg_id": "<original platform id>"}

API:
  add_fact(person_id, text, **meta)
  list_facts(person_id) -> list
  remove_fact(person_id, fact_id)
  append_thread(person_id, platform, profile, role, sender, content, **meta)
  read_thread(person_id, platform, profile, limit=50) -> list
  list_threads(person_id) -> list[(platform, profile, count, last_ts)]
  summarize_context(person_id, platform=None, profile=None, max_chars=4000) -> str
      → usado pelo LLM como contexto antes de responder
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _base() -> Path:
    try:
        from jarvis.config.paths import project_root
        b = project_root() / "data" / "people_memory"
    except Exception:
        b = Path("data") / "people_memory"
    b.mkdir(parents=True, exist_ok=True)
    return b


def _person_dir(person_id: str) -> Path:
    d = _base() / person_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "threads").mkdir(parents=True, exist_ok=True)
    return d


def _facts_path(person_id: str) -> Path:
    return _person_dir(person_id) / "facts.json"


def _thread_path(person_id: str, platform: str, profile: str) -> Path:
    return _person_dir(person_id) / "threads" / f"{platform}__{profile}.jsonl"


# ---------- Facts ----------

def list_facts(person_id: str) -> list[dict[str, Any]]:
    p = _facts_path(person_id)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8") or "[]") or []
    except Exception:
        return []


def add_fact(person_id: str, text: str, *, source: str = "manual",
             platform: Optional[str] = None, profile: Optional[str] = None,
             extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    with _LOCK:
        facts = list_facts(person_id)
        item = {
            "id": uuid.uuid4().hex[:12],
            "text": text,
            "source": source,
            "platform": platform,
            "profile": profile,
            "ts": _now_iso(),
            **(extra or {}),
        }
        facts.append(item)
        _facts_path(person_id).write_text(
            json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return item


def remove_fact(person_id: str, fact_id: str) -> bool:
    with _LOCK:
        facts = list_facts(person_id)
        new = [f for f in facts if f.get("id") != fact_id]
        if len(new) == len(facts):
            return False
        _facts_path(person_id).write_text(
            json.dumps(new, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True


# ---------- Threads ----------

def append_thread(person_id: str, platform: str, profile: str,
                  role: str, sender: str, content: str,
                  *, msg_id: Optional[str] = None,
                  extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    with _LOCK:
        path = _thread_path(person_id, platform, profile)
        item = {
            "id": uuid.uuid4().hex[:12],
            "role": role,                     # incoming | outgoing | system
            "platform": platform,
            "profile": profile,
            "sender": sender,
            "content": content,
            "ts": _now_iso(),
            "msg_id": msg_id,
        }
        if extra:
            item.update(extra)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item


def read_thread(person_id: str, platform: str, profile: str,
                limit: int = 50) -> list[dict[str, Any]]:
    path = _thread_path(person_id, platform, profile)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for ln in lines[-int(limit):]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def list_threads(person_id: str) -> list[dict[str, Any]]:
    d = _person_dir(person_id) / "threads"
    out: list[dict[str, Any]] = []
    if not d.exists():
        return out
    for f in d.glob("*.jsonl"):
        try:
            stem = f.stem
            if "__" not in stem:
                continue
            platform, profile = stem.split("__", 1)
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
            count = len(lines)
            last_ts = None
            if lines:
                try:
                    last_ts = json.loads(lines[-1]).get("ts")
                except Exception:
                    last_ts = None
            out.append({
                "platform": platform, "profile": profile,
                "count": count, "last_ts": last_ts,
            })
        except Exception:
            continue
    return out


# ---------- Contexto pro LLM ----------

def summarize_context(person_id: str, *, platform: Optional[str] = None,
                      profile: Optional[str] = None, max_chars: int = 4000,
                      last_n_msgs: int = 20) -> str:
    """Monta um bloco de contexto: facts + últimas N msgs da thread atual.

    Usado antes de chamar o LLM para responder/raciocinar sobre esta pessoa.
    """
    parts: list[str] = []
    facts = list_facts(person_id)
    if facts:
        parts.append("FATOS SOBRE A PESSOA:")
        for f in facts[-30:]:
            parts.append(f"  - {f.get('text','')}")
        parts.append("")
    if platform and profile:
        msgs = read_thread(person_id, platform, profile, limit=last_n_msgs)
        if msgs:
            parts.append(f"HISTÓRICO ({platform}/{profile}, últimas {len(msgs)}):")
            for m in msgs:
                role = m.get("role", "?")
                who = "ELE" if role == "incoming" else ("EU" if role == "outgoing" else role.upper())
                parts.append(f"  [{who}] {m.get('content','')}")
    text = "\n".join(parts)
    if len(text) > max_chars:
        text = text[-max_chars:]
    return text


# ---------- Hook ao InboxWatcher ----------

def hook_incoming_event(ev: dict[str, Any]) -> None:
    """Subscriber pro event_bus `messaging.incoming`: salva na thread se
    `person_id` estiver presente no evento."""
    pid = ev.get("person_id")
    if not pid:
        return
    try:
        append_thread(
            pid,
            ev.get("platform", ""), ev.get("profile", ""),
            role="incoming",
            sender=ev.get("sender", ""),
            content=ev.get("preview", ""),
            msg_id=ev.get("chat_id") or None,
            extra={"unread_count": ev.get("unread_count")},
        )
    except Exception:
        pass


__all__ = [
    "list_facts", "add_fact", "remove_fact",
    "append_thread", "read_thread", "list_threads",
    "summarize_context", "hook_incoming_event",
]
