"""K — contrato (F2-09): `PosixProcesses.restart_self`
(`jarvis/platform/linux/processes.py`, ainda não existe — import dentro
de cada teste). `xfail(strict=True, reason="F2-09")`.
"""
import subprocess

import pytest

pytestmark = [pytest.mark.linux_only]


def _fake_popen():
    calls = []

    def _popen(args, **kwargs):
        calls.append((args, kwargs))

    return _popen, calls


def test_restart_self_appimage(monkeypatch):
    from jarvis.platform.linux.processes import PosixProcesses

    monkeypatch.setenv("APPIMAGE", "/tmp/Jarvis.AppImage")
    popen_fn, calls = _fake_popen()
    PosixProcesses(popen_fn=popen_fn).restart_self(
        main_path="/opt/jarvis/main.py", frozen=False, argv=["--flag"]
    )
    assert calls[0][0] == ["/tmp/Jarvis.AppImage", "--flag"]


def test_restart_self_frozen(monkeypatch):
    import sys

    from jarvis.platform.linux.processes import PosixProcesses

    monkeypatch.delenv("APPIMAGE", raising=False)
    popen_fn, calls = _fake_popen()
    PosixProcesses(popen_fn=popen_fn).restart_self(
        main_path="/opt/jarvis/main.py", frozen=True, argv=["--flag"]
    )
    assert calls[0][0] == [sys.executable, "--flag"]


def test_restart_self_dev(monkeypatch):
    import sys

    from jarvis.platform.linux.processes import PosixProcesses

    monkeypatch.delenv("APPIMAGE", raising=False)
    popen_fn, calls = _fake_popen()
    PosixProcesses(popen_fn=popen_fn).restart_self(
        main_path="/repo/main.py", frozen=False, argv=[]
    )
    assert calls[0][0] == [sys.executable, "/repo/main.py"]


def test_restart_self_kwargs_detached_not_registered():
    from jarvis.platform.linux.processes import PosixProcesses

    popen_fn, calls = _fake_popen()
    PosixProcesses(popen_fn=popen_fn).restart_self(
        main_path="/repo/main.py", frozen=False, argv=[]
    )
    _args, kwargs = calls[0]
    assert kwargs.get("cwd") == "/repo"
    assert kwargs.get("start_new_session") is True
    assert kwargs.get("stdin") == subprocess.DEVNULL
