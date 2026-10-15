"""Aceite do cartão F0-01: os portões recusam de verdade (não são enfeite de CI).

(b) o linter recusa um arquivo mal formatado proposital;
além disso, o linter recusa shell irrestrito — a proibição central da SPEC §4.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
CONFIG = RAIZ / "pyproject.toml"

MAL_FORMATADO = "import os,sys\ndef  f( a,b ):\n  return   { 'x':a,'y':b }\n"

COM_SHELL = (
    "from __future__ import annotations\n"
    "import subprocess\n\n\n"
    "def rodar(cmd: str) -> None:\n"
    "    subprocess.run(cmd, shell=True, check=False)\n"
)

PROCESSOS = ("audio_io", "agentd", "s2", "policy", "executor", "memoryd", "ui")


def ruff(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ruff", *argv, "--no-cache", "--config", str(CONFIG)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_formatador_recusa_arquivo_mal_formatado(tmp_path: Path) -> None:
    alvo = tmp_path / "feio.py"
    alvo.write_text(MAL_FORMATADO, encoding="utf-8")

    resultado = ruff("format", "--check", str(alvo))

    assert resultado.returncode != 0, resultado.stdout + resultado.stderr


def test_linter_recusa_arquivo_mal_formatado(tmp_path: Path) -> None:
    alvo = tmp_path / "feio.py"
    alvo.write_text(MAL_FORMATADO, encoding="utf-8")

    resultado = ruff("check", str(alvo))

    assert resultado.returncode != 0, resultado.stdout + resultado.stderr


def test_linter_recusa_shell_irrestrito(tmp_path: Path) -> None:
    """SPEC §4 e CONTRIBUTING 6: não existe caminho de shell no código de produção."""
    alvo = tmp_path / "com_shell.py"
    alvo.write_text(COM_SHELL, encoding="utf-8")

    resultado = ruff("check", str(alvo))

    assert resultado.returncode != 0, resultado.stdout + resultado.stderr
    assert "S602" in resultado.stdout or "S604" in resultado.stdout, resultado.stdout


def test_formatador_aceita_arquivo_bem_formatado(tmp_path: Path) -> None:
    alvo = tmp_path / "bonito.py"
    alvo.write_text('"""Doc."""\n\nX: int = 1\n', encoding="utf-8")

    resultado = ruff("format", "--check", str(alvo))

    assert resultado.returncode == 0, resultado.stdout + resultado.stderr


@pytest.mark.parametrize("processo", PROCESSOS)
def test_cada_processo_e_um_pacote_importavel(processo: str) -> None:
    """Os sete processos da SPEC §2 existem como pacote desde o primeiro commit."""
    modulo = importlib.import_module(f"jarvis.{processo}")

    assert modulo.__doc__ is not None, f"jarvis.{processo} sem responsabilidade documentada"
