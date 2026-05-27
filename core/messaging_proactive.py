"""Messaging Proactive Rules — decide o que fazer quando uma mensagem chega.

Subscreve `messaging.incoming` no event_bus e aplica regras configuráveis:
  • Silenciar tudo durante game_mode / foco / quiet hours
  • Anunciar via TTS se INBOX_NOTIFY_TTS=True
  • Auto-resposta opcional ("Estou ocupado, te respondo às X")
  • Resumo agendado: "Você tem N mensagens novas — quer que eu leia?"

Para evitar spam, mantém cooldown por (platform, profile) e batching:
  mensagens dentro de BATCH_WINDOW_S são agrupadas em um único anúncio.

Configuração (config.py):
  INBOX_NOTIFY_TTS              : bool — fala "nova mensagem de X" via TTS
  INBOX_TTS_TEMPLATE            : str — template (default: "Nova mensagem de {sender} no {platform}")
  INBOX_QUIET_HOURS             : list[int]
  INBOX_RESPECT_GAME_MODE       : bool (default True)
  INBOX_BATCH_WINDOW_S          : int (default 8)
  INBOX_PROACTIVE_THRESHOLD     : int — só anuncia se >= N mensagens não lidas (default 1)
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


def _get_cfg(name, default):
    try:
        import config as _cfg
        return getattr(_cfg, name, default)
    except Exception:
        return default


class MessagingProactive:
    def __init__(self) -> None:
        self._speak_cb: Optional[Callable[[str], None]] = None
        self._lock = threading.RLock()
        self._batch: list[dict[str, Any]] = []
        self._batch_timer: Optional[threading.Timer] = None
        self._installed = False

    def set_speak_callback(self, fn: Optional[Callable[[str], None]]) -> None:
        self._speak_cb = fn

    def install(self) -> None:
        if self._installed:
            return
        try:
            from core.event_bus import subscribe
            subscribe("messaging.incoming", self._on_incoming)
            self._installed = True
            log.info("MessagingProactive instalado")
        except Exception as e:                                      # noqa: BLE001
            log.warning("MessagingProactive install falhou: %s", e)

    # ---------- regras de gating ----------
    def _is_quiet_hour(self) -> bool:
        quiet = _get_cfg("INBOX_QUIET_HOURS", [])
        try:
            if not quiet:
                return False
            hr = datetime.now().hour
            return hr in [int(h) for h in quiet]
        except Exception:
            return False

    def _game_active(self) -> bool:
        if not _get_cfg("INBOX_RESPECT_GAME_MODE", True):
            return False
        try:
            from core.game_mode_manager import is_game_mode_active
            return bool(is_game_mode_active())
        except Exception:
            return False

    def _should_announce(self, ev: dict[str, Any]) -> bool:
        if not _get_cfg("INBOX_NOTIFY_TTS", False):
            return False
        if self._is_quiet_hour():
            return False
        if self._game_active():
            return False
        threshold = int(_get_cfg("INBOX_PROACTIVE_THRESHOLD", 1))
        if int(ev.get("unread_count", 1)) < threshold:
            return False
        return True

    # ---------- handler ----------
    def _on_incoming(self, ev: dict[str, Any]) -> None:
        try:
            if not self._should_announce(ev):
                return
            with self._lock:
                self._batch.append(ev)
                if self._batch_timer is None:
                    delay = max(1.0, float(_get_cfg("INBOX_BATCH_WINDOW_S", 8)))
                    self._batch_timer = threading.Timer(delay, self._flush_batch)
                    self._batch_timer.daemon = True
                    self._batch_timer.start()
        except Exception as e:                                      # noqa: BLE001
            log.debug("MessagingProactive handler erro: %s", e)

    def _flush_batch(self) -> None:
        with self._lock:
            items = list(self._batch)
            self._batch.clear()
            self._batch_timer = None
        if not items or self._speak_cb is None:
            return
        try:
            phrase = self._build_phrase(items)
            if phrase:
                self._speak_cb(phrase)
        except Exception as e:                                      # noqa: BLE001
            log.debug("MessagingProactive flush erro: %s", e)

    def _build_phrase(self, items: list[dict[str, Any]]) -> str:
        template = _get_cfg(
            "INBOX_TTS_TEMPLATE",
            "Nova mensagem de {sender} no {platform}.",
        )
        if len(items) == 1:
            ev = items[0]
            try:
                return template.format(
                    sender=ev.get("sender", "?"),
                    platform=ev.get("platform", "?"),
                    profile=ev.get("profile", ""),
                    preview=ev.get("preview", ""),
                    count=ev.get("unread_count", 1),
                )
            except Exception:
                return f"Nova mensagem de {ev.get('sender','?')}."
        # múltiplas
        senders = sorted({(it.get("sender") or "?") for it in items})
        plats = sorted({(it.get("platform") or "?") for it in items})
        if len(senders) == 1:
            return f"{len(items)} novas mensagens de {senders[0]}."
        return f"{len(items)} novas mensagens em {', '.join(plats)}."


# ---------- singleton ----------
_inst: MessagingProactive | None = None


def get_messaging_proactive() -> MessagingProactive:
    global _inst
    if _inst is None:
        _inst = MessagingProactive()
    return _inst


__all__ = ["MessagingProactive", "get_messaging_proactive"]
