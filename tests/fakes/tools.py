"""Ferramentas de linha de comando falsas (`wpctl`, `pactl`, `wl-paste`,
`xclip`, `playerctl`, ...) para os testes de F2-03/F2-04/F2-08, que fazem
`subprocess.run([<ferramenta>, ...])` em vez de falar direto com D-Bus.
Fixture `fake_tools` em `tests/conftest.py`.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path


def install_fake_tools(bin_dir: Path, calls_dir: Path, scripts: dict[str, str]) -> dict[str, Path]:
    """Cria um script executável por entrada de `scripts` (nome da
    ferramenta -> corpo do shell script, recebe `argv` como `"$@"`).
    Cada invocação é registrada, uma linha por chamada (args separados por
    espaço, como o shell os recebeu), no arquivo `<calls_dir>/<nome>.calls`.
    Devolve `{nome: caminho do .calls}` para o teste conferir depois.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    calls_dir.mkdir(parents=True, exist_ok=True)

    calls_paths: dict[str, Path] = {}
    for name, body in scripts.items():
        calls_path = calls_dir / f"{name}.calls"
        calls_paths[name] = calls_path

        script_path = bin_dir / name
        script_path.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$*" >> "{calls_path}"\n'
            f"{body}\n"
        )
        mode = script_path.stat().st_mode
        script_path.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    return calls_paths


def prepend_to_path(bin_dir: Path) -> str:
    """Novo valor de `PATH` com `bin_dir` na frente — para
    `monkeypatch.setenv("PATH", ...)`."""
    return f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
