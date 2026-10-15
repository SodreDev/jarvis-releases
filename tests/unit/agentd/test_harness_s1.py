"""Cartão F1-08, aceite (b): o harness mede n ≥ 10 000 e publica sem depender de hardware."""

from __future__ import annotations

import csv
from pathlib import Path

from tools.harness_s1 import ESTADOS, main

from jarvis.agentd.s1 import TETO_MS

RAIZ = Path(__file__).resolve().parents[3]


def test_o_harness_publica_custo_por_cenario(tmp_path: Path) -> None:
    assert main(["--n", "200", "--saida", str(tmp_path)]) == 0

    md = (tmp_path / "f1-08-s1.md").read_text(encoding="utf-8")
    with (tmp_path / "f1-08-s1.csv").open(encoding="utf-8") as arquivo:
        linhas = list(csv.DictReader(arquivo))

    assert len(linhas) == len(ESTADOS)
    assert {linha["cenario"] for linha in linhas} == {nome for nome, _ in ESTADOS}
    assert "não depende de hardware" in md
    assert f"{TETO_MS:.0f} ms" in md


def test_a_decisao_custa_muito_menos_que_o_teto(tmp_path: Path) -> None:
    """O orçamento não é gasto pela tabela: é gasto pelo que vem antes dela."""
    main(["--n", "500", "--saida", str(tmp_path)])

    with (tmp_path / "f1-08-s1.csv").open(encoding="utf-8") as arquivo:
        p95 = [float(linha["p95_us"]) for linha in csv.DictReader(arquivo)]

    assert max(p95) < TETO_MS * 1000 / 100, "a decisão tem de ficar na casa dos microssegundos"


def test_o_harness_nao_escreve_na_medicao_publicada(tmp_path: Path) -> None:
    publicada = RAIZ / "docs" / "medicoes" / "f1-08-s1.md"
    antes = publicada.read_bytes() if publicada.exists() else None

    main(["--n", "100", "--saida", str(tmp_path)])

    assert (publicada.read_bytes() if publicada.exists() else None) == antes
