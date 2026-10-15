"""Cartão F1-01: `JARVIS_AUDIO_BACKEND` escolhe, e valor errado não vira padrão silencioso."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.audio_io import (
    VARIAVEL_BACKEND,
    Backend,
    DispositivoProibidoEmCI,
    FonteDeArquivo,
    FonteDeDispositivo,
    FonteSintetica,
    SumidouroDeArquivo,
    SumidouroDeDispositivo,
    SumidouroEmMemoria,
    backend_escolhido,
    em_ci,
    fonte_do_ambiente,
    sumidouro_do_ambiente,
)
from jarvis.relogio import RelogioFalso


def test_sem_a_variavel_o_padrao_e_sintetico_e_nao_a_placa_de_som() -> None:
    assert backend_escolhido({}) is Backend.SINTETICO
    assert isinstance(fonte_do_ambiente(relogio=RelogioFalso(), ambiente={}), FonteSintetica)


def test_valor_desconhecido_da_variavel_e_erro_com_a_lista_do_que_vale() -> None:
    with pytest.raises(ValueError, match="arquivo, sintetico, dispositivo"):
        backend_escolhido({VARIAVEL_BACKEND: "pulseaudio"})


def test_backend_de_arquivo_exige_caminho() -> None:
    ambiente = {VARIAVEL_BACKEND: "arquivo"}
    with pytest.raises(ValueError, match="caminho"):
        fonte_do_ambiente(relogio=RelogioFalso(), ambiente=ambiente)

    fonte = fonte_do_ambiente(relogio=RelogioFalso(), caminho=Path("x.wav"), ambiente=ambiente)
    assert isinstance(fonte, FonteDeArquivo)


def test_backend_de_dispositivo_vem_montado_mas_recusa_abrir_sob_ci() -> None:
    ambiente = {VARIAVEL_BACKEND: "dispositivo", "CI": "1"}
    fonte = fonte_do_ambiente(relogio=RelogioFalso(), ambiente=ambiente)
    sumidouro = sumidouro_do_ambiente(ambiente=ambiente)

    assert isinstance(fonte, FonteDeDispositivo)
    assert isinstance(sumidouro, SumidouroDeDispositivo)
    with pytest.raises(DispositivoProibidoEmCI):
        fonte.abrir()
    with pytest.raises(DispositivoProibidoEmCI):
        sumidouro.abrir()


def test_sumidouro_segue_o_mesmo_backend(tmp_path: Path) -> None:
    assert isinstance(sumidouro_do_ambiente(ambiente={}), SumidouroEmMemoria)
    assert isinstance(
        sumidouro_do_ambiente(caminho=tmp_path / "s.wav", ambiente={VARIAVEL_BACKEND: "arquivo"}),
        SumidouroDeArquivo,
    )


@pytest.mark.parametrize("valor", ["1", "true", "TRUE", "yes", "on", "sim"])
def test_ci_e_reconhecido_nas_formas_que_os_ambientes_usam(valor: str) -> None:
    assert em_ci({"CI": valor})


@pytest.mark.parametrize("valor", ["", "0", "false", "no"])
def test_fora_do_ci_a_variavel_nao_mente(valor: str) -> None:
    assert not em_ci({"CI": valor})
