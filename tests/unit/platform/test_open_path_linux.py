"""K — contrato (F2-06): `jarvis.platform.linux.open_path` (ainda não
existe — import dentro de cada teste). `xfail(strict=True, reason="F2-06")`.
"""
import subprocess

import pytest

pytestmark = [pytest.mark.linux_only]


def test_xdg_open_calls_detached_and_not_registered_as_child():
    from jarvis.platform.linux.open_path import XdgOpen

    calls = []

    class _FakeProc:
        pass

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return _FakeProc()

    ok = XdgOpen(popen_fn=fake_popen).open("https://exemplo.com")
    assert ok is True
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["xdg-open", "https://exemplo.com"]
    assert kwargs.get("start_new_session") is True
    assert kwargs.get("close_fds") is True
    assert kwargs.get("stdin") == subprocess.DEVNULL
    assert kwargs.get("stdout") == subprocess.DEVNULL
    assert kwargs.get("stderr") == subprocess.DEVNULL


def test_open_text_file_delegates_to_xdg_open(tmp_path):
    from jarvis.platform.linux.open_path import XdgOpen

    p = tmp_path / "arquivo.txt"
    p.write_text("conteudo")

    calls = []

    class _FakeProc:
        pass

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return _FakeProc()

    # open_text_file no Linux = open() do BACKEND (xdg-open, com fallback
    # gio open) — não o builtin open() do Python, que não mostraria nada ao
    # usuário. Mesma ideia de "método open do adapter", como o notepad.exe
    # do Windows continua conferido no golden (test_startfile_callsites.py).
    ok = XdgOpen(popen_fn=fake_popen).open_text_file(str(p))
    assert ok is True
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["xdg-open", str(p)]
    assert kwargs.get("start_new_session") is True
    assert kwargs.get("close_fds") is True


def test_open_text_file_delegates_to_gio_open_fallback(tmp_path):
    from jarvis.platform.linux.open_path import GioOpen

    p = tmp_path / "arquivo.txt"
    p.write_text("conteudo")

    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))

        class _FakeProc:
            pass

        return _FakeProc()

    ok = GioOpen(popen_fn=fake_popen).open_text_file(str(p))
    assert ok is True
    assert calls[0][0] == ["gio", "open", str(p)]


def test_gio_open_fallback():
    from jarvis.platform.linux.open_path import GioOpen

    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))

        class _FakeProc:
            pass

        return _FakeProc()

    GioOpen(popen_fn=fake_popen).open("/tmp/arquivo.pdf")
    assert calls[0][0] == ["gio", "open", "/tmp/arquivo.pdf"]
