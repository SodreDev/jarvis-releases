"""Cartão F1-01, aceite (b): mesma entrada e mesma semente ⇒ mesma trilha."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from jarvis.audio_io import (
    ROTEIRO_PADRAO,
    TAXA_PADRAO,
    FonteDeArquivo,
    FonteSintetica,
    gerar,
    reproduzir,
)
from jarvis.audio_io import trilha as modulo_trilha
from jarvis.relogio import RelogioFalso

SESSAO = "0193f0a0-0000-7000-8000-000000000000"


def reproduzir_sintetico(semente: int) -> list[modulo_trilha.EventoDeTrilha]:
    fonte = FonteSintetica(relogio=RelogioFalso(), semente=semente)
    return reproduzir(fonte, session_id=SESSAO).eventos


def test_duas_execucoes_com_a_mesma_semente_dao_a_mesma_trilha() -> None:
    assert modulo_trilha.comparar(reproduzir_sintetico(7), reproduzir_sintetico(7)) is None


def test_semente_diferente_muda_a_trilha_e_a_divergencia_e_apontada() -> None:
    divergencia = modulo_trilha.comparar(reproduzir_sintetico(7), reproduzir_sintetico(8))

    assert divergencia is not None


def test_a_trilha_segue_o_roteiro_nos_instantes_exatos_do_relogio_injetado() -> None:
    """A asserção de latência é exata porque o tempo é virtual: nada de ± do escalonador."""
    eventos = reproduzir_sintetico(7)
    fronteiras_ms = []
    acumulado = 0.0
    for trecho in ROTEIRO_PADRAO:
        acumulado += trecho.duracao_ms
        fronteiras_ms.append(acumulado)

    instantes_ms = [e.ts_mono_ns / 1_000_000 for e in eventos]
    fala = [e.payload["speech"] for e in eventos]

    assert fala == [False, True, False, True, False]
    # O primeiro evento é o estado inicial, no primeiro quadro (20 ms); os outros caem no
    # quadro seguinte a cada fronteira do roteiro (200, 800, 1100, 1500 ms).
    assert instantes_ms[0] == 20.0
    assert instantes_ms[1] == pytest.approx(fronteiras_ms[0] + 20.0, abs=20.0)
    assert instantes_ms[2] == pytest.approx(fronteiras_ms[1] + 20.0, abs=20.0)
    assert all(i % 20.0 == 0 for i in instantes_ms)


def test_o_mesmo_wav_duas_vezes_da_a_mesma_trilha(tmp_path: Path) -> None:
    caminho = tmp_path / "turno.wav"
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(TAXA_PADRAO)
        arquivo.writeframes(gerar(semente=2))

    def trilha_do_wav() -> list[modulo_trilha.EventoDeTrilha]:
        fonte = FonteDeArquivo(caminho=caminho, relogio=RelogioFalso())
        return reproduzir(fonte, session_id=SESSAO).eventos

    assert modulo_trilha.comparar(trilha_do_wav(), trilha_do_wav()) is None
    assert len(trilha_do_wav()) == 5


def test_a_reproducao_conta_quadros_e_amostras_consumidos() -> None:
    fonte = FonteSintetica(relogio=RelogioFalso(), semente=1)
    reproducao = reproduzir(fonte, session_id=SESSAO)

    esperado_ms = sum(t.duracao_ms for t in ROTEIRO_PADRAO)
    assert reproducao.quadros == pytest.approx(esperado_ms / 20, abs=1)
    assert reproducao.amostras == reproducao.quadros * 320
    assert reproducao.duracao_ms == pytest.approx(esperado_ms, abs=20)
