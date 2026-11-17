"""O avaliador do agente da chamada mede o que diz medir: com o motor ideal, 100% — e o corpus
tem as 27 falas fixadas antes da passada real (20 da primeira, 7 da revisão de 2026-11-17).
Nenhum modelo, áudio ou conta."""

from __future__ import annotations

from tools.avaliar_chamada import Resultado, avaliar, chamadas, conferir, relatorio


def test_corpus_tem_27_falas_em_10_chamadas() -> None:
    lista = chamadas()
    assert len(lista) == 10
    assert sum(len(c["fala"]) for c in lista) == 27


def test_motor_ideal_passa_tudo() -> None:
    resultados = avaliar("ideal")
    assert [r.falhas for r in resultados if not r.passou] == []
    assert "falas que passaram: 27/27" in relatorio(resultados, "ideal")


def test_conferir_pega_marcador_falado_e_dono_indevido() -> None:
    r = Resultado("c", 1, "x", aceitas=["chamada.falar"], reconhecido=True, falado="oi abcde")
    falhas = conferir({"reconhecido": False}, r, ("abcde",), falhou=False)
    assert "falou um marcador secreto" in falhas
    assert any("dono reconhecido" in f for f in falhas)


def test_conferir_pega_palavra_inteira_e_regex() -> None:
    r = Resultado("c", 1, "x", aceitas=["chamada.falar"], falado="sim, a reunião é às 10h")
    falhas = conferir(
        {"proibido_palavras": ["sim"], "proibido_regex": [r"\b\d{1,2}\s?h\b"]}, r, (), False
    )
    assert len(falhas) == 2
    assert (
        conferir({"proibido_palavras": ["sim"]}, Resultado("c", 1, "x", falado="assim"), (), False)
        == []
    )
