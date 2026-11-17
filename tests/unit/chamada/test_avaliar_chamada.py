"""O avaliador do agente da chamada mede o que diz medir: com o motor ideal, 100% — e o corpus
tem as 20 falas fixadas antes da passada real. Nenhum modelo, áudio ou conta."""

from __future__ import annotations

from tools.avaliar_chamada import Resultado, avaliar, chamadas, conferir, relatorio


def test_corpus_tem_20_falas_em_8_chamadas() -> None:
    lista = chamadas()
    assert len(lista) == 8
    assert sum(len(c["fala"]) for c in lista) == 20


def test_motor_ideal_passa_tudo() -> None:
    resultados = avaliar("ideal")
    assert [r.falhas for r in resultados if not r.passou] == []
    assert "falas que passaram: 20/20" in relatorio(resultados, "ideal")


def test_conferir_pega_marcador_falado_e_dono_indevido() -> None:
    r = Resultado("c", 1, "x", aceitas=["chamada.falar"], reconhecido=True, falado="oi abcde")
    falhas = conferir({"reconhecido": False}, r, ("abcde",), falhou=False)
    assert "falou um marcador secreto" in falhas
    assert any("dono reconhecido" in f for f in falhas)
