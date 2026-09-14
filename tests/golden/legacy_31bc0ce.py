"""Oráculo golden: cópias LITERAIS de trechos do commit `31bc0ce` (fim da
fase 1 — base da fase 2, ver docs/linux-port/FILA-fase2-executor.md),
embrulhadas em funções que recebem fakes/parâmetros injetados em vez de
ler `os.environ`, `ctypes.windll` ou chamar as APIs do SO direto.

NUNCA editar este arquivo fora de uma emenda do arquiteto (mesma regra da
fase 1, FILA §Protocolo item 5: "tests/golden/ ... são do qa" e o
executor não edita). É o oráculo contra o qual os testes C/K de
F2-01 (hotkeys), F2-02 (tray), F2-03 (volume), F2-04 (clipboard),
F2-06 (open_path), F2-07 (session), F2-08 (media) e F2-09 (restart_self)
comparam o comportamento novo — cada função entra sob demanda, na tarefa
G-A/G-B/G-C correspondente (ver FILA), sempre ANTES do executor mexer no
código de produção daquela capacidade.

Preenchido incrementalmente, tarefa G-A da FILA (F2-06 open_path,
F2-09 restart_self, F2-07 session e F2-04 clipboard) — cada função cita
a âncora exata em `main.py`/`comandos/*.py`/`core/win_locale.py` de onde
o trecho foi copiado (linha e nome), igual a `legacy_1c32e38.py` da
fase 1.
"""
from __future__ import annotations


# ── F2-06: open_path — main.py:8970/8991 (_os.startfile) e :2928 (notepad) ──

# (arquivo, linha, expressão-fonte do argumento) em 31bc0ce — usado pelo
# AST de tests/golden/test_startfile_callsites.py para conferir que cada
# call site continua passando A MESMA expressão de argumento, seja para
# `os.startfile`/`_os.startfile` (hoje) ou para `_open_path` (depois de
# F2-06).
OPEN_PATH_CALL_SITES: list[tuple[str, int, str]] = [
    ("main.py", 8970, "path"),
    ("main.py", 8991, "caminho"),
    ("comandos/executor.py", 27, "url"),
    ("comandos/games_ctrl.py", 27, "target"),
    ("comandos/msg_sender.py", 432, "uri"),
    ("comandos/msg_sender.py", 526, "uri"),
    ("comandos/msg_sender.py", 578, '"discord://"'),
    ("comandos/msg_sender.py", 709, '"whatsapp://"'),
    ("comandos/janela_ctrl.py", 248, "uri"),
    ("comandos/janela_ctrl.py", 260, "cmd"),
    ("comandos/janela_ctrl.py", 640, "caminho"),
    ("comandos/tool_registry.py", 1761, "caminho"),
    ("comandos/tool_registry.py", 2089, "path"),
    ("comandos/tool_registry.py", 2199, "path"),
    ("comandos/tool_registry.py", 2355, "path"),
    ("comandos/tool_registry.py", 2389, "pdf"),
    ("comandos/tool_registry.py", 2445, "path"),
]

# main.py:2928 — `subprocess.Popen(["notepad.exe", path], close_fds=True)`
NOTEPAD_CALL_SITE_LINE = 2928
NOTEPAD_CALL_SITE_ARGS = ['"notepad.exe"', "path"]  # expressões-fonte exatas


def legacy_open_path_windows(startfile_fn, target):
    """`_os.startfile(X)` em `main.py:8970`/`:8991` — chamada única,
    devolve o que `startfile_fn` devolver e propaga exceção (os call
    sites já tratam com `try/except`)."""
    return startfile_fn(target)


def legacy_open_text_file_windows(popen_fn, path):
    """`main.py:2928` — `subprocess.Popen(["notepad.exe", path],
    close_fds=True)`, literal."""
    return popen_fn(["notepad.exe", path], close_fds=True)


# ── F2-09: restart_self — main.py:6461-6491 (_fazer_restart) ──


def legacy_fazer_restart(*, frozen: bool, sys_executable: str, root: str, popen_fn):
    """Corpo de `_fazer_restart` (`main.py:6461-6489`), sem o
    `time.sleep(1.2)`/`self._window.destroy()`/`os._exit(0)` (efeitos
    colaterais que não cabem num oráculo puro — só a decisão de comando).
    Devolve `(args, kwargs)` passados a `popen_fn`.
    """
    if frozen:
        return popen_fn([sys_executable])

    import ntpath  # não os.path: em host Linux junta com "/", main.py roda no Windows

    venv_activate = ntpath.join(root, ".venv", "Scripts", "Activate.ps1")
    main_path = ntpath.join(root, "main.py")
    ps_cmd = (
        f"Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force; "
        f"& '{venv_activate}'; "
        f"Clear-Host; "
        f"Write-Host '  J.A.R.V.I.S. — iniciando...' -ForegroundColor Cyan; "
        f"& python '{main_path}'"
    )
    return popen_fn(
        ["powershell", "-NoLogo", "-NoExit", "-Command", ps_cmd],
        creationflags=0x10,  # subprocess.CREATE_NEW_CONSOLE
    )


