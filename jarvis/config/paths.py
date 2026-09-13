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


def model_dir() -> "Path | None":
    """Diretório SIDECAR do modelo local externo (orquestrador customizado).

    Resolução (primeiro que existir vence): env `JARVIS_MODELO_DIR` →
    `config.MODELO_LOCAL_DIR` (settável pela UI) → pasta-padrão
    `project_root()/modelo_local`. Retorna `None` se nenhuma existir → o JARVIS
    degrada para o MiniLM/API. O modelo NUNCA vem do repo nem do `.exe`; checa só
    a EXISTÊNCIA da pasta (não abre nem inspeciona os pesos).
    """
    # 1. env JARVIS_MODELO_DIR (override de máquina / credentials/.env)
    env = os.environ.get("JARVIS_MODELO_DIR", "").strip()
    if env and Path(env).expanduser().is_dir():
        return Path(env).expanduser()
    # 2. config.MODELO_LOCAL_DIR (settável pela UI — aba 🧠 Cérebro)
    try:
        import config as _cfg
        cfg_dir = (getattr(_cfg, "MODELO_LOCAL_DIR", "") or "").strip()
        if cfg_dir and Path(cfg_dir).expanduser().is_dir():
            return Path(cfg_dir).expanduser()
    except Exception:
        pass
    # 3. pasta-padrão ao lado do exe (frozen) / na raiz do repo (dev)
    default = project_root() / "modelo_local"
    return default if default.is_dir() else None


__all__ = [
    "project_root",
    "user_config_dir",
    "user_config_file",
    "user_data_dir",
    "credentials_dir",
    "logs_dir",
    "browser_profiles_dir",
    "dev_config_override",
    "model_dir",
]
