"""O corpus de endereçamento e a ferramenta que o mede (ADR-0029)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.medir_enderecamento import CORPUS, main

CAMPOS = {"id", "fala", "rotulo", "intencao", "jarvis_perguntou"}


def _corpus() -> list[dict[str, object]]:
    return [json.loads(linha) for linha in CORPUS.read_text("utf-8").splitlines() if linha.strip()]


def test_o_corpus_tem_as_duas_classes_e_ids_unicos() -> None:
    corpus = _corpus()
    assert all(set(linha) == CAMPOS for linha in corpus)
    assert len({linha["id"] for linha in corpus}) == len(corpus)
    assert {linha["rotulo"] for linha in corpus} == {"jarvis", "outro"}
    assert {linha["intencao"] for linha in corpus} == {"resposta", "sugestao", "acao", "ignorar"}
    assert all((linha["intencao"] == "ignorar") == (linha["rotulo"] == "outro") for linha in corpus)


def test_o_oraculo_acerta_tudo_e_prova_que_a_conta_fecha(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    saida = tmp_path / "r.json"
    assert main(["--oraculo", "--json", str(saida)]) == 0
    texto = capsys.readouterr().out
    assert "falso-aceite     0" in texto and "falso-rejeito    0" in texto
    bruto = json.loads(saida.read_text("utf-8"))
    assert bruto["resultado"]["total"] == len(_corpus())
    assert len(bruto["itens"]) == len(_corpus()) and all("p" in i for i in bruto["itens"])


def test_o_baseline_de_regras_erra_o_que_se_espera_dele(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--regras"]) == 0
    texto = capsys.readouterr().out
    assert "falso-aceite" in texto and "erros: e0" in texto, "o baseline devia errar alguma coisa"


def test_a_medicao_na_nuvem_recusa_sob_ci(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CI", "1")
    assert main(["--openrouter"]) == 2
    assert "recuso" in capsys.readouterr().err
