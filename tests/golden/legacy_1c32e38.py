"""Oráculo golden: cópia LITERAL de trechos do commit `1c32e38` (baseline
2.7.0, antes do port Linux), embrulhada em funções que recebem `environ`/
`home` injetados em vez de ler `os.environ`/`Path.home()` direto.

NUNCA editar este arquivo fora de uma emenda do arquiteto (ver
docs/linux-port/FILA-fase1-executor.md, linha 12) — é o oráculo contra o
qual os testes C/K de F1-02, F1-03 e F1-07 comparam o comportamento novo.

Fontes:
- `git show 1c32e38:jarvis/config/paths.py` — `_appdata_root()` e as
  funções públicas `user_config_dir`, `user_data_dir`, `credentials_dir`,
  `logs_dir` (idênticas em HEAD; nada mudou até aqui).
- `git show 1c32e38:main.py`, âncoras `_wv_storage = os.path.join(`
  (`:2622`) e `_wv_data = os.path.join(` (`:13519`) — as duas expressões
  são literalmente iguais.
"""
from __future__ import annotations

import ntpath
from pathlib import Path


def legacy_appdata_root(environ: dict, home: str) -> Path:
    """`_appdata_root()` em 1c32e38, ramo `os.name == "nt"`.

    `os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")`
    — `or` trata APPDATA ausente OU vazio como "usar o padrão".
    """
    base = environ.get("APPDATA") or str(Path(home) / "AppData" / "Roaming")
    return Path(base) / "JARVIS"


def legacy_user_config_dir(environ: dict, home: str) -> Path:
    return legacy_appdata_root(environ, home)


def legacy_user_data_dir(environ: dict, home: str) -> Path:
    return legacy_appdata_root(environ, home) / "data"


def legacy_credentials_dir(environ: dict, home: str) -> Path:
    return legacy_appdata_root(environ, home) / "credentials"


def legacy_logs_dir(environ: dict, home: str) -> Path:
    return legacy_appdata_root(environ, home) / "logs"


def legacy_webview_storage(environ: dict, home: str) -> str:
    """`_wv_storage` (`main.py:2622`) e `_wv_data` (`main.py:13519`) em
    1c32e38 — as duas expressões são idênticas:

    `os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
    "JARVIS", "webview_data")`

    Usa `.get(chave, padrão)` de 2 argumentos: só cai no padrão (`home`)
    se a chave estiver AUSENTE — APPDATA vazio ("") permanece vazio. Essa
    semântica é diferente da de `legacy_appdata_root` (que usa `or`) e as
    duas devem ser preservadas separadamente (ver SPEC F1-02).

    `ntpath` em vez de `os.path`/`pathlib` porque, no Windows real,
    `os.path is ntpath` — reproduzimos isso explicitamente para o teste
    rodar de forma determinística também em host Linux.
    """
    return ntpath.join(environ.get("APPDATA", home), "JARVIS", "webview_data")


def legacy_refresh_path(environ: dict, winreg_mod) -> set[str]:
    """`main.py:113-129` em 1c32e38, âncora `if sys.platform == "win32":` /
    `import winreg` / `_ler_path_windows()`.

    Difere do original só em expor o CONJUNTO de entradas resultante (sem
    vazias) em vez de escrever a string final em `os.environ["PATH"]`
    (efeito colateral que não cabe num oráculo puro).
    """
    caminhos = set(environ.get("PATH", "").split(";"))
    for hive, scope in [
        (winreg_mod.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg_mod.HKEY_CURRENT_USER, r"Environment"),
    ]:
        try:
            with winreg_mod.OpenKey(hive, scope) as k:
                val, _ = winreg_mod.QueryValueEx(k, "Path")
                caminhos.update(val.split(";"))
        except Exception:
            pass
    return set(filter(None, caminhos))


def legacy_job_object(ct, wt):
    """Bloco `if _sys_crash.platform == "win32":` de `main.py`, perto de
    `main.py:13412-13493` em 1c32e38 (Job Object KILL_ON_JOB_CLOSE |
    BREAKAWAY_OK). `ct` substitui `ctypes` (`WinDLL`/`sizeof`/`byref`/
    `Structure`/`get_last_error`) e `wt` substitui `ctypes.wintypes` —
    únicas trocas em relação ao bloco original; sem outra mudança de lógica.
    """
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


__all__ = [
    "legacy_appdata_root",
    "legacy_user_config_dir",
    "legacy_user_data_dir",
    "legacy_credentials_dir",
    "legacy_logs_dir",
    "legacy_webview_storage",
    "legacy_refresh_path",
    "legacy_job_object",
]
