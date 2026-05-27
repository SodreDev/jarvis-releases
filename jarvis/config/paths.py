"""Paths canônicos do JARVIS.

Usa APPDATA no Windows e XDG_CONFIG_HOME no Linux/macOS. Tudo relativo;
nenhum caminho `C:\\Users\\…` hardcoded.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _appdata_root() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "JARVIS"
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "jarvis"


def project_root() -> Path:
    """Raiz do projeto (gravável).

    - **Frozen (PyInstaller)**: pasta onde está o `.exe` (`dist/JARVIS/`).
      Não usa `_MEIPASS` (read-only); usa `dirname(sys.executable)` para
      manter `data/`, `credentials/`, `logs/` ao lado do binário.
    - **Dev**: 2 níveis acima deste arquivo (`<repo>/jarvis/config/paths.py`
      → `<repo>/`).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def user_config_dir() -> Path:
    p = _appdata_root()
    p.mkdir(parents=True, exist_ok=True)
    return p


def user_config_file() -> Path:
    return user_config_dir() / "config.user.toml"


def user_data_dir() -> Path:
    p = _appdata_root() / "data"
    p.mkdir(parents=True, exist_ok=True)
    return p


def credentials_dir() -> Path:
    p = _appdata_root() / "credentials"
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = _appdata_root() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def browser_profiles_dir() -> Path:
    """Raiz dos `user_data_dir` do Playwright (1 pasta por perfil/plataforma)."""
    p = project_root() / "data" / "browser_profiles"
    p.mkdir(parents=True, exist_ok=True)
    return p


def dev_config_override() -> Path:
    """`./config.user.toml` na raiz do repo — override de desenvolvimento."""
    return project_root() / "config.user.toml"


__all__ = [
    "project_root",
    "user_config_dir",
    "user_config_file",
    "user_data_dir",
    "credentials_dir",
    "logs_dir",
    "browser_profiles_dir",
    "dev_config_override",
]
