"""Cartão F1-01, aceite (d): a ferramenta de replay acusa divergência pela linha de comando."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
FERRAMENTA = RAIZ / "tools" / "replay_audio.py"


def replay(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(FERRAMENTA), *argv],
        capture_output=True,
        text=True,
        check=False,
        cwd=RAIZ,
    )


def test_duas_execucoes_com_a_mesma_semente_dao_arquivos_identicos(tmp_path: Path) -> None:
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"

    assert replay("--sintetico", "--semente", "7", "--trilha", str(a)).returncode == 0
    assert replay("--sintetico", "--semente", "7", "--trilha", str(b)).returncode == 0

    assert a.read_bytes() == b.read_bytes()
    comparacao = replay("--trilha", str(a), "--comparar", str(b))
    assert comparacao.returncode == 0, comparacao.stdout
    assert "trilhas iguais" in comparacao.stdout


def test_trilhas_diferentes_saem_com_codigo_de_erro_e_o_primeiro_evento_que_diferiu(
    tmp_path: Path,
) -> None:
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    replay("--sintetico", "--semente", "7", "--trilha", str(a))
    replay("--sintetico", "--semente", "8", "--trilha", str(b))

    comparacao = replay("--trilha", str(a), "--comparar", str(b))

    assert comparacao.returncode == 1
    assert "DIVERGÊNCIA" in comparacao.stdout
    assert "evento " in comparacao.stdout


def test_sem_entrada_a_ferramenta_recusa_em_vez_de_inventar(tmp_path: Path) -> None:
    resultado = replay("--trilha", str(tmp_path / "x.jsonl"))

    assert resultado.returncode != 0
    assert "--wav" in resultado.stderr or "--sintetico" in resultado.stderr
