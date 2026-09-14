"""C — caracterização (F2-09): `_fazer_restart` no Windows continua
idêntico depois de virar `jarvis.platform.windows.processes.restart_self`.
"""
from tests.golden.legacy_31bc0ce import legacy_fazer_restart


def test_frozen_relaunches_own_executable():
    calls = []

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))

    legacy_fazer_restart(
        frozen=True, sys_executable=r"C:\JARVIS\JARVIS.exe", root=r"C:\JARVIS", popen_fn=fake_popen
    )
    assert calls == [((["C:\\JARVIS\\JARVIS.exe"],), {})]


def test_dev_opens_powershell_with_create_new_console():
    calls = []

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))

    legacy_fazer_restart(
        frozen=False,
        sys_executable=r"C:\Python\python.exe",
        root=r"C:\repo",
        popen_fn=fake_popen,
    )
    assert len(calls) == 1
    (cmd_args,), kwargs = calls[0]
    assert cmd_args[0] == "powershell"
    assert cmd_args[1:4] == ["-NoLogo", "-NoExit", "-Command"]
    ps_cmd = cmd_args[4]
    assert r"C:\repo\.venv\Scripts\Activate.ps1" in ps_cmd
    assert r"C:\repo\main.py" in ps_cmd
    assert kwargs == {"creationflags": 0x10}
