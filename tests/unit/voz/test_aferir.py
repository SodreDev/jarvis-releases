"""Os dois testes da aba de diagnóstico (ADR-0019): o microfone pega? a voz sai?

Sem placa de som: com `JARVIS_AUDIO_BACKEND=arquivo` a fonte é um WAV e o sumidouro é outro,
que é o banco de teste do F1-01. O que se prova aqui é que a medição **termina**, que ela
devolve recusa em vez de exceção quando não há dispositivo, e que o nível medido é o do áudio
que entrou — não um número inventado pela tela.
"""

from __future__ import annotations

import wave
from pathlib import Path

from jarvis.audio_io.quadro import TAXA_PADRAO, de_int16
from jarvis.relogio import RelogioFalso
from jarvis.voz.aferir import PISO_DB, medir_microfone, provar_voz
from jarvis.voz.config import Configuracao

ARQUIVO = {"JARVIS_AUDIO_BACKEND": "arquivo"}
CONFIGURACAO = Configuracao(asr="asr-whisper-local", tts="tts-parametrico", s2="eco")


def wav_de(caminho: Path, valor: int, segundos: float = 1.0) -> Path:
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(TAXA_PADRAO)
        arquivo.writeframes(de_int16([valor] * int(TAXA_PADRAO * segundos)))
    return caminho


def test_microfone_com_som_relata_nivel_e_termina(tmp_path: Path) -> None:
    nivel = medir_microfone(
        CONFIGURACAO,
        segundos=0.5,
        ambiente=ARQUIVO,
        relogio=RelogioFalso(),
        caminho_de_entrada=wav_de(tmp_path / "alto.wav", valor=8000),
    )

    assert nivel.deu_certo
    assert nivel.quadros == 25, "o teto de quadros não foi respeitado"
    assert nivel.pico_db > -30.0
    assert "chegando som" in nivel.frase()


def test_microfone_em_silencio_diz_que_nada_chegou(tmp_path: Path) -> None:
    """Fonte aberta e zero sinal é um diagnóstico — e é diferente de dispositivo ausente."""
    nivel = medir_microfone(
        CONFIGURACAO,
        segundos=0.2,
        ambiente=ARQUIVO,
        relogio=RelogioFalso(),
        caminho_de_entrada=wav_de(tmp_path / "mudo.wav", valor=0),
    )

    assert nivel.quadros > 0
    assert nivel.pico_db <= PISO_DB + 1
    assert "silêncio digital" in nivel.frase()


def test_sem_dispositivo_a_medicao_devolve_recusa_em_vez_de_explodir() -> None:
    nivel = medir_microfone(
        CONFIGURACAO, segundos=0.2, ambiente={"JARVIS_AUDIO_BACKEND": "dispositivo", "CI": "1"}
    )

    assert not nivel.deu_certo
    assert nivel.erro, "recusa sem frase não ajuda ninguém"
    assert "CI" in nivel.frase()


def test_cancelar_para_a_medicao_no_meio(tmp_path: Path) -> None:
    vistos: list[float] = []
    nivel = medir_microfone(
        CONFIGURACAO,
        segundos=10.0,
        ambiente=ARQUIVO,
        relogio=RelogioFalso(),
        caminho_de_entrada=wav_de(tmp_path / "longo.wav", valor=5000, segundos=5.0),
        ao_quadro=vistos.append,
        cancelado=lambda: len(vistos) >= 3,
    )

    assert nivel.quadros == 3
    assert len(vistos) == 3, "a barrinha de nível não recebeu um dB por quadro"


def test_a_voz_de_teste_sai_pelo_sumidouro(tmp_path: Path) -> None:
    saida = tmp_path / "voz.wav"

    prova = provar_voz(
        CONFIGURACAO,
        raiz=tmp_path / "sessao",
        ambiente=ARQUIVO,
        caminho_de_saida=saida,
    )

    assert prova.deu_certo, prova.erro
    assert prova.amostras > 0
    assert prova.onde == "local"
    assert saida.exists() and saida.stat().st_size > 44
    assert "de áudio" in prova.frase()


def test_motor_que_nao_existe_vira_frase_e_nao_traceback(tmp_path: Path) -> None:
    prova = provar_voz(
        CONFIGURACAO.com(tts="tts-que-ninguem-registrou"),
        raiz=tmp_path / "sessao",
        ambiente=ARQUIVO,
        caminho_de_saida=tmp_path / "voz.wav",
    )

    assert not prova.deu_certo
    assert "não está no registro" in prova.erro
