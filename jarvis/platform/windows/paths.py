"""Backend de paths do Windows (W1 — expressões literais de 1c32e38).

Raiz em %APPDATA%/JARVIS (com o mesmo `or` do paths.py legado); cache em
%LOCALAPPDATA%. webview_storage_dir usa `os.path.join` + `.get` de 2 argumentos
(APPDATA vazio continua vazio), preservando a semântica do main.py.
"""
from __future__ import annotations

import os
from pathlib import Path

from ..common.base import BackendBase


class WindowsPaths(BackendBase):
    name = "windows.appdata"

    def __init__(self, ctx=None, *, environ=None, home=None, path_module=None):
        self.ctx = ctx
        self._environ = environ if environ is not None else os.environ
        self._home = home
        self._path = path_module if path_module is not None else os.path

    # ── helpers ──────────────────────────────────────────────────────────────
    def _home_dir(self) -> Path:
        return Path(self._home) if self._home is not None else Path.home()

    def _root(self) -> Path:
        # `or`: APPDATA ausente OU vazio cai no padrão (igual ao paths.py legado).
        base = self._environ.get("APPDATA") or str(self._home_dir() / "AppData" / "Roaming")
        return Path(base) / "JARVIS"

    @staticmethod
    def _ensure(p: Path) -> Path:
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ── API Paths ────────────────────────────────────────────────────────────
    def user_config_dir(self) -> Path:
        return self._ensure(self._root())

    def user_data_dir(self) -> Path:
        return self._ensure(self._root() / "data")

    def credentials_dir(self) -> Path:
        return self._ensure(self._root() / "credentials")

    def logs_dir(self) -> Path:
        return self._ensure(self._root() / "logs")

    def cache_dir(self) -> Path:
        base = self._environ.get("LOCALAPPDATA") or str(self._home_dir() / "AppData" / "Local")
        return self._ensure(Path(base) / "JARVIS" / "cache")

    def webview_storage_dir(self) -> str:
        # `.get` de 2 argumentos: só cai no padrão se a chave estiver AUSENTE.
        default_home = self._home if self._home is not None else self._path.expanduser("~")
        return self._path.join(
            self._environ.get("APPDATA", default_home), "JARVIS", "webview_data"
        )
