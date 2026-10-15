"""Cartão F1-06, aceites (a) e (b): o harness publica WER com a ressalva e o SLO-3 definido."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from tools.harness_asr import amostra_equilibrada, main, resumo, rodar_item

from jarvis.corpus.sintetico import gerar_corpus
from jarvis.corpus.voz import VozParametrica

RAIZ = Path(__file__).resolve().parents[3]


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    gerar_corpus(
        8, semente=77, pasta=tmp_path, voz=VozParametrica(), fracao_ruido=0.0, fracao_eco=0.0
    )
    return tmp_path


def test_o_harness_publica_wer_slo3_e_a_ressalva(corpus: Path, tmp_path: Path) -> None:
    saida = tmp_path / "medicoes"

    codigo = main(
        ["--corpus", str(corpus), "--itens", "4", "--motores", "oraculo", "--saida", str(saida)]
    )

    assert codigo == 0
    md = (saida / "f1-06-asr.md").read_text(encoding="utf-8")
    with (saida / "f1-06-asr.csv").open(encoding="utf-8") as arquivo:
        linhas = list(csv.DictReader(arquivo))

    assert len(linhas) == 4
    assert "TTS sintético, material fácil" in md, "a ressalva do aceite (a) é obrigatória"
    assert "WER na voz do dono" in md
    assert "parakeet-tdt-0.6b-v3" in md, "o que não foi executado tem de estar escrito"
    assert all(float(linha["wer"]) == 0.0 for linha in linhas), "o oráculo acerta por construção"


def test_a_amostra_e_equilibrada_entre_as_duas_classes(corpus: Path) -> None:
    from jarvis.corpus.rotulos import ler_rotulos

    rotulos = [r for r in ler_rotulos(corpus / "rotulos.jsonl") if r.split == "calibracao"]

    escolhidos = amostra_equilibrada(rotulos, 4)

    assert len(escolhidos) == 4
    assert sum(1 for r in escolhidos if r.fim_de_turno) == 2


def test_o_resumo_separa_por_implementacao_e_guarda_modelo_e_licenca(corpus: Path) -> None:
    from tools.harness_asr import Medicao, ler_wav

    from jarvis.corpus.rotulos import ler_rotulos

    rotulo = next(r for r in ler_rotulos(corpus / "rotulos.jsonl"))
    medicao = Medicao(itens=1)
    medicao.resultados.append(rodar_item(rotulo, ler_wav(corpus / rotulo.arquivo), "oraculo"))

    tabela = resumo(medicao)

    assert len(tabela) == 1
    (valores,) = tabela.values()
    assert valores["licenca"] == "não se aplica (texto do próprio corpus)"
    assert valores["modelo"] == "(nenhum)"
    assert float(valores["rtf_parede_p50"]) >= 0.0


def test_o_harness_nao_escreve_na_medicao_publicada(corpus: Path, tmp_path: Path) -> None:
    publicada = RAIZ / "docs" / "medicoes" / "f1-06-asr.md"
    antes = publicada.read_bytes() if publicada.exists() else None

    main(
        ["--corpus", str(corpus), "--itens", "2", "--motores", "oraculo", "--saida", str(tmp_path)]
    )

    assert (publicada.read_bytes() if publicada.exists() else None) == antes
