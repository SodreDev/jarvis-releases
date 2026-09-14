"""K F2-09: restart_self nos adapters.

- Windows (W1): WindowsProcesses.restart_self faz a MESMA chamada de Popen que o
  oráculo legado de 31bc0ce (frozen → [sys.executable]; dev → PowerShell com o
  Activate.ps1 e creationflags 0x10), com ntpath injetado para rodar no Linux.
- Linux: a nova instância não é registrada como filho e herda o ambiente.
"""
import ntpath

from jarvis.platform.linux.processes import PosixProcesses
from jarvis.platform.windows.processes import WindowsProcesses
from tests.golden.legacy_31bc0ce import legacy_fazer_restart


def _gravador():
    calls = []

    def popen(*args, **kwargs):
        calls.append((args, kwargs))

    return popen, calls


def test_windows_frozen_igual_ao_legado():
    novo, calls_novo = _gravador()
    velho, calls_velho = _gravador()
    exe = r"C:\JARVIS\JARVIS.exe"
    WindowsProcesses(popen_fn=novo, executable=exe, path_mod=ntpath).restart_self(
        main_path=r"C:\JARVIS\_internal\main.py", frozen=True
    )
    legacy_fazer_restart(frozen=True, sys_executable=exe, root=r"C:\JARVIS", popen_fn=velho)
    assert calls_novo == calls_velho == [(([exe],), {})]


def test_windows_dev_igual_ao_legado():
    novo, calls_novo = _gravador()
    velho, calls_velho = _gravador()
    WindowsProcesses(popen_fn=novo, executable=r"C:\Python\python.exe", path_mod=ntpath).restart_self(
        main_path=r"C:\repo\main.py", frozen=False
    )
    legacy_fazer_restart(
        frozen=False, sys_executable=r"C:\Python\python.exe", root=r"C:\repo", popen_fn=velho
    )
    assert calls_novo == calls_velho
    assert calls_novo[0][1] == {"creationflags": 0x10}


def test_windows_ignora_argv():
    novo, calls = _gravador()
    WindowsProcesses(popen_fn=novo, executable=r"C:\JARVIS\JARVIS.exe", path_mod=ntpath).restart_self(
        main_path=r"C:\JARVIS\main.py", frozen=True, argv=["--qualquer"]
    )
    assert calls == [(([r"C:\JARVIS\JARVIS.exe"],), {})]


def test_linux_nao_registra_filho_e_herda_ambiente(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    novo, calls = _gravador()
    proc = PosixProcesses(popen_fn=novo)
    proc.restart_self(main_path="/repo/main.py", frozen=False, argv=["--x"])
    (cmd,), kwargs = calls[0]
    assert cmd[1:] == ["/repo/main.py", "--x"]
    assert "env" not in kwargs and "shell" not in kwargs
    assert proc.alive_children() == []


def test_linux_argv_padrao_e_sys_argv(monkeypatch):
    import sys

    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(sys, "argv", ["main.py", "--debug"])
    novo, calls = _gravador()
    PosixProcesses(popen_fn=novo).restart_self(main_path="/repo/main.py", frozen=False)
    assert calls[0][0][0] == [sys.executable, "/repo/main.py", "--debug"]
