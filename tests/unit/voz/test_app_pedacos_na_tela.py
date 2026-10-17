"""A tela segue a geração, não a fala (achado do dono, 2026-10-17: "um bloco por segundo").

O tocador só puxa o pedaço seguinte depois de tocar o anterior em tempo real; o texto que vai
para a janela tem de sair na linha do cérebro, no instante em que o pedaço nasce.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

import jarvis.voz.app as modulo
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao

FRASES = 12
REPRODUCAO_S = 0.15
"""Quanto o "alto-falante" leva para consumir cada pedaço (real: 2 a 4 s por frase)."""


def test_o_texto_chega_a_tela_no_ritmo_da_geracao_e_nao_da_reproducao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = modulo.SintetizadorEmStreaming.pedacos_do_stream

    def com_reproducao_lenta(self: Any, trechos: Any) -> Iterator[Any]:
        for item in original(self, trechos):
            yield item
            time.sleep(REPRODUCAO_S)

    monkeypatch.setattr(modulo.SintetizadorEmStreaming, "pedacos_do_stream", com_reproducao_lenta)
    laco = Aplicativo(
        configuracao=Configuracao(asr="asr-whisper-local", tts="tts-parametrico", s2="eco"),
        raiz=tmp_path,
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        caminho_de_saida=tmp_path / "saida.wav",
    )
    laco._motor = MotorRoteirizado(
        resposta=" ".join(f"Esta é a frase número {i} da resposta." for i in range(FRASES)),
        atraso_entre_deltas_s=0.002,
    )
    marcas: list[float] = []
    inicio = time.monotonic()
    laco.ao_pedaco = lambda _texto: marcas.append(time.monotonic() - inicio)
    laco.abrir(com_asr=False)

    laco.rodar_texto(["conta uma história"])
    total = time.monotonic() - inicio

    assert len(marcas) >= FRASES
    reproducao = FRASES * REPRODUCAO_S
    assert total >= reproducao * 0.9, "o teste só vale com a reprodução lenta de verdade"
    assert marcas[-1] < reproducao / 2, (
        f"o último pedaço só chegou à tela em {marcas[-1]:.2f} s de {reproducao:.2f} s de fala: "
        "a tela está seguindo o alto-falante"
    )
    intervalos = [b - a for a, b in pairwise(marcas)]
    assert statistics.median(intervalos) < REPRODUCAO_S / 2
