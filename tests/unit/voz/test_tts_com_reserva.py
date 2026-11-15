"""A voz não impede a conversa (bug do dono, 2026-11-14): o TTS escolhido que não abre — chave da
ElevenLabs ausente, nuvem desligada — dá lugar ao endpoint de voz (ADR-0068) quando ele está
ligado, senão ao motor local padrão, com uma frase curta do porquê. Motores falsos: nenhum áudio,
nenhuma rede, nenhuma chave lida."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from jarvis.voz import app
from jarvis.voz.app import AplicativoIndisponivel, motor_de_tts_com_reserva
from jarvis.voz.chaves import SegredoAusente
from jarvis.voz.config import TTS_ENDPOINT, TTS_PADRAO, Configuracao


def _motores(monkeypatch: pytest.MonkeyPatch, *, quebram: set[str]) -> list[str]:
    pedidos: list[str] = []

    def falso(configuracao: Configuracao, **_: Any) -> str:
        pedidos.append(configuracao.tts)
        if configuracao.tts in quebram:
            raise SegredoAusente("falta a chave JARVIS_ELEVENLABS_API_KEY")
        return f"motor:{configuracao.tts}"

    monkeypatch.setattr(app, "motor_de_tts", falso)
    return pedidos


def _abrir(configuracao: Configuracao) -> tuple[Any, str]:
    return motor_de_tts_com_reserva(configuracao, raiz=Path(), cancelado=lambda: False)


def test_o_escolhido_que_abre_fala_sem_aviso(monkeypatch: pytest.MonkeyPatch) -> None:
    _motores(monkeypatch, quebram=set())
    assert _abrir(Configuracao(tts="tts-elevenlabs")) == ("motor:tts-elevenlabs", "")


def test_sem_a_chave_da_elevenlabs_fala_o_endpoint_ligado(monkeypatch: pytest.MonkeyPatch) -> None:
    pedidos = _motores(monkeypatch, quebram={"tts-elevenlabs"})
    configuracao = Configuracao(tts="tts-elevenlabs", nuvem_ligada=("tts-endpoint",))

    motor, frase = _abrir(configuracao)

    assert motor == f"motor:{TTS_ENDPOINT}"
    assert pedidos == ["tts-elevenlabs", TTS_ENDPOINT]
    assert "tts-elevenlabs" in frase and TTS_ENDPOINT in frase


def test_sem_endpoint_ligado_fala_o_motor_local(monkeypatch: pytest.MonkeyPatch) -> None:
    pedidos = _motores(monkeypatch, quebram={"tts-elevenlabs"})

    motor, frase = _abrir(Configuracao(tts="tts-elevenlabs"))

    assert motor == f"motor:{TTS_PADRAO}"
    assert pedidos == ["tts-elevenlabs", TTS_PADRAO]
    assert frase


def test_so_quando_nem_o_padrao_abre_o_erro_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    _motores(monkeypatch, quebram={"tts-elevenlabs", TTS_PADRAO})
    with pytest.raises((SegredoAusente, AplicativoIndisponivel)):
        _abrir(Configuracao(tts="tts-elevenlabs"))
