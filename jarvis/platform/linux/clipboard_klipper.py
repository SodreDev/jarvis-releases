"""Clipboard pelo Klipper do KDE (F2-04), via D-Bus de sessão.

``org.kde.klipper`` ``/klipper`` ``org.kde.klipper.klipper``:
``getClipboardContents``/``setClipboardContents``; ``watch`` = sinal
``clipboardHistoryUpdated`` → ``getClipboardContents``. Sonda: ``org.kde.klipper``
tem dono. Falhas viram None/False, nunca exceção.
"""
from __future__ import annotations

from ..common.base import BackendBase, Probe
from . import dbus as _dbus

BUS_NAME = "org.kde.klipper"
OBJECT_PATH = "/klipper"
INTERFACE = "org.kde.klipper.klipper"


def klipper_available(timeout: float = _dbus.PROBE_TIMEOUT) -> bool:
    """O Klipper está no D-Bus de sessão? Qualquer falha dá False."""
    return _dbus.name_has_owner(BUS_NAME, timeout=timeout)


class KlipperClipboard(BackendBase):
    name = "linux.klipper"
    can_watch = True

    def __init__(self, ctx=None):
        self.ctx = ctx

    @classmethod
    def probe(cls, ctx) -> Probe:
        if klipper_available():
            return Probe(True)
        return Probe(False, f"{BUS_NAME} sem dono no D-Bus de sessão")

    def get_text(self):
        try:
            (texto,) = _dbus.call(BUS_NAME, OBJECT_PATH, INTERFACE, "getClipboardContents")
        except Exception:
            return None
        return texto

    def set_text(self, text: str) -> bool:
        try:
            _dbus.call(BUS_NAME, OBJECT_PATH, INTERFACE, "setClipboardContents", "s", (str(text),))
        except Exception:
            return False
        return True

    def watch(self, on_change, stop) -> bool:
        try:
            regra = _dbus.match_rule(interface=INTERFACE, member="clipboardHistoryUpdated", path=OBJECT_PATH)
            fila = _dbus.subscribe(regra)
        except Exception as e:
            print(f"[CLIPBOARD] Klipper sem sinal de mudança: {e}")
            return False
        with fila:
            while not stop.is_set():
                if fila.get(timeout=0.5) is None:
                    continue
                texto = self.get_text()
                if texto:
                    on_change(texto)
        return True
