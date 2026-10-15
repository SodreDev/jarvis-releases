"""Fusão das três listas por RRF e recuperação completa (SPEC §6.8 passo 3) — cartão F0-05."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from jarvis.memoryd.esquema import abrir
from jarvis.memoryd.fusao import buscar_lexico, recuperar, rrf, termos
from jarvis.memoryd.grafo import Tetos
from jarvis.memoryd.sintetico import Escala, gerar


@pytest.fixture
def grafo() -> Iterator[sqlite3.Connection]:
    con = abrir()
    gerar(con, Escala.de_corpus("teste", episodios_base=122, fator=1))
    yield con
    con.close()


def test_rrf_soma_as_posicoes_e_guarda_a_fonte() -> None:
    fundido = rrf([("densa", ["a", "b", "c"]), ("lexica", ["b", "a"]), ("grafo", ["c"])], k=60)
    por_id = {i: (e, f) for i, e, f in fundido}

    assert fundido[0][0] == "a"  # 1º na densa + 2º na léxica
    assert por_id["b"][1] == ("densa", "lexica")
    assert por_id["c"][1] == ("densa", "grafo")
    assert por_id["a"][0] > por_id["c"][0]


def test_rrf_nao_precisa_de_escores_comparaveis() -> None:
    """É o ponto do RRF: fundir listas de naturezas diferentes sem calibrar uma na outra."""
    fundido = rrf([("densa", ["x"]), ("lexica", ["y"]), ("grafo", ["x"])])

    assert fundido[0][0] == "x"
    assert fundido[0][2] == ("densa", "grafo")


def test_termos_normaliza_acento_e_caixa() -> None:
    assert termos("Café com Pão") == ["café", "com", "pão"]


def test_busca_lexica_fts5_encontra_por_termo(grafo: sqlite3.Connection) -> None:
    achados = buscar_lexico(grafo, "entidade 42", k=5)

    assert achados
    assert all(a.startswith("mu-") for a in achados)


def test_busca_lexica_ignora_diacritico(grafo: sqlite3.Connection) -> None:
    """`remove_diacritics 2` na FTS5: "nota" e "notá" caem no mesmo token."""
    com = buscar_lexico(grafo, "nota", k=3)
    sem = buscar_lexico(grafo, "nótá", k=3)

    assert com and com == sem


def test_recuperacao_devolve_de_quatro_a_oito_evidencias_com_caminho(
    grafo: sqlite3.Connection,
) -> None:
    resultado = recuperar(grafo, "entidade 42", evidencias=8)

    assert 4 <= len(resultado.achados) <= 8
    assert any(a.caminho for a in resultado.achados), "nenhuma evidência trouxe caminho de grafo"
    assert all(a.fontes for a in resultado.achados)
    assert resultado.ms_total > 0


def test_recuperacao_usa_as_tres_listas(grafo: sqlite3.Connection) -> None:
    resultado = recuperar(grafo, "entidade 42")
    fontes = {fonte for achado in resultado.achados for fonte in achado.fontes}

    assert fontes == {"densa", "lexica", "grafo"}


def test_truncamento_do_grafo_chega_a_quem_consulta(grafo: sqlite3.Connection) -> None:
    """A recuperação não esconde que veio truncada (§6.8, P9)."""
    resultado = recuperar(grafo, "entidade 42", tetos=Tetos(saltos=2, orcamento_ms=0.0))

    assert resultado.graph_truncated
    assert resultado.motivo
    assert resultado.achados, "truncado ainda tem de ser utilizável"


def test_consulta_sem_correspondencia_nao_inventa_evidencia(grafo: sqlite3.Connection) -> None:
    """§6.8 passo 5: abstinência é resposta válida; inventar não é (P9)."""
    resultado = recuperar(grafo, "zymbxqw inexistente")

    assert resultado.achados == []
