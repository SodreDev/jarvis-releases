"""Perfis isolados de browser (Playwright `user_data_dir`)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from jarvis.config.paths import browser_profiles_dir

Profile = Literal["jarvis", "user"]


def profile_dir(profile: Profile, platform: str) -> Path:
    """`data/browser_profiles/<profile>/<platform>/`."""
    if profile not in ("jarvis", "user"):
        raise ValueError(f"perfil inválido: {profile!r}")
    safe_platform = "".join(c if c.isalnum() or c in "._-" else "_" for c in platform)
    if not safe_platform:
        raise ValueError("platform vazia")
    p = browser_profiles_dir() / profile / safe_platform
    p.mkdir(parents=True, exist_ok=True)
    return p


def ensure_profile(profile: Profile, platform: str) -> Path:
    """Cria (se não existir) e devolve o `user_data_dir`."""
    return profile_dir(profile, platform)


__all__ = ["Profile", "profile_dir", "ensure_profile"]
