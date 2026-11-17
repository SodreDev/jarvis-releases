"""O avaliador do canal do dono mede o que diz medir: com o motor ideal, 100% — e o corpus tem os
13 casos fixados antes da passada real. Nenhum modelo, navegador ou conta."""

from __future__ import annotations

from tools.avaliar_canal_do_dono import Resultado, avaliar, casos, conferir, relatorio


def test_corpus_tem_13_casos() -> None:
    lista = casos()
    assert len(lista) == 13
    assert len({c["id"] for c in lista}) == 13


def test_motor_ideal_passa_tudo() -> None:
    resultados = avaliar("ideal")
    assert [r.falhas for r in resultados if not r.passou] == []
    assert "casos que passaram: 13/13" in relatorio(resultados, "ideal")


def test_conferir_pega_envio_fora_do_chat_do_dono_e_estado_errado() -> None:
    r = Resultado("k", enviadas=[("c1", "x")], estados=["confirmada"])
    falhas = conferir(
        {"deve_enviar_em": "c2", "eventos": ["acao"], "estado_final": ["pendente"]}, r
    )
    assert any("fora do chat do dono" in f for f in falhas)
    assert any("estados" in f for f in falhas)
