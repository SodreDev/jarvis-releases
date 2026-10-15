"""Cartão F1-01: o gerador é determinístico e cada material é o que diz ser."""

from __future__ import annotations

from random import Random

import pytest

from jarvis.audio_io import (
    PISO_DB,
    ROTEIRO_PADRAO,
    TAXA_PADRAO,
    TipoDeTrecho,
    Trecho,
    aplicar_ganho_db,
    como_int16,
    de_int16,
    eco,
    energia_db,
    fala_simulada,
    gerar,
    misturar,
    ruido_rosa,
    silencio,
)


def test_mesma_semente_mesmos_bytes_e_semente_diferente_outro_sinal() -> None:
    assert gerar(semente=7) == gerar(semente=7)
    assert gerar(semente=7) != gerar(semente=8)


def test_silencio_e_zero_e_tem_o_piso_de_energia() -> None:
    amostras = silencio(100.0)
    assert set(amostras) == {0}
    assert energia_db(amostras) == PISO_DB


def test_fala_simulada_fica_na_faixa_declarada_de_energia() -> None:
    amostras = fala_simulada(500.0, aleatorio=Random(1))
    # Faixa declarada do gerador: alta o bastante para o detector ver fala (limiar -45 dBFS),
    # baixa o bastante para não saturar o int16.
    assert -30.0 < energia_db(amostras) < -8.0


def test_ruido_rosa_fica_abaixo_da_fala_no_ganho_padrao() -> None:
    assert energia_db(ruido_rosa(500.0, aleatorio=Random(1))) < energia_db(
        fala_simulada(500.0, aleatorio=Random(1))
    )


def test_ganho_de_menos_6_db_derruba_a_energia_em_6_db() -> None:
    sinal = fala_simulada(200.0, aleatorio=Random(2))
    assert energia_db(aplicar_ganho_db(sinal, -6.0)) == pytest.approx(
        energia_db(sinal) - 6.0, abs=0.2
    )


def test_eco_e_copia_atrasada_e_atenuada() -> None:
    sinal = fala_simulada(200.0, aleatorio=Random(3))
    com_eco = eco(sinal, atraso_ms=60.0, ganho_db=-12.0)

    n_atraso = int(TAXA_PADRAO * 0.060)
    assert len(com_eco) == len(sinal) + n_atraso * 2
    assert set(com_eco[: n_atraso * 2]) == {0}  # o atraso é silêncio
    assert energia_db(com_eco[n_atraso * 2 :]) == pytest.approx(energia_db(sinal) - 12.0, abs=0.2)


def test_misturar_satura_em_vez_de_dar_a_volta_no_int16() -> None:
    cheio = de_int16([32767] * 10)
    assert list(como_int16(misturar(cheio, cheio))) == [32767] * 10


def test_roteiro_padrao_tem_a_duracao_somada_dos_trechos() -> None:
    esperado_ms = sum(t.duracao_ms for t in ROTEIRO_PADRAO)
    amostras = gerar(ROTEIRO_PADRAO, semente=0)
    assert len(amostras) / 2 / TAXA_PADRAO * 1000 == pytest.approx(esperado_ms, abs=1.0)


def test_trecho_de_eco_repete_o_que_veio_antes_atenuado() -> None:
    roteiro = (
        Trecho(TipoDeTrecho.FALA, 200.0),
        Trecho(TipoDeTrecho.ECO, 200.0, ganho_db=-6.0, atraso_ms=200.0),
    )
    sinal = gerar(roteiro, semente=5)
    metade = len(sinal) // 2
    assert energia_db(sinal[metade:]) == pytest.approx(energia_db(sinal[:metade]) - 6.0, abs=0.5)
