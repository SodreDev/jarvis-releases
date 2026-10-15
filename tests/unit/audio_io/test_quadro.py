"""Cartão F1-01: o quadro de 20 ms é contrato, não convenção."""

from __future__ import annotations

import math
from array import array

import pytest

from jarvis.audio_io import (
    AMOSTRAS_POR_QUADRO,
    BYTES_POR_QUADRO,
    PISO_DB,
    TAXA_PADRAO,
    Quadro,
    como_int16,
    de_int16,
    em_quadros,
    energia_db,
)


def test_o_quadro_tem_exatamente_320_amostras_a_16_khz() -> None:
    assert AMOSTRAS_POR_QUADRO == 320
    assert BYTES_POR_QUADRO == 640
    assert pytest.approx(0.020) == AMOSTRAS_POR_QUADRO / TAXA_PADRAO


def test_quadro_de_outro_tamanho_e_erro_e_nao_arredondamento() -> None:
    with pytest.raises(ValueError, match="640"):
        Quadro(indice=0, amostras=bytes(600), ts_mono_ns=0)


def test_silencio_digital_vira_piso_declarado_em_vez_de_menos_infinito() -> None:
    assert energia_db(bytes(BYTES_POR_QUADRO)) == PISO_DB
    assert math.isfinite(energia_db(bytes(BYTES_POR_QUADRO)))


def test_energia_de_senoide_de_meia_escala_bate_com_a_conta() -> None:
    valores = array(
        "h",
        (
            round(0.5 * 32767 * math.sin(math.tau * 440 * n / TAXA_PADRAO))
            for n in range(AMOSTRAS_POR_QUADRO)
        ),
    )
    quadro = Quadro(indice=0, amostras=de_int16(valores), ts_mono_ns=0)
    # RMS de uma senoide de amplitude 0,5 é 0,5/√2 ⇒ 20·log10(0,3536) ≈ -9,03 dBFS.
    assert quadro.energia_db == pytest.approx(-9.03, abs=0.3)


def test_ida_e_volta_de_int16_nao_depende_da_ordem_de_bytes_da_maquina() -> None:
    valores = array("h", [-32768, -1, 0, 1, 32767])
    assert list(como_int16(de_int16(valores))) == list(valores)


def test_em_quadros_completa_o_ultimo_quadro_e_carimba_de_20_em_20_ms() -> None:
    amostras = bytes(BYTES_POR_QUADRO + 100)  # um quadro e um pedaço
    quadros = em_quadros(amostras, ts_inicial_ns=1_000)

    assert [q.indice for q in quadros] == [0, 1]
    assert all(len(q.amostras) == BYTES_POR_QUADRO for q in quadros)
    assert quadros[1].ts_mono_ns - quadros[0].ts_mono_ns == 20_000_000
    assert quadros[1].duracao_ms == pytest.approx(20.0)
