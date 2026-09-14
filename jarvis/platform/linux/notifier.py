"""Notificações do sistema no Linux (F2-05). O Windows não envia nesta fase (D-F2-5).

Cadeia no REGISTRY (linux-wayland e linux-x11; headless não tem notifier):
- ``DbusNotifier``: ``org.freedesktop.Notifications.Notify`` via jeepney, com
  app_name ``APP_NAME``, ícone vazio e os hints ``urgency`` (byte 0/1/2) e
  ``desktop-entry`` = ``APP_ID`` (o servidor pega nome e ícone do .desktop).
  Sonda: o nome tem dono no D-Bus de sessão (até 1 s).
- ``NotifySendNotifier``: ``notify-send -a APP_NAME -u <urgência> [-t ms]``.
  Sonda: ``notify-send`` no PATH.

``notify`` nunca levanta: devolve False quando a notificação não saiu.
"""
from __future__ import annotations

from ..common.base import BackendBase, Probe
from . import dbus as _dbus
from . import tools
from .app_id import APP_ID, APP_NAME

BUS_NAME = "org.freedesktop.Notifications"
OBJECT_PATH = "/org/freedesktop/Notifications"
INTERFACE = "org.freedesktop.Notifications"
NOTIFY_SIGNATURE = "susssasa{sv}i"

URGENCY_BYTES = {"low": 0, "normal": 1, "critical": 2}


def urgency_name(urgency) -> str:
    """Normaliza a urgência ("low", "normal", "critical"); desconhecida vira "normal"."""
    nome = str(urgency or "").strip().lower()
    return nome if nome in URGENCY_BYTES else "normal"


def _timeout_ms(timeout_ms) -> int:
    return -1 if timeout_ms is None else int(timeout_ms)


class DbusNotifier(BackendBase):
    name = "linux.dbus_notifications"

    @classmethod
    def probe(cls, ctx) -> Probe:
        try:
            if _dbus.name_has_owner(BUS_NAME, timeout=_dbus.PROBE_TIMEOUT):
                return Probe(True)
        except Exception as e:
            return Probe(False, f"probe: {type(e).__name__}: {e}")
        return Probe(False, f"{BUS_NAME} sem dono no D-Bus de sessão")

    def notify(self, title: str, body: str, *, urgency: str = "normal", timeout_ms: int = -1) -> bool:
        hints = {
            "urgency": ("y", URGENCY_BYTES[urgency_name(urgency)]),
            "desktop-entry": ("s", APP_ID),
        }
        args = (APP_NAME, 0, "", str(title), str(body), [], hints, _timeout_ms(timeout_ms))
        try:
            _dbus.call(
                BUS_NAME, OBJECT_PATH, INTERFACE, "Notify", NOTIFY_SIGNATURE, args, _dbus.CALL_TIMEOUT
            )
        except Exception as e:
            print(f"[NOTIF] Notify via D-Bus falhou: {e}")
            return False
        return True


class NotifySendNotifier(BackendBase):
    name = "linux.notify_send"

    @classmethod
    def probe(cls, ctx) -> Probe:
        if tools.which("notify-send"):
            return Probe(True)
        return Probe(False, "notify-send ausente no PATH")

    def notify(self, title: str, body: str, *, urgency: str = "normal", timeout_ms: int = -1) -> bool:
        argv = [
            "notify-send", "-a", APP_NAME, "-u", urgency_name(urgency),
            "-h", f"string:desktop-entry:{APP_ID}",
        ]
        ms = _timeout_ms(timeout_ms)
        if ms >= 0:
            argv += ["-t", str(ms)]
        argv += ["--", str(title), str(body)]
        r = tools.run_tool(argv)
        return r is not None and r.returncode == 0
