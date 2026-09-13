"""PersonRegistry — registro de pessoas com identidade cross-platform.

Cada Person tem um `id` estável (slug) e uma lista de identidades por
plataforma (`platform`, `handle`, `profile_seen_on`). Permite:

  • resolver (platform, handle) -> person_id
  • listar todas as pessoas
  • criar/editar/deletar pessoa
  • juntar duas pessoas em uma (merge)

Persistido em `data/people.json` (atômico).

Schema do arquivo:
{
  "version": 1,
  "people": {
     "<person_id>": {
        "id": "<person_id>",
        "name": "João Silva",
        "tags": ["familia", "trabalho"],
        "notes": "irmão",
        "identities": [
            {"platform": "whatsapp", "handle": "5511999999999",
             "profile": "user", "label": "celular"},
            {"platform": "telegram", "handle": "@joaosilva", "profile": "user"}
        ],
        "created_at": "2026-05-26T03:00:00Z",
        "updated_at": "2026-05-26T03:00:00Z"
     }, ...
  }
}
"""
from __future__ import annotations

import json
import re
import threading
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _people_file() -> Path:
    try:
        from jarvis.config.paths import project_root
        base = project_root() / "data"
    except Exception:
        base = Path("data")
    base.mkdir(parents=True, exist_ok=True)
    return base / "people.json"


