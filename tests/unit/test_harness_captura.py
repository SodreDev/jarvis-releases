"""Partes verificáveis do harness de captura (cartão F0-04).

O harness mede; estes testes provam que a medição é **justa**: o braço Rust e o braço Python
decidem a mesma coisa sobre o mesmo áudio, o gerador é determinístico e o percentil é o que
diz ser. Sem isso, comparar linguagens não significaria nada.

Os braços de medição vivem no grupo `medicao` (numpy, onnxruntime), que **não** é instalado
no CI: os testes que precisam deles são pulados, e isso fica dito no relatório.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from tools.harness_captura import (
    FRAME,
    TAXA,
    Medicao,
    Resultado,
    compilar_rust,
    gerar_audio,
    percentil,
    resumo_por_braco,
)

RAIZ = Path(__file__).resolve().parents[2]


def test_percentil_bate_com_a_definicao() -> None:
    """Posto mais próximo (nearest-rank), que é o que o relatório diz publicar."""
    valores = [float(i) for i in range(101)]  # 0..100

    assert percentil(valores, 0) == 0.0
    assert percentil(valores, 50) == 50.0
    assert percentil(valores, 95) == 95.0
    assert percentil(valores, 100) == 100.0
    assert percentil([], 95) == 0.0
    assert percentil([7.0], 95) == 7.0
    desordenado = [3.0, 1.0, 2.0]
    assert percentil(desordenado, 50) == 2.0  # ordena antes de cortar


def test_gerador_de_audio_e_deterministico(tmp_path: Path) -> None:
    """Os braços só são comparáveis se lerem exatamente o mesmo áudio."""
    um = tmp_path / "a.raw"
    outro = tmp_path / "b.raw"

    frames_um = gerar_audio(um, 2.0)
    frames_outro = gerar_audio(outro, 2.0)

    assert frames_um == frames_outro == int(2.0 * TAXA) // FRAME
    assert um.read_bytes() == outro.read_bytes()


def test_audio_gerado_tem_fala_e_silencio(tmp_path: Path) -> None:
    """Se o sinal fosse só silêncio, o VAD nunca ligaria e a medição seria vazia."""
    numpy = pytest.importorskip("numpy", reason="grupo `medicao` não instalado")
    caminho = tmp_path / "a.raw"
    gerar_audio(caminho, 3.0)

    amostras = numpy.frombuffer(caminho.read_bytes(), dtype="<i2").astype(numpy.float32) / 32768
    janelas = amostras[: len(amostras) // FRAME * FRAME].reshape(-1, FRAME)
    rms = numpy.sqrt((janelas * janelas).mean(axis=1))

    assert rms.max() > 0.05, "nenhum trecho com energia de fala"
    assert rms.min() < 0.005, "nenhum trecho de silêncio"


def test_resumo_por_braco_usa_a_mediana_das_execucoes() -> None:
    medicao = Medicao(
        resultados=[
            Resultado("x", 1, 10, 1, 1.0, 1.0, 2.0, 3.0, 9.0),
            Resultado("x", 2, 10, 1, 1.0, 3.0, 4.0, 5.0, 7.0),
            Resultado("x", 3, 10, 1, 1.0, 2.0, 3.0, 4.0, 8.0),
        ]
    )

    resumo = resumo_por_braco(medicao)

    assert resumo["x"]["p50"] == 2.0
    assert resumo["x"]["p95"] == 3.0
    assert resumo["x"]["max"] == 9.0
    assert resumo["x"]["n"] == 30


@pytest.mark.skipif(shutil.which("rustc") is None, reason="rustc não está nesta máquina")
def test_braco_rust_compila_e_decide_igual_ao_python(tmp_path: Path) -> None:
    """A comparação de linguagens só vale se as duas implementações concordarem.

    Mesmo áudio, mesmos limiares, mesma histerese: a contagem de eventos tem de ser igual.
    """
    pytest.importorskip("numpy", reason="grupo `medicao` não instalado")
    from tools.harness_captura import carregar, medir_python_numpy

    audio = tmp_path / "a.raw"
    frames = gerar_audio(audio, 20.0)

    binario, versao = compilar_rust(tmp_path / "vad_bench")
    assert binario is not None, versao

    saida = subprocess.run(
        [str(binario), str(audio), str(frames), "1"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    do_rust = json.loads(saida.strip().splitlines()[-1])
    do_python = medir_python_numpy(carregar(audio), frames, 1)

    assert do_rust["n"] == do_python.n == frames
    assert do_rust["eventos"] == do_python.eventos, (
        f"Rust achou {do_rust['eventos']} eventos e Python {do_python.eventos}: "
        "os braços divergiram e a comparação não serve"
    )
    assert do_rust["eventos"] > 0


@pytest.mark.skipif(shutil.which("rustc") is None, reason="rustc não está nesta máquina")
def test_fonte_rust_nao_tem_dependencia_externa() -> None:
    """Exigência do dono: nada instalado. O braço Rust compila com `rustc`, sem cargo."""
    fonte = (RAIZ / "medicao" / "vad_bench.rs").read_text(encoding="utf-8")

    assert "extern crate" not in fonte
    for linha in fonte.splitlines():
        if linha.startswith("use "):
            assert linha.startswith("use std::"), f"dependência externa: {linha}"
    assert not (RAIZ / "medicao" / "Cargo.toml").exists()


def test_observador_de_gc_mede_as_pausas() -> None:
    import gc

    from tools.harness_captura import ObservadorDeGc

    with ObservadorDeGc() as observador:
        lixo = [[object() for _ in range(100)] for _ in range(50)]
        del lixo
        gc.collect()

    assert observador.pausas, "nenhuma pausa de GC observada mesmo com coleta forçada"
    assert observador.total_ms >= 0.0


def test_harness_roda_de_ponta_a_ponta_em_amostra_pequena(tmp_path: Path) -> None:
    """Fumaça: o harness inteiro roda, publica CSV e declara as lacunas (sem o modelo ONNX)."""
    pytest.importorskip("numpy", reason="grupo `medicao` não instalado")
    concluido = subprocess.run(
        [
            sys.executable,
            str(RAIZ / "tools" / "harness_captura.py"),
            "--frames",
            "200",
            "--execucoes",
            "1",
            "--segundos-piso",
            "0.5",
            "--trabalho",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=RAIZ,
    )

    assert concluido.returncode == 0, concluido.stdout + concluido.stderr
    assert "não medido: braço `python-onnx`" in concluido.stdout
    assert (RAIZ / "docs" / "medicoes" / "f0-04-captura.csv").exists()
