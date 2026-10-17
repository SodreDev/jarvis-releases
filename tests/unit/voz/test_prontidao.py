"""O que falta para um motor rodar — a mesma frase para o laço e para a janela (bug do dono,
2026-10-16: a janela dizia "ligado" e o laço recusava por outro motivo)."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.voz.app import AplicativoIndisponivel, motor_de_tts
from jarvis.voz.config import Configuracao
from jarvis.voz.prontidao import o_que_falta
from jarvis.voz.provedores import provedores


def test_nuvem_desligada_diz_como_ligar() -> None:
    falta = o_que_falta("asr-groq-whisper-large-v3-turbo", Configuracao())
    assert "está desligado" in falta and "ligue" in falta


def test_nuvem_ligada_sem_chave_diz_onde_guardar() -> None:
    configuracao = Configuracao(voz_elevenlabs="v", nuvem_ligada=("tts-elevenlabs",))
    falta = o_que_falta("tts-elevenlabs", configuracao, ambiente={})
    assert "falta a chave JARVIS_ELEVENLABS_API_KEY" in falta and "Chaves de API" in falta


def test_elevenlabs_sem_voz_escolhida() -> None:
    configuracao = Configuracao(nuvem_ligada=("tts-elevenlabs",))
    falta = o_que_falta(
        "tts-elevenlabs", configuracao, ambiente={"JARVIS_ELEVENLABS_API_KEY": "x" * 20}
    )
    assert "falta escolher a voz" in falta


def test_piper_sem_a_voz_baixada(tmp_path: Path) -> None:
    falta = o_que_falta("tts-piper-epitran", Configuracao(), pasta_de_vozes=tmp_path)
    assert (
        falta.startswith("falta baixar a voz pt_BR-faber-medium") or "falta a biblioteca" in falta
    )


def test_motor_local_sem_dependencia_roda() -> None:
    assert o_que_falta("tts-parametrico", Configuracao()) == ""


def test_a_janela_e_o_laco_dizem_a_mesma_coisa(tmp_path: Path) -> None:
    configuracao = Configuracao(
        tts="tts-elevenlabs", voz_elevenlabs="v", nuvem_ligada=("tts-elevenlabs",)
    )
    (eleven,) = [p for p in provedores(configuracao, "tts", ambiente={}) if p.escolhido]
    assert eleven.ligado and eleven.falta
    with pytest.raises(AplicativoIndisponivel) as erro:
        motor_de_tts(configuracao, raiz=tmp_path, cancelado=lambda: False, ambiente={})
    assert eleven.falta in str(erro.value)
    assert eleven.para_dict()["falta"] == eleven.falta
