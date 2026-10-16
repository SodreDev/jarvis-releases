"""A medição da palavra de ativação (ADR-0021): a regra do limiar e o número publicado.

Roda só com a redução sem dependência (`--sem-epitran`), em pasta temporária: o CI não tem o
grupo `voz`, e o relatório de `docs/medicoes` não é reescrito pela suíte.
"""

from __future__ import annotations

from pathlib import Path

from tools.harness_palavra import Linha, escolher, ler_varredura, main

from jarvis.voz.palavra import LIMIAR_PADRAO

RAIZ = Path(__file__).resolve().parents[3]
PUBLICADO = RAIZ / "docs" / "medicoes" / "palavra-de-ativacao.csv"


def _linha(limiar: float, *, fp: int = 0, fn: int = 0) -> Linha:
    return Linha(
        fonemizador="simples",
        limiar=limiar,
        negativos=10,
        fp_corpus=0,
        vizinhos=10,
        fp_vizinhos=fp,
        positivos=10,
        fn=fn,
        comando_errado=0,
    )


def test_escolhe_o_meio_do_plato_sem_falso_positivo() -> None:
    linhas = [
        _linha(0.60, fp=3),
        _linha(0.70),
        _linha(0.75),
        _linha(0.80),
        _linha(0.85, fn=5),
    ]
    assert escolher(linhas) == 0.75


def test_sem_limiar_seguro_nao_inventa_um() -> None:
    assert escolher([_linha(0.6, fp=1), _linha(0.9, fp=1)]) is None


def test_harness_roda_e_o_padrao_do_codigo_e_o_que_ele_sugere(tmp_path: Path) -> None:
    assert main(["--saida", str(tmp_path), "--sem-epitran"]) == 0
    linhas = ler_varredura(tmp_path / "palavra-de-ativacao.csv")
    no_padrao = next(
        linha
        for linha in linhas
        if linha["fonemizador"] == "simples" and float(linha["limiar"]) == LIMIAR_PADRAO
    )
    assert int(no_padrao["fp_corpus"]) == 0
    assert int(no_padrao["fp_vizinhos"]) == 0
    assert int(no_padrao["fn"]) == 0
    relatorio = (tmp_path / "palavra-de-ativacao.md").read_text(encoding="utf-8")
    assert "Só texto" in relatorio and "não foi medido" in relatorio


def test_o_csv_publicado_existe_e_tem_os_dois_fonemizadores() -> None:
    nomes = {linha["fonemizador"] for linha in ler_varredura(PUBLICADO)}
    assert nomes == {"simples", "epitran"}
