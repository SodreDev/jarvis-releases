"""A tela segue a geração, não a fala (achado do dono, 2026-10-17: "um bloco por segundo").

O tocador só puxa o pedaço seguinte depois de tocar o anterior; o texto que vai para a janela tem
de sair na linha do cérebro, no instante em que nasce. A prova não mede tempo — sob carga a
máquina atrasa tudo, e um teto em segundos falhava sem defeito nenhum: o "alto-falante" fica
**parado no primeiro lote** até a tela ter a resposta inteira. Se a tela seguisse a fala, ela não
chegaria ao fim com o alto-falante parado, e o prazo (generoso, só para o teste não travar) vence.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from jarvis.agentd.tts import SintetizadorEmStreaming
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao

FRASES = 30
"""15 lotes de fala: mais que o primeiro + 3 sínteses à frente + qualquer fila curta."""
ULTIMA = f"Esta é a frase número {FRASES - 1} da resposta."
PRAZO_S = 20.0
"""Só vence se a tela não seguir a geração; a resposta inteira chega em milissegundos."""


def test_a_tela_recebe_a_resposta_inteira_com_o_alto_falante_parado_no_primeiro_lote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tela: list[str] = []
    completa = threading.Event()
    parado_ate_a_tela_completar: list[bool] = []
    original = SintetizadorEmStreaming.pedacos_do_stream

    def parado_no_primeiro(self: Any, trechos: Any) -> Iterator[Any]:
        for indice, item in enumerate(original(self, trechos)):
            yield item
            if indice == 0:  # o tocador pede o 2º lote: o alto-falante "ainda fala" o 1º
                parado_ate_a_tela_completar.append(completa.wait(PRAZO_S))

    def mostrar(texto: str) -> None:
        tela.append(texto)
        if texto.endswith(ULTIMA):
            completa.set()

    monkeypatch.setattr(SintetizadorEmStreaming, "pedacos_do_stream", parado_no_primeiro)
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
    laco.ao_pedaco = mostrar
    laco.abrir(com_asr=False)

    laco.rodar_texto(["conta uma história"])

    assert parado_ate_a_tela_completar == [True], (
        "com o alto-falante parado no 1º lote, a tela não chegou ao fim da resposta: ela está "
        "seguindo a fala"
    )
    assert len(tela) >= 2, "a tela tem de crescer, não aparecer inteira de uma vez"
    assert all(b.startswith(a) for a, b in pairwise(tela)), "o texto só cresce"
    assert laco.turnos and laco.turnos[-1].respondeu.endswith(ULTIMA)
