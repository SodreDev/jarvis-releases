"""Cartão F1-02: o gerador roda como processo do zero, como o dono vai rodar."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
FERRAMENTA = RAIZ / "tools" / "corpus_sintetico.py"


def gerador(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(FERRAMENTA), *argv],
        capture_output=True,
        text=True,
        check=False,
        cwd=RAIZ,
    )


def test_gera_e_depois_confere_a_regeneracao(tmp_path: Path) -> None:
    saida = tmp_path / "turnos"

    criacao = gerador(
        "--n", "6", "--gerador", "parametrico", "--semente", "11", "--saida", str(saida)
    )
    assert criacao.returncode == 0, criacao.stdout + criacao.stderr
    assert "sintetico: 6" in criacao.stdout
    assert "real: 0" in criacao.stdout

    conferencia = gerador("--verificar", "--gerador", "parametrico", "--saida", str(saida))

    assert conferencia.returncode == 0, conferencia.stdout
    assert "confere" in conferencia.stdout


def test_gerador_que_mudou_de_comportamento_e_acusado(tmp_path: Path) -> None:
    """`--verificar` não compara o arquivo no disco: regenera do rótulo e compara o sha256.

    É a diferença entre as duas conferências do corpus. `tools/corpus.py verificar` pega
    arquivo alterado; esta pega **gerador** que mudou — por isso o teste mexe no `sha256` do
    rótulo, que é o que o gerador teria produzido.
    """
    saida = tmp_path / "turnos"
    gerador("--n", "4", "--gerador", "parametrico", "--saida", str(saida))
    rotulos = saida / "rotulos.jsonl"
    linhas = rotulos.read_text(encoding="utf-8").splitlines()
    alvo = next(i for i, linha in enumerate(linhas) if '"id": "s-0002"' in linha)
    linhas[alvo] = re.sub(r'"sha256": "[0-9a-f]{64}"', f'"sha256": "{"0" * 64}"', linhas[alvo])
    rotulos.write_text("\n".join(linhas) + "\n", encoding="utf-8")

    conferencia = gerador("--verificar", "--gerador", "parametrico", "--saida", str(saida))

    assert conferencia.returncode == 1
    assert "s-0002" in conferencia.stdout
    assert "determinístico" in conferencia.stdout


def test_pedir_a_voz_piper_sem_o_modelo_explica_o_que_fazer(tmp_path: Path) -> None:
    """Sem o .onnx da voz, o gerador recusa com a URL — não gera áudio mudo e não inventa."""
    resultado = gerador(
        "--n",
        "2",
        "--gerador",
        "piper",
        "--voz-dir",
        str(tmp_path / "vazia"),
        "--saida",
        str(tmp_path / "turnos"),
    )

    assert resultado.returncode == 2
    assert "huggingface.co/rhasspy/piper-voices" in resultado.stdout
