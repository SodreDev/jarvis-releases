"""Ambiente do Windows: completa o PATH lendo o registro (ffplay via winget).

`refresh_path_from_registry` é a cópia literal de `_ler_path_windows` do main.py
de 1c32e38: mesmo set inicial, mesmo laço com HKLM/HKCU, try/except e
`";".join(filter(None, caminhos))` gravado em environ["PATH"]. winreg é lazy
(só no Windows) e injetável para teste; devolve o conjunto final (sem vazias).
"""
from __future__ import annotations

import os


def refresh_path_from_registry(environ=None, winreg_mod=None):
    if environ is None:
        environ = os.environ
    if winreg_mod is None:
        import winreg as winreg_mod

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
    environ["PATH"] = ";".join(filter(None, caminhos))
    return set(filter(None, caminhos))
