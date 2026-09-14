"""K — contrato (F2-06): `jarvis.platform.linux.open_path` (ainda não
existe — import dentro de cada teste). `xfail(strict=True, reason="F2-06")`.
"""
import subprocess

import pytest

pytestmark = [pytest.mark.linux_only, pytest.mark.xfail(strict=True, reason="F2-06")]


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


def test_open_text_file_is_plain_python_open(tmp_path):
    from jarvis.platform.linux.open_path import XdgOpen

    p = tmp_path / "arquivo.txt"
    p.write_text("conteudo")
    # open_text_file no Linux = open(path) — não deve levantar nem chamar
    # subprocess nenhum.
    ok = XdgOpen(popen_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("não deveria chamar Popen"))).open_text_file(str(p))
    assert ok is True


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
