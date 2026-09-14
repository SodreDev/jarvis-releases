"""K — contrato (F2-04, tools-lab): `comandos/clipboard_hist_ctrl.py`
passa a rodar `get(Cap.CLIPBOARD).watch(_on_change, _stop_event)` numa
thread, em vez do `_monitor_loop` com `ctypes.windll` direto — mesmas
regras de dedupe/limite de histórico (SPEC F2-04). Ainda não implementado
— `xfail(strict=True, reason="F2-04")`.
"""
import threading
import time

import pytest

pytestmark = []


class _FakeCapClipboard:
    """`watch(on_change, stop_event)` chama `on_change(texto)` para cada
    item de `changes`, depois bloqueia até `stop_event` ser sinalizado —
    igual ao contrato real (bloqueia até `stop`)."""

    can_watch = True

    def __init__(self, changes):
        self._changes = changes

    def watch(self, on_change, stop_event):
        for text in self._changes:
            on_change(text)
        stop_event.wait(timeout=2)
        return True


def test_start_monitor_uses_cap_clipboard_watch(monkeypatch):
    from comandos import clipboard_hist_ctrl as chc

    fake = _FakeCapClipboard(["primeiro", "primeiro", "segundo"])
    monkeypatch.setattr(chc, "_plat_get_clipboard", lambda: fake)

    chc._history.clear()
    chc.start_monitor()
    time.sleep(0.2)
    chc._stop_event.set()

    assert chc._history == ["primeiro", "segundo"]


def test_start_monitor_no_backend_logs_once(monkeypatch, capsys):
    from comandos import clipboard_hist_ctrl as chc

    class _NoWatch:
        can_watch = False

    monkeypatch.setattr(chc, "_plat_get_clipboard", lambda: _NoWatch())
    chc.start_monitor()
    time.sleep(0.2)
    out = capsys.readouterr().out
    assert out.count("monitor de clipboard desligado") <= 1
