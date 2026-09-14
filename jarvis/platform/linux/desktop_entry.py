"""Arquivo .desktop do Jarvis para o portal reconhecer o app (F2-01, D-F2-3).

``ensure_desktop_entry()`` grava ``$XDG_DATA_HOME/applications/<APP_ID>.desktop``
(padrão ``~/.local/share``) com ``NoDisplay=true``, ``Exec=<python> <main.py>`` e
``Icon=``. Idempotente: só escreve se o arquivo não existe ou se o ``Exec`` mudou.
No AppImage quem cuida é o AppRun (Fase 5), então aqui não grava nada.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping, Optional

from .app_id import APP_ID, APP_NAME

_ESPECIAIS = set(' \t\n"\'\\><~|&;$*?#()`')


def _citar(argumento: str) -> str:
    """Aspas no formato da Desktop Entry Specification quando preciso."""
    if argumento and not (set(argumento) & _ESPECIAIS):
        return argumento
    escapado = "".join("\\" + c if c in '"`$\\' else c for c in argumento)
    return f'"{escapado}"'


def _main_path() -> str:
    principal = sys.modules.get("__main__")
    arquivo = getattr(principal, "__file__", None) or (sys.argv[0] if sys.argv else "main.py")
    return os.path.abspath(arquivo)


def desktop_entry_path(app_id: str = APP_ID, environ: Optional[Mapping[str, str]] = None) -> Path:
    env = os.environ if environ is None else environ
    base = env.get("XDG_DATA_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".local", "share")
    return Path(base) / "applications" / f"{app_id}.desktop"


def ensure_desktop_entry(
    app_id: str = APP_ID,
    *,
    main_path: Optional[str] = None,
    executable: Optional[str] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> Optional[Path]:
    """Garante o .desktop do usuário. Devolve o caminho, ou None (AppImage/erro)."""
    env = os.environ if environ is None else environ
    if env.get("APPIMAGE"):
        return None
    exec_linha = f"{_citar(executable or sys.executable)} {_citar(main_path or _main_path())}"
    caminho = desktop_entry_path(app_id, env)
    try:
        if caminho.exists() and f"Exec={exec_linha}" in caminho.read_text(encoding="utf-8").splitlines():
            return caminho
        caminho.parent.mkdir(parents=True, exist_ok=True)
        conteudo = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_NAME}\n"
            f"Exec={exec_linha}\n"
            "Icon=\n"
            "Terminal=false\n"
            "NoDisplay=true\n"
        )
        temporario = caminho.with_suffix(".desktop.tmp")
        temporario.write_text(conteudo, encoding="utf-8")
        os.replace(temporario, caminho)
    except OSError as e:
        print(f"[HOTKEYS] não consegui gravar {caminho}: {e}")
        return None
    return caminho