def _slug(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s or uuid.uuid4().hex[:8]


def _norm_handle(platform: str, handle: str) -> str:
    h = (handle or "").strip()
    if not h:
        return ""
    if platform == "whatsapp":
        # mantém só dígitos (+ sem prefixo)
        return re.sub(r"\D+", "", h)
    if platform == "telegram":
        return h.lstrip("@").lower()
    if platform == "instagram":
        return h.lstrip("@").lower()
    if platform == "discord":
        return h.lower()
    if platform == "gmail":
        return h.lower()
    return h.lower()


def _empty() -> dict[str, Any]:
    return {"version": 1, "people": {}}


def _load_raw() -> dict[str, Any]:
    p = _people_file()
    if not p.exists():
        return _empty()
    try:
        return json.loads(p.read_text(encoding="utf-8") or "{}") or _empty()
    except Exception:
        return _empty()


def _save_raw(data: dict[str, Any]) -> None:
    p = _people_file()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


# ---------- API pública ----------

def list_people() -> list[dict[str, Any]]:
    with _LOCK:
        data = _load_raw()
        return list(data.get("people", {}).values())


def get_person(person_id: str) -> Optional[dict[str, Any]]:
    with _LOCK:
        data = _load_raw()
        return data.get("people", {}).get(person_id)


def find_by_identity(platform: str, handle: str) -> Optional[dict[str, Any]]:
    nh = _norm_handle(platform, handle)
    if not nh:
        return None
    with _LOCK:
        for pid, p in _load_raw().get("people", {}).items():
            for ident in p.get("identities", []):
                if ident.get("platform") == platform and _norm_handle(platform, ident.get("handle","")) == nh:
                    return p
    return None


def resolve_person_id(platform: str, handle: str) -> Optional[str]:
    p = find_by_identity(platform, handle)
    return p["id"] if p else None


def upsert_person(
    name: str,
    *,
    person_id: Optional[str] = None,
    tags: Optional[Iterable[str]] = None,
    notes: Optional[str] = None,
    identities: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    with _LOCK:
        data = _load_raw()
        people = data.setdefault("people", {})
        pid = person_id or _slug(name)
        # garante unicidade do id
        base = pid; n = 2
        while pid in people and not person_id:
            pid = f"{base}_{n}"; n += 1
        existing = people.get(pid, {})
        merged = {
            "id": pid,
            "name": name or existing.get("name") or pid,
            "tags": sorted(set(list(existing.get("tags", [])) + list(tags or []))),
            "notes": notes if notes is not None else existing.get("notes", ""),
            "identities": existing.get("identities", []),
            "created_at": existing.get("created_at") or _now_iso(),
            "updated_at": _now_iso(),
        }
        if identities:
            for ident in identities:
                add_identity_inplace(merged, ident.get("platform",""), ident.get("handle",""),
                                     profile=ident.get("profile"), label=ident.get("label"))
        people[pid] = merged
        _save_raw(data)
        return merged


def add_identity_inplace(person: dict, platform: str, handle: str, *, profile=None, label=None) -> bool:
    if not platform or not handle:
        return False
    nh = _norm_handle(platform, handle)
    for ident in person.get("identities", []):
        if ident.get("platform") == platform and _norm_handle(platform, ident.get("handle","")) == nh:
            # já existe — só atualiza meta
            if profile: ident["profile"] = profile
            if label:   ident["label"] = label
            return False
    person.setdefault("identities", []).append({
        "platform": platform, "handle": handle,
        "profile": profile, "label": label,
    })
    person["updated_at"] = _now_iso()
    return True


def add_identity(person_id: str, platform: str, handle: str, *,
                 profile: Optional[str] = None, label: Optional[str] = None) -> bool:
    with _LOCK:
        data = _load_raw()
        people = data.get("people", {})
        person = people.get(person_id)
        if person is None:
            return False
        added = add_identity_inplace(person, platform, handle, profile=profile, label=label)
        if added:
            _save_raw(data)
        return added


def remove_identity(person_id: str, platform: str, handle: str) -> bool:
    nh = _norm_handle(platform, handle)
    with _LOCK:
        data = _load_raw()
        person = data.get("people", {}).get(person_id)
        if not person:
            return False
        before = len(person.get("identities", []))
        person["identities"] = [
            i for i in person.get("identities", [])
            if not (i.get("platform") == platform and _norm_handle(platform, i.get("handle","")) == nh)
        ]
        if len(person["identities"]) != before:
            person["updated_at"] = _now_iso()
            _save_raw(data)
            return True
        return False


def delete_person(person_id: str) -> bool:
    with _LOCK:
        data = _load_raw()
        if person_id in data.get("people", {}):
            del data["people"][person_id]
            _save_raw(data)
            return True
        return False


def merge_people(keep_id: str, merge_id: str) -> Optional[dict[str, Any]]:
    """Move todas as identidades de merge_id para keep_id e deleta merge_id."""
    if keep_id == merge_id:
        return get_person(keep_id)
    with _LOCK:
        data = _load_raw()
        people = data.get("people", {})
        a, b = people.get(keep_id), people.get(merge_id)
        if not a or not b:
            return None
        for ident in b.get("identities", []):
            add_identity_inplace(a, ident.get("platform",""), ident.get("handle",""),
                                 profile=ident.get("profile"), label=ident.get("label"))
        a["tags"] = sorted(set(a.get("tags", []) + b.get("tags", [])))
        if b.get("notes") and not a.get("notes"):
            a["notes"] = b["notes"]
        a["updated_at"] = _now_iso()
        del people[merge_id]
        _save_raw(data)
        return a


__all__ = [
    "list_people", "get_person", "find_by_identity", "resolve_person_id",
    "upsert_person", "add_identity", "remove_identity",
    "delete_person", "merge_people",
    "is_self_account",
]


# ─── Self-account detection ─────────────────────────────────────────────────
# Identifica se um (platform, handle) é a CONTA DO PRÓPRIO USUÁRIO logado
# em outro dispositivo — para não responder a si mesmo no #Jarvis nem
# notificar mensagens auto-enviadas. Consulta:
#   1) config.SELF_ACCOUNTS (env vars JARVIS_*_MY_*) — fonte primária
#   2) identidades marcadas com `is_self=True` no people.json (opcional)

def is_self_account(platform: str, handle: str) -> bool:
    if not platform or not handle:
        return False
    nh = _norm_handle(platform, handle)
    if not nh:
        return False
    # 1) config
    try:
        import config as _cfg
        selfs = (getattr(_cfg, "SELF_ACCOUNTS", {}) or {}).get(platform, []) or []
        for s in selfs:
            if _norm_handle(platform, s) == nh:
                return True
    except Exception:
        pass
    # 2) flag is_self no people.json
    try:
        with _LOCK:
            for p in _load_raw().get("people", {}).values():
                for ident in p.get("identities", []):
                    if (ident.get("platform") == platform
                            and ident.get("is_self") is True
                            and _norm_handle(platform, ident.get("handle","")) == nh):
                        return True
    except Exception:
        pass
    return False
