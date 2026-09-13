"""Fixtures compartilhadas dos testes do Jarvis."""
import sys

import pytest


@pytest.fixture
def fake_platform(monkeypatch):
    """Simula sys.platform. Uso: fake_platform("win32") ou fake_platform("linux")."""

    def _set(platform_name: str):
        monkeypatch.setattr(sys, "platform", platform_name)
        return platform_name

    return _set


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """HOME e diretórios XDG apontando para uma pasta temporária, para nenhum
    teste ler ou escrever nos dados reais do usuário (config, cache, dados)."""
    home = tmp_path / "home"
    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    data_dir = tmp_path / "share"
    state_dir = tmp_path / "state"
    for d in (home, config_dir, cache_dir, data_dir, state_dir):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_dir))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_dir))

    return {
        "home": home,
        "config": config_dir,
        "cache": cache_dir,
        "data": data_dir,
        "state": state_dir,
    }
