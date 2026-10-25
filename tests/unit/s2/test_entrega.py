"""O que já foi dito não se diz de novo (`jarvis.s2.entrega`, dono, 2026-10-25; ADR-0046)."""

from __future__ import annotations

import pytest

from jarvis.s2.entrega import FiltroDoJaDito, cita_ferramenta, frases, so_o_novo, traz_algo_novo


@pytest.mark.parametrize(
    ("frase", "ditos", "novo"),
    [
        # a repetição de sempre: calada
        ("Pronto, abri o Discord.", ["Abrindo o Discord."], False),
        ("Pronto, o Discord está aberto.", ["Vou abrir o Discord."], False),
        ("O Steam foi encerrado.", ["Encerrei o Steam."], False),
        ("Fechei a janela do Brave.", ["Vou fechar o Brave."], False),
        ("Terminei o que você pediu.", ["Certo, já cuido disso."], False),
        ("O Discord já está aberto na sua tela.", ["Abrindo o Discord."], False),
        ("Posso fechar o Brave?", ["Posso fechar o Brave?"], False),
        # o resultado que o dono ainda não ouviu: dito
        ("Pronto, abri o Discord.", ["Certo, já cuido disso."], True),
        (
            "Abri o vídeo mais recente do Primo Rico.",
            ["Abri a busca do YouTube por Primo Rico."],
            True,
        ),
        ("São três e meia.", ["Vou ver."], True),
        ("Quer que eu entre no servidor do trabalho?", ["Abrindo o Discord."], True),
        ("Abri o Kate.", ["Certo."], True),
        ("Apaguei.", ["Vou apagar."], True),  # a intenção não é o resultado
        ("Apaguei a anotação do café.", ["Apaguei a anotação do café."], False),
        # falha: só a repetição exata se cala
        ("Não consegui: nenhum navegador está aberto.", ["Certo, já cuido disso."], True),
        (
            "Não consegui: nenhum navegador está aberto.",
            ["Não consegui: nenhum navegador está aberto."],
            False,
        ),
    ],
)
def test_traz_algo_novo(frase: str, ditos: list[str], novo: bool) -> None:
    assert traz_algo_novo(frase, ditos) is novo


def test_so_o_novo_fica_com_as_frases_que_trazem_algo_e_sem_nada_dito_passa_tudo() -> None:
    texto = "Pronto! O Discord já está aberto. Quer que eu entre no servidor?"
    assert so_o_novo(texto, ["Abrindo o Discord."]) == "Quer que eu entre no servidor?"
    assert so_o_novo("Pronto.", []) == "Pronto.", "a primeira resposta nunca é calada"


def test_o_filtro_em_stream_espera_a_frase_fechar_e_cala_a_repeticao_de_si_mesmo() -> None:
    filtro = FiltroDoJaDito(ditos=["Certo."])
    assert filtro.passar("Abri o Kate com o arquivo ") == ""
    assert filtro.passar("de notas. O Kate está ") == "Abri o Kate com o arquivo de notas. "
    assert filtro.passar("aberto.") == ""
    assert filtro.fechar() == ""
    assert filtro.caladas == ["O Kate está aberto."]


def test_a_frase_que_cita_ferramenta_e_etapa_interna_mesmo_sem_nada_dito() -> None:
    filtro = FiltroDoJaDito(ditos=[], ids=frozenset({"files.read_text"}))
    assert (
        filtro.passar("Usei files.read_text para ler. Na nota tem café. ") == "Na nota tem café. "
    )
    assert cita_ferramenta('Mandei {"x": 1}.', ())
    assert not cita_ferramenta("Abri o arquivo de texto.", {"files.read_text"})


def test_frases_respeita_abreviacao_e_inicial() -> None:
    completas, resto = frases("O Sr. Silva ligou. J. R. R. Tolkien escreveu. E mais")
    assert completas == ["O Sr. Silva ligou. ", "J. R. R. Tolkien escreveu. "]
    assert resto == "E mais"
