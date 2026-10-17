"""O corpus C2 sintético e as contas do harness da §8.1 — sem modelo e sem rede."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest
from tools.corpus_c2 import gerar, montar
from tools.harness_indice import calibrar_limiar, decidir, ndcg, recall

from jarvis.memoryd.indice import IndiceEmMemoria


def test_corpus_e_reproduzivel_e_do_tamanho_da_spec() -> None:
    um, outro = gerar(), gerar()
    assert um.hash == outro.hash
    contagem = Counter(c.subconjunto for c in um.consultas)
    assert set(contagem) == {"C2a", "C2b", "C2c", "C2d"}
    assert 100 <= len(um.consultas) <= 300, "a §8.1 pede 100–300 consultas"


def test_gabarito_aponta_para_fatos_que_existem() -> None:
    corpus = gerar()
    chaves = {f.chave for f in corpus.fatos}
    for consulta in corpus.consultas:
        assert set(consulta.gabarito) <= chaves
        assert set(consulta.vencidos) <= chaves
        assert bool(consulta.gabarito) == (consulta.subconjunto != "C2d")
    for consulta in (c for c in corpus.consultas if c.subconjunto == "C2c"):
        (novo,) = consulta.gabarito
        assert next(f for f in corpus.fatos if f.chave == novo).substitui in consulta.vencidos


def test_divisao_70_30_estratificada_e_disjunta() -> None:
    corpus = gerar()
    calibracao, retidas = corpus.dividir()
    assert not calibracao & retidas
    assert calibracao | retidas == {c.id for c in corpus.consultas}
    for sub in ("C2a", "C2b", "C2c", "C2d"):
        ids = {c.id for c in corpus.consultas if c.subconjunto == sub}
        assert ids & retidas, f"{sub} sem consulta retida"


def test_montar_grava_pelo_livro_com_vencidas_e_mencoes() -> None:
    corpus = gerar()
    montado = montar(corpus, IndiceEmMemoria())
    con = montado.livro.con
    assert set(montado.unidade_do_fato) == {f.chave for f in corpus.fatos}
    substituidas = sum(1 for f in corpus.fatos if f.substitui)
    assert (
        con.execute("SELECT COUNT(*) FROM assertion WHERE status = 'superseded'").fetchone()[0]
        == substituidas
    )
    assert con.execute("SELECT COUNT(*) FROM entity_edge").fetchone()[0] == len(corpus.arestas)
    ligadas = con.execute(
        "SELECT COUNT(*) FROM entity_mention WHERE memory_unit_id IS NOT NULL"
    ).fetchone()[0]
    assert ligadas > len(corpus.arestas), "o extrator de menções não ligou as memórias"
    assert con.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0


def test_metricas_de_ranking() -> None:
    assert recall(["a", "b", "c"], {"a", "z"}) == 0.5
    assert ndcg(["a", "b"], {"a"}) == 1.0
    assert ndcg(["b", "a"], {"a"}) == pytest.approx(1 / 1.585, rel=1e-3)


def test_limiar_separa_negativos_de_positivos() -> None:
    pares = [(0.9, False), (0.85, False), (0.7, True), (0.6, True)]
    limiar = calibrar_limiar(pares)
    assert 0.7 < limiar <= 0.85


def _resumo(*, residuo: dict[str, bool], recall: dict[str, float], p95: dict[str, float]) -> Any:
    return {
        "veto": {
            c: {"vetor_no_disco_depois_da_manutencao": r, "delete_tira_da_busca": True}
            for c, r in residuo.items()
        },
        "execucoes": [
            {"candidato": c, "recall20": recall[c], "busca_p95_ms": p95[c]} for c in recall
        ],
    }


@pytest.mark.parametrize(
    ("residuo", "recall_", "p95", "vencedor"),
    [
        (
            {"chroma": True, "lance": False},
            {"chroma": 0.9, "lance": 0.7},
            {"chroma": 1, "lance": 9},
            "lance",
        ),
        (
            {"chroma": False, "lance": False},
            {"chroma": 0.70, "lance": 0.71},
            {"chroma": 4, "lance": 4.5},
            "chroma",
        ),
        (
            {"chroma": False, "lance": False},
            {"chroma": 0.60, "lance": 0.70},
            {"chroma": 4, "lance": 4},
            "lance",
        ),
        (
            {"chroma": False, "lance": False},
            {"chroma": 0.70, "lance": 0.74},
            {"chroma": 4, "lance": 4},
            "dono",
        ),
    ],
)
def test_regra_da_8_1_na_ordem_dela(
    residuo: dict[str, bool], recall_: dict[str, float], p95: dict[str, float], vencedor: str
) -> None:
    assert decidir(_resumo(residuo=residuo, recall=recall_, p95=p95))["vencedor"] == vencedor
