"""Cartão F1-03, aceite (e): o harness publica piso, com etiqueta, e não mexe em docs/medicoes."""

from __future__ import annotations

import csv
from pathlib import Path

from tools.harness_audio_io import (
    ETIQUETA,
    Medicao,
    de_tempos,
    escrever_wav,
    main,
    medir_cancelamento,
    medir_captura,
    resumo_por_braco,
)

RAIZ = Path(__file__).resolve().parents[3]


def test_o_harness_roda_em_amostra_pequena_e_publica_onde_mandaram(tmp_path: Path) -> None:
    saida = tmp_path / "medicoes"

    assert (
        main(
            ["--quadros", "100", "--execucoes", "2", "--cancelamentos", "5", "--saida", str(saida)]
        )
        == 0
    )

    md = (saida / "f1-03-audio-io.md").read_text(encoding="utf-8")
    with (saida / "f1-03-audio-io.csv").open(encoding="utf-8") as arquivo:
        linhas = list(csv.DictReader(arquivo))

    assert ETIQUETA in md
    assert "jitter de captura" in md, "a lacuna de hardware tem de estar escrita no relatório"
    assert {linha["braco"] for linha in linhas} >= {"captura→AudioActivity", "Cancel→fila vazia"}
    assert {linha["execucao"] for linha in linhas} == {"1", "2"}


def test_o_harness_nao_escreve_na_medicao_publicada(tmp_path: Path) -> None:
    """A armadilha que a F0-04 pagou: teste que publica medição substitui a de verdade."""
    publicada = RAIZ / "docs" / "medicoes" / "f1-03-audio-io.md"
    antes = publicada.read_bytes() if publicada.exists() else None

    main(["--quadros", "60", "--execucoes", "1", "--cancelamentos", "3", "--saida", str(tmp_path)])

    depois = publicada.read_bytes() if publicada.exists() else None
    assert antes == depois


def test_o_caminho_com_evento_custa_mais_que_o_sem_evento(tmp_path: Path) -> None:
    """O gargalo é a fronteira (envelope + contrato), não a aritmética — como na F0-04."""
    alternado = tmp_path / "a.wav"
    silencio = tmp_path / "s.wav"
    escrever_wav(alternado, 200, alternado=True)
    escrever_wav(silencio, 200, alternado=False)

    com = medir_captura(alternado, 1, nome="com", observacao="")
    sem = medir_captura(silencio, 1, nome="sem", observacao="")

    assert com.n == sem.n == 200
    assert com.p50_ms > sem.p50_ms


def test_o_erro_de_played_ms_medido_e_zero() -> None:
    """Se isto deixar de ser zero, `played_ms` parou de vir das amostras consumidas."""
    _, erro = medir_cancelamento(1, 20)

    assert erro.max_ms == 0.0


def test_resumo_usa_mediana_entre_execucoes() -> None:
    medicao = Medicao(quadros=10, execucoes=3)
    for execucao, valor in enumerate([1.0, 5.0, 3.0], start=1):
        medicao.resultados.append(de_tempos("x", execucao, [valor]))

    assert resumo_por_braco(medicao)["x"]["p50"] == 3.0
    assert resumo_por_braco(medicao)["x"]["max"] == 5.0
