"""InboxWatcher — varre periodicamente as conversas não lidas em todas as
plataformas/perfis logados e emite eventos `messaging.incoming` no event_bus.

Estratégia (Fase 2 do roadmap):
  • A cada `INBOX_POLL_INTERVAL_S` segundos, para cada (platform, profile)
    cujo backend `is_available()` retorna True (sessão salva no disco),
    chama backend.read_inbox(). Cada Message é deduplicada vs último snapshot.
  • Itens novos OU com unread_count maior que antes geram um evento.
  • Snapshot é guardado em memória (e em `notif_history.jsonl` para audit).

Configuração (config.py):
  INBOX_WATCHER_ENABLED          : bool (default True)
  INBOX_POLL_INTERVAL_S          : int  (default 30, min 10)
  INBOX_NOTIFY_TTS               : bool (default False) — fala "nova mensagem de X"
  INBOX_QUIET_HOURS              : list[int] (default []) — horas em que silencia
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.event_bus import publish

log = logging.getLogger(__name__)

_PLATFORMS = ("whatsapp", "instagram", "discord", "telegram", "gmail")
_PROFILES = ("jarvis", "user")
_HISTORY_FILE = "notif_history.jsonl"


def _get_cfg(name: str, default):
    try:
        import config as _cfg
        return getattr(_cfg, name, default)
    except Exception:
        return default


class InboxWatcher:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # snapshot: { "<plat>:<prof>:<chat_id>": {"count": int, "preview": str, "ts": iso} }
        self._snapshot: dict[str, dict[str, Any]] = {}
        # Última varredura por (plat,prof) para UI
        self._last_scan: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.RLock()

    # ---------- ciclo de vida ----------
    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="jarvis-inbox-watcher", daemon=True
        )
        self._thread.start()
        log.info("InboxWatcher iniciado")
        return True

    def stop(self) -> bool:
        self._stop.set()
        t = self._thread
        if t:
            t.join(timeout=3.0)
        self._thread = None
        log.info("InboxWatcher parado")
        return True

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ---------- estado / API ----------
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.is_running(),
                "items": dict(self._snapshot),
                "last_scan": {
                    f"{p}:{q}": v for (p, q), v in self._last_scan.items()
                },
            }

    def force_scan(self) -> dict[str, Any]:
        """Roda uma varredura síncrona agora. Útil pra UI ‘Atualizar’."""
        self._scan_all()
        return self.snapshot()

    # ---------- núcleo ----------
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if _get_cfg("INBOX_WATCHER_ENABLED", True):
                    self._scan_all()
            except Exception as e:                                  # noqa: BLE001
                log.warning("InboxWatcher scan falhou: %s", e)
            interval = max(10, int(_get_cfg("INBOX_POLL_INTERVAL_S", 30)))
            # Sleep cortável pelo stop
            for _ in range(interval):
                if self._stop.is_set():
                    return
                time.sleep(1.0)

    def _is_quiet_hour(self) -> bool:
        quiet = _get_cfg("INBOX_QUIET_HOURS", [])
        try:
            if not isinstance(quiet, (list, tuple)) or not quiet:
                return False
            hr = datetime.now().hour
            return hr in [int(h) for h in quiet]
        except Exception:
            return False

    def _scan_all(self) -> None:
        # Import lazy pra evitar custo no boot
        try:
            from jarvis.messaging.base import get_backend
        except Exception as e:                                      # noqa: BLE001
            log.debug("messaging.base indisponível: %s", e)
            return

        for plat in _PLATFORMS:
            for prof in _PROFILES:
                if self._stop.is_set():
                    return
                self._scan_one(plat, prof, get_backend)

    def _scan_one(self, plat: str, prof: str, get_backend) -> None:
        try:
            be = get_backend(plat, prof)  # type: ignore[arg-type]
        except Exception:
            be = None
        if be is None:
            return
        try:
            if not be.is_available():
                return
        except Exception:
            return

        scan_ts = datetime.utcnow().isoformat() + "Z"
        try:
            msgs = be.read_inbox()
        except Exception as e:                                      # noqa: BLE001
            log.debug("read_inbox %s/%s erro: %s", plat, prof, e)
            with self._lock:
                self._last_scan[(plat, prof)] = {
                    "ok": False, "ts": scan_ts, "error": str(e), "items": 0,
                }
            return

        items = msgs or []
        with self._lock:
            self._last_scan[(plat, prof)] = {
                "ok": True, "ts": scan_ts, "error": None, "items": len(items),
            }

        new_events: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for m in items:
            try:
                key = m.id
                seen_ids.add(key)
                count = int((m.raw or {}).get("unread_count") or 1)
                prev = self._snapshot.get(key)
                is_new = prev is None
                bumped = (not is_new) and count > int(prev.get("count") or 0)
                if is_new or bumped:
                    ev = {
                        "platform": m.platform,
                        "profile": m.profile,
                        "chat_id": (m.raw or {}).get("chat_id") or m.sender,
                        "sender": m.sender,
                        "preview": m.content,
                        "unread_count": count,
                        "ts": (m.timestamp or datetime.utcnow()).isoformat() + "Z",
                        "is_new": is_new,
                    }
                    new_events.append(ev)
                with self._lock:
                    self._snapshot[key] = {
                        "count": count,
                        "preview": m.content,
                        "sender": m.sender,
                        "platform": m.platform,
                        "profile": m.profile,
                        "ts": (m.timestamp or datetime.utcnow()).isoformat() + "Z",
                    }
            except Exception:
                continue

        # Purga chats que sumiram da lista (foram lidos em outra interface)
        prefix = f"{plat}:{prof}:"
        with self._lock:
            stale = [k for k in self._snapshot if k.startswith(prefix) and k not in seen_ids]
            for k in stale:
                self._snapshot.pop(k, None)

        if new_events and not self._is_quiet_hour():
            self._emit(new_events)

    # ---------- emissão ----------
    def _emit(self, events: list[dict[str, Any]]) -> None:
        # Enriquece com person_id se já mapeado
        try:
            from core.person_registry import resolve_person_id
        except Exception:
            resolve_person_id = None  # type: ignore[assignment]
        for ev in events:
            try:
                if resolve_person_id is not None:
                    pid = resolve_person_id(ev.get("platform", ""), ev.get("chat_id") or ev.get("sender") or "")
                    if pid:
                        ev["person_id"] = pid
            except Exception:
                pass
            try:
                publish("messaging.incoming", ev)
            except Exception as e:                                  # noqa: BLE001
                log.debug("publish messaging.incoming falhou: %s", e)
            try:
                self._append_history(ev)
            except Exception:
                pass

    def _append_history(self, ev: dict[str, Any]) -> None:
        try:
            from jarvis.config.paths import project_root
            p = project_root() / _HISTORY_FILE
        except Exception:
            p = Path(_HISTORY_FILE)
        try:
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "messaging.incoming", **ev}, ensure_ascii=False) + "\n")
        except Exception:
            pass


# ---------- singleton ----------
_watcher: InboxWatcher | None = None


def get_inbox_watcher() -> InboxWatcher:
    global _watcher
    if _watcher is None:
        _watcher = InboxWatcher()
    return _watcher


__all__ = ["InboxWatcher", "get_inbox_watcher"]
