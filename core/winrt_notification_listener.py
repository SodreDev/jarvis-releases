# -*- coding: utf-8 -*-
"""
core/winrt_notification_listener.py
───────────────────────────────────
Captura notificações nativas do Windows via UserNotificationListener
(API moderna Win10+) usando o pacote `winsdk` já instalado.

Vantagens vs SetWinEventHook:
  • Texto completo do remetente e corpo da notificação (não só título).
  • Funciona para QUALQUER app que mostre toast (não só foreground).
  • Inclui notificações silenciadas (DND-aware via filtro).

Limitações:
  • Requer permissão "Notification access" no Windows Settings.
  • Se permissão negada → fallback para SetWinEventHook existente.

Uso:
    from core.winrt_notification_listener import WinRTNotificationListener
    lst = WinRTNotificationListener(on_message=lambda app,sender,body,raw: ...)
    if lst.start():
        ...
    lst.stop()
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Callable, Optional

# Tipo do callback: (app_key, sender, body, raw_dict)
NotificationCB = Callable[[str, str, str, dict], None]


async def _to_aw(op):
    """Aguarda um IAsyncOperation do WinRT (winsdk integra com asyncio)."""
    return await op


# Map de AUMID conhecidos → app_key estável
_AUMID_MAP = {
    "whatsappdesktop":    "whatsapp",
    "whatsapp.desktop":   "whatsapp",
    "discord.discord":    "discord",
    "discord":            "discord",
    "5319275a.whatsappdesktop": "whatsapp",
    "facebook.317180b0bb486":   "instagram",  # IG via Messenger? raro
    "instagram.instagram": "instagram",
    "telegram.telegramdesktop": "telegram",
    "microsoft.windowscommunicationsapps": "outlook",
}


def _app_key_from_aumid(aumid: str) -> str:
    low = (aumid or "").lower()
    for needle, key in _AUMID_MAP.items():
        if needle in low:
            return key
    # heurística: pega a parte mais à direita antes do "!"
    if "!" in low:
        tail = low.split("!", 1)[0]
    else:
        tail = low
    for k in ("discord", "whatsapp", "instagram", "telegram", "outlook", "gmail"):
        if k in tail:
            return k
    return tail or "desconhecido"


class WinRTNotificationListener:
    """Listener de notificações do Windows via WinRT. Roda thread polling
    (~1s) porque a API nativa de callback exige um loop COM apartment."""

    POLL_INTERVAL = 1.0

    def __init__(self, on_message: NotificationCB):
        self._cb = on_message
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._seen_ids: set[int] = set()
        self._listener = None  # type: ignore[var-annotated]

    # ─── lifecycle ───────────────────────────────────────────────────────

    def start(self) -> bool:
        """Tenta ativar o listener. Retorna False se não houver permissão
        ou se winsdk não estiver disponível — caller deve usar fallback."""
        try:
            from winsdk.windows.ui.notifications.management import (
                UserNotificationListener,
                UserNotificationListenerAccessStatus,
            )
            self._listener = UserNotificationListener.current
            status = asyncio.run(_to_aw(self._listener.request_access_async()))
            if status != UserNotificationListenerAccessStatus.ALLOWED:
                print(f"[WINRT-NOTIF] permissão negada (status={status}). "
                      "Habilite em Windows > Privacidade > Notificações.")
                return False
        except Exception as e:
            print(f"[WINRT-NOTIF] indisponível: {e}")
            return False

        # Snapshot inicial: tudo o que já existe NÃO dispara callback
        try:
            from winsdk.windows.ui.notifications import NotificationKinds
            initial = asyncio.run(_to_aw(
                self._listener.get_notifications_async(NotificationKinds.TOAST)
            ))
            for n in initial:
                self._seen_ids.add(int(n.id))
        except Exception as e:
            print(f"[WINRT-NOTIF] snapshot inicial falhou: {e}")

        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="WinRTNotifListener"
        )
        self._thread.start()
        print(f"[WINRT-NOTIF] iniciado. snapshot inicial: {len(self._seen_ids)} notif.")
        return True

    def stop(self) -> None:
        self._running = False
        self._thread = None

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    # ─── poll loop ───────────────────────────────────────────────────────

    def _loop(self) -> None:
        from winsdk.windows.ui.notifications import NotificationKinds
        # Cada thread precisa de seu próprio event loop p/ asyncio.run_until_complete
        loop = asyncio.new_event_loop()
        try:
            while self._running:
                try:
                    items = loop.run_until_complete(_to_aw(
                        self._listener.get_notifications_async(NotificationKinds.TOAST)
                    ))
                    for n in items:
                        nid = int(n.id)
                        if nid in self._seen_ids:
                            continue
                        self._seen_ids.add(nid)
                        info = self._parse(n)
                        if info is None:
                            continue
                        try:
                            self._cb(info["app_key"], info["sender"],
                                      info["body"], info["raw"])
                        except Exception as cbe:
                            print(f"[WINRT-NOTIF] callback err: {cbe}")
                    # GC: nunca deixa _seen_ids crescer indefinidamente
                    if len(self._seen_ids) > 2000:
                        self._seen_ids = set(list(self._seen_ids)[-1000:])
                except Exception as e:
                    print(f"[WINRT-NOTIF] loop err: {e}")
                time.sleep(self.POLL_INTERVAL)
        finally:
            try:
                loop.close()
            except Exception:
                pass

    # ─── parsing ─────────────────────────────────────────────────────────

    def _parse(self, n) -> Optional[dict]:
        try:
            app_info = n.app_info
            aumid = getattr(app_info, "app_user_model_id", "") or ""
            display = getattr(app_info, "display_info", None)
            app_display = getattr(display, "display_name", "") if display else ""
            toast = n.notification.visual.get_binding("ToastGeneric") or \
                    n.notification.visual.bindings[0]
            texts: list[str] = []
            for t in toast.get_text_elements():
                try:
                    texts.append(t.text or "")
                except Exception:
                    pass
            # 1ª linha geralmente é "Sender" ou "Sender — title"
            # 2ª/3ª linhas são corpo da mensagem.
            sender = texts[0] if texts else ""
            body = "\n".join(texts[1:]) if len(texts) > 1 else ""
            # WhatsApp/Discord: às vezes o sender vem como "X (Y mensagens)"
            sender = sender.split(" (")[0].strip()
            return {
                "app_key": _app_key_from_aumid(aumid),
                "sender": sender,
                "body": body,
                "raw": {
                    "aumid": aumid,
                    "app_display": app_display,
                    "texts": texts,
                    "id": int(n.id),
                },
            }
        except Exception as e:
            print(f"[WINRT-NOTIF] parse err: {e}")
            return None
