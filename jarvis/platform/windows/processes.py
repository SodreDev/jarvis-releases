"""Limpeza de processos filhos no Windows via Job Object (KILL_ON_JOB_CLOSE).

`install_kill_on_close_job` é a CÓPIA LITERAL do bloco Job Object do main.py de
1c32e38 (mesmas estruturas, flags 0x2000|0x800, mesmos prints). ctypes e
ctypes.wintypes entram por parâmetro (lazy import quando ausentes) para o módulo
poder ser importado no Linux. O handle fica numa global do módulo, mantido vivo
(se fechar, o KILL_ON_JOB_CLOSE mataria o próprio JARVIS).
"""
from __future__ import annotations

from ..common.base import BackendBase

# Handle do Job Object mantido vivo pelo tempo de vida do processo.
_JOB_HANDLE = None


def install_kill_on_close_job(ct=None, wt=None):
    """Cria o Job Object KILL_ON_JOB_CLOSE|BREAKAWAY_OK e prende o processo nele.

    Retorna o handle (verdadeiro) em sucesso, None em falha. Cópia literal do
    bloco original do main.py, com ctypes/wintypes injetáveis.
    """
    if ct is None:
        import ctypes as ct
    if wt is None:
        from ctypes import wintypes as wt
    try:
        class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ct.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ct.c_int64),
                ("PerJobUserTimeLimit", ct.c_int64),
                ("LimitFlags", wt.DWORD),
                ("MinimumWorkingSetSize", ct.c_size_t),
                ("MaximumWorkingSetSize", ct.c_size_t),
                ("ActiveProcessLimit", wt.DWORD),
                ("Affinity", ct.c_void_p),
                ("PriorityClass", wt.DWORD),
                ("SchedulingClass", wt.DWORD),
            ]

        class _IO_COUNTERS(ct.Structure):
            _fields_ = [
                ("ReadOperationCount", ct.c_uint64),
                ("WriteOperationCount", ct.c_uint64),
                ("OtherOperationCount", ct.c_uint64),
                ("ReadTransferCount", ct.c_uint64),
                ("WriteTransferCount", ct.c_uint64),
                ("OtherTransferCount", ct.c_uint64),
            ]

        class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ct.Structure):
            _fields_ = [
                ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ct.c_size_t),
                ("JobMemoryLimit", ct.c_size_t),
                ("PeakProcessMemoryUsed", ct.c_size_t),
                ("PeakJobMemoryUsed", ct.c_size_t),
            ]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        # BREAKAWAY_OK permite que processos filhos que pedem
        # CREATE_BREAKAWAY_FROM_JOB escapem do job. Necessário pra
        # o navegador (Chrome/Brave/Edge) — Chromium detecta job e
        # altera comportamento de sandbox/IPC, abrindo SEM janela.
        JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
        JobObjectExtendedLimitInformation = 9

        kernel32 = ct.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wt.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ct.c_void_p, wt.LPCWSTR]
        kernel32.SetInformationJobObject.restype = wt.BOOL
        kernel32.AssignProcessToJobObject.restype = wt.BOOL
        kernel32.GetCurrentProcess.restype = wt.HANDLE

        _job = kernel32.CreateJobObjectW(None, None)
        if _job:
            info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = (
                JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                | JOB_OBJECT_LIMIT_BREAKAWAY_OK
            )
            ok = kernel32.SetInformationJobObject(
                _job,
                JobObjectExtendedLimitInformation,
                ct.byref(info),
                ct.sizeof(info),
            )
            if ok:
                assigned = kernel32.AssignProcessToJobObject(_job, kernel32.GetCurrentProcess())
                # Mantém o handle vivo (módulo global) — se for fechado,
                # o KILL_ON_JOB_CLOSE dispara e mata o próprio JARVIS.
                globals()["_JOB_HANDLE"] = _job
                print(f"[JOB] Job Object criado (KILL_ON_JOB_CLOSE), assigned={bool(assigned)}")
                return _job
            else:
                print(f"[JOB] SetInformationJobObject falhou: err={ct.get_last_error()}")
                return None
        else:
            print(f"[JOB] CreateJobObjectW falhou: err={ct.get_last_error()}")
            return None
    except Exception as _je:
        print(f"[JOB] Falha ao configurar Job Object: {_je}")
        return None


class WindowsProcesses(BackendBase):
    name = "windows.job_object"

    def __init__(self, ctx=None, *, popen_fn=None, executable=None, path_mod=None):
        self.ctx = ctx
        # Injetáveis só para os testes (W2); em produção: Popen, sys.executable, os.path.
        self._popen_fn = popen_fn
        self._executable = executable
        self._path_mod = path_mod

    def hidden_console_flags(self) -> int:
        import subprocess
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def install_child_cleanup(self) -> None:
        install_kill_on_close_job()

    def register_child(self, proc, *, tree: bool = False) -> None:
        # No Windows o Job Object cuida da limpeza; nada a registrar.
        return None

    def alive_children(self) -> list:
        return []

    def new_session_kwargs(self) -> dict:
        return {}

    def restart_self(self, *, main_path: str, frozen: bool, argv=None) -> None:
        """Cópia literal do `_fazer_restart` do main.py (31bc0ce). O sleep, o
        destroy e o os._exit continuam no main.py. `argv` é ignorado: o restart
        do Windows nunca repassou argumentos."""
        import subprocess
        import sys

        popen = self._popen_fn or subprocess.Popen
        executable = self._executable or sys.executable

        if frozen:
            # Exe compilado: relança o próprio executável diretamente
            popen([executable])
        else:
            # Modo dev (.py): abre novo PowerShell com venv ativado
            path = self._path_mod
            if path is None:
                import os.path as path
            _root = path.dirname(main_path)
            _venv_activate = path.join(_root, ".venv", "Scripts", "Activate.ps1")
            _main = path.join(_root, "main.py")
            _ps_cmd = (
                f"Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force; "
                f"& '{_venv_activate}'; "
                f"Clear-Host; "
                f"Write-Host '  J.A.R.V.I.S. — iniciando...' -ForegroundColor Cyan; "
                f"& python '{_main}'"
            )
            popen(
                ["powershell", "-NoLogo", "-NoExit", "-Command", _ps_cmd],
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10),  # 0x10 no Windows
            )
