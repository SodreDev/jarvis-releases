"""Nenhum teste unitário lê nem escreve na configuração real do dono.

`presets.toml`, `jarvis-voz.toml` e afins moram em `~/.config/jarvis`; sem isolamento, um dono
com o Groq ligado fazia falhar testes que esperam o padrão (motor «eco», modo texto). Aqui o
HOME e as pastas XDG apontam para um diretório temporário vazio em todo teste.
"""

from __future__ import annotations

import os
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
    # fora do tmp_path: testes que listam o diretório do teste não podem ver a home isolada
    casa = tmp_path.parent / f"{tmp_path.name}-home"
    casa.mkdir()
    # o rustup/cargo moram no HOME real; preserva só as variáveis, antes de trocar o HOME
    real = Path(os.environ.get("HOME", "~")).expanduser()
    monkeypatch.setenv("RUSTUP_HOME", os.environ.get("RUSTUP_HOME") or str(real / ".rustup"))
    monkeypatch.setenv("CARGO_HOME", os.environ.get("CARGO_HOME") or str(real / ".cargo"))
    monkeypatch.setenv("HOME", str(casa))
    for variavel, pasta in _XDG.items():
        monkeypatch.setenv(variavel, str(casa / pasta))
    return casa
