"""Nenhum teste unitário lê nem escreve na configuração real do dono.

`presets.toml`, `jarvis-voz.toml` e afins moram em `~/.config/jarvis`; sem isolamento, um dono
com o Groq ligado fazia falhar testes que esperam o padrão (motor «eco», modo texto). Aqui o
HOME e as pastas XDG apontam para um diretório temporário vazio em todo teste.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_XDG = {
    "XDG_CONFIG_HOME": "config",
    "XDG_DATA_HOME": "data",
    "XDG_CACHE_HOME": "cache",
    "XDG_STATE_HOME": "state",
}


@pytest.fixture(autouse=True)
def ambiente_do_dono_isolado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    casa = tmp_path / "home-isolada"
    casa.mkdir()
    monkeypatch.setenv("HOME", str(casa))
    for variavel, pasta in _XDG.items():
        monkeypatch.setenv(variavel, str(casa / pasta))
    return casa