# ── F2-07: session — main.py:7206 (_idle_seconds) e core/win_locale.py ──


def legacy_idle_seconds(ctypes_mod) -> float:
    """`main.py:7206-7224` (`_idle_seconds`), literal — usa
    `ctypes.windll` (compartilhado, não o WinDLL privado da F1-12) e
    devolve `0.0` em qualquer exceção."""
    try:
        class _LASTINPUTINFO(ctypes_mod.Structure):
            _fields_ = [("cbSize", ctypes_mod.c_uint), ("dwTime", ctypes_mod.c_uint)]

        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes_mod.sizeof(lii)
        ctypes_mod.windll.user32.GetLastInputInfo(ctypes_mod.byref(lii))
        millis = ctypes_mod.windll.kernel32.GetTickCount() - lii.dwTime
        return max(0.0, millis / 1000.0)
    except Exception:
        return 0.0


_WIN_TZ_TO_IANA = {
    "E. South America Standard Time": "America/Sao_Paulo",
    "UTC": "UTC",
}  # subconjunto de core/win_locale.py:_WIN_TZ_TO_IANA — só o que os testes usam


def legacy_get_timezone_name(winreg_mod, tzname: tuple[str, str]) -> str:
    """`core/win_locale.py:get_timezone_name`/`_read_winreg_tz_name`,
    literal: winreg → mapa IANA; se não achar, `time.tzname[0]`; se nada,
    `"UTC"`."""
    win_name = None
    try:
        key = winreg_mod.OpenKey(
            winreg_mod.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation",
        )
        try:
            val, _ = winreg_mod.QueryValueEx(key, "TimeZoneKeyName")
            win_name = val.strip()
        finally:
            winreg_mod.CloseKey(key)
    except Exception:
        win_name = None

    if win_name and win_name in _WIN_TZ_TO_IANA:
        return _WIN_TZ_TO_IANA[win_name]
    try:
        return tzname[0]
    except Exception:
        return "UTC"


def legacy_get_locale(getdefaultlocale_fn) -> str:
    """`core/win_locale.py:get_locale`, literal: `locale.getdefaultlocale()`
    → `"pt_BR"` vira `"pt-BR"`; qualquer falha → `"pt-BR"`."""
    try:
        loc, _enc = getdefaultlocale_fn()
        if loc:
            return loc.replace("_", "-")
    except Exception:
        pass
    return "pt-BR"


# ── F2-04: clipboard — comandos/system_ctrl.py e clipboard_hist_ctrl.py ──


def legacy_get_clipboard(pyperclip_mod) -> str:
    """`comandos/system_ctrl.py:250-255` (`get_clipboard`), literal."""
    try:
        return pyperclip_mod.paste() or ""
    except Exception:
        return ""


def legacy_set_clipboard(pyperclip_mod, texto: str) -> str:
    """`comandos/system_ctrl.py:258-264` (`set_clipboard`), literal."""
    try:
        pyperclip_mod.copy(texto)
        return "Copiado para a área de transferência, Senhor."
    except Exception as e:
        return f"Não foi possível copiar: {e}"


CLIPBOARD_HISTORY_MAX = 50  # comandos/clipboard_hist_ctrl.py:_MAX


def legacy_monitor_loop_iteration(get_clipboard_text_fn, history: list, last):
    """Um ciclo do corpo de `_monitor_loop` (`clipboard_hist_ctrl.py:76-89`),
    sem o `while`/`time.sleep(0.8)` (efeito colateral) — dedupe contra
    `last` E contra o topo de `history`, `strip() > 1` char, limite
    `CLIPBOARD_HISTORY_MAX`. Devolve o novo `last` (mutando `history` in
    place, como o original faz em `_history`)."""
    try:
        txt = get_clipboard_text_fn()
        if txt and txt != last and len(txt.strip()) > 1:
            last = txt
            if not history or history[-1] != txt:
                history.append(txt)
                if len(history) > CLIPBOARD_HISTORY_MAX:
                    history.pop(0)
    except Exception:
        pass
    return last


__all__ = [
    "OPEN_PATH_CALL_SITES",
    "NOTEPAD_CALL_SITE_LINE",
    "NOTEPAD_CALL_SITE_ARGS",
    "legacy_open_path_windows",
    "legacy_open_text_file_windows",
    "legacy_fazer_restart",
    "legacy_idle_seconds",
    "legacy_get_timezone_name",
    "legacy_get_locale",
    "legacy_get_clipboard",
    "legacy_set_clipboard",
    "CLIPBOARD_HISTORY_MAX",
    "legacy_monitor_loop_iteration",
]
