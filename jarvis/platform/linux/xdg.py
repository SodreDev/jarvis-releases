"""Backend de paths XDG (Linux).

Segue a XDG Base Directory Specification: config em $XDG_CONFIG_HOME, dados em
$XDG_DATA_HOME, estado/logs em $XDG_STATE_HOME, cache em $XDG_CACHE_HOME —
tudo sob a subpasta minúscula "jarvis". Variável vazia ou RELATIVA é ignorada
(vale o padrão ~/.config, ~/.local/share, ~/.local/state, ~/.cache). Os níveis
"jarvis/..." criados ganham modo 0700; as pastas-base XDG não são alteradas.
"""
from __future__ import annotations

import os
from pathlib import Path

from ..common.base import BackendBase


class XdgPaths(BackendBase):
    name = "linux.xdg"

    def __init__(self, ctx=None, *, environ=None, home=None):
        self.ctx = ctx
        self._environ = environ if environ is not None else os.environ
        self._home = Path(home) if home is not None else None

    # ── bases XDG ────────────────────────────────────────────────────────────
    def _home_dir(self) -> Path:
        return self._home if self._home is not None else Path.home()

    def _xdg(self, var: str, *default_parts: str) -> Path:
        val = self._environ.get(var, "")
        if val:
            p = Path(val)
            if p.is_absolute():  # relativa é ignorada (regra XDG)
                return p
        return self._home_dir().joinpath(*default_parts)

    def _config_base(self) -> Path:
        return self._xdg("XDG_CONFIG_HOME", ".config")

    def _data_base(self) -> Path:
        return self._xdg("XDG_DATA_HOME", ".local", "share")

    def _state_base(self) -> Path:
        return self._xdg("XDG_STATE_HOME", ".local", "state")

    def _cache_base(self) -> Path:
        return self._xdg("XDG_CACHE_HOME", ".cache")

    @staticmethod
    def _ensure(p: Path) -> Path:
        p.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(p, 0o700)  # só os níveis jarvis/... que criamos
        except OSError:
            pass
        return p

    # ── API Paths ────────────────────────────────────────────────────────────
    def user_config_dir(self) -> Path:
        return self._ensure(self._config_base() / "jarvis")

    def user_data_dir(self) -> Path:
        return self._ensure(self._data_base() / "jarvis")

    def credentials_dir(self) -> Path:
        self._ensure(self._config_base() / "jarvis")
        return self._ensure(self._config_base() / "jarvis" / "credentials")

    def logs_dir(self) -> Path:
        self._ensure(self._state_base() / "jarvis")
        return self._ensure(self._state_base() / "jarvis" / "logs")

    def cache_dir(self) -> Path:
        return self._ensure(self._cache_base() / "jarvis")

    def webview_storage_dir(self) -> Path:
        self._ensure(self._data_base() / "jarvis")
        return self._ensure(self._data_base() / "jarvis" / "webview_data")
