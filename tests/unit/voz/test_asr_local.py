"""O ASR local fala a interface única e atravessa o portão de motores (ADR-0017).

O caminho medido do F1-06 não mudou — o que mudou é que agora o motor **declara** de onde ele
é e por qual id o portão o conhece. Estes testes são a diferença entre as duas coisas.
"""

from __future__ import annotations

import pytest

from jarvis.agentd.asr import (
    MotorDeReferencia,
    MotorWhisper,
    TranscritorIncremental,
)
from jarvis.audio_io.quadro import TAXA_PADRAO, de_int16
from jarvis.voz.interface import Hipotese, MotorDeAsr, Onde
from jarvis.voz.registro import MotorRecusado, exigir_motor

TEXTO = "abre a pasta de fotos na área de trabalho"


def audio_de(ms: float) -> bytes:
    return de_int16([0] * int(TAXA_PADRAO * ms / 1000))


@pytest.mark.parametrize(
    "motor",
    [MotorDeReferencia(texto=TEXTO, duracao_ms=1000.0), MotorWhisper()],
    ids=["oráculo", "whisper"],
)
def test_os_motores_locais_satisfazem_a_interface_unica(motor: MotorDeAsr) -> None:
    assert isinstance(motor, MotorDeAsr)
    assert motor.onde is Onde.LOCAL
    assert motor.idioma


def test_a_hipotese_tem_nome_e_continua_desempacotando_como_antes() -> None:
    """`NamedTuple` é o que deixa a interface ser única sem reescrever o F1-06."""
    hipotese = MotorDeReferencia(texto=TEXTO, duracao_ms=1000.0).transcrever(audio_de(1000))

    assert isinstance(hipotese, Hipotese)
    texto, confianca = hipotese  # é o que o TranscritorIncremental faz
    assert texto == hipotese.texto == TEXTO
    assert confianca == hipotese.confianca == 1.0
    assert hipotese[0] == TEXTO


def test_o_transcritor_incremental_continua_funcionando_com_a_hipotese_nomeada() -> None:
    from jarvis.audio_io.aec import quadros_de

    transcritor = TranscritorIncremental(
        motor=MotorDeReferencia(texto=TEXTO, duracao_ms=1000.0), passo_ms=200.0
    )
    transcritor.comecar(session_id="0193f0a0-0000-7000-8000-000000000000", epoch=1)
    eventos = [e for q in quadros_de(audio_de(1000)) for e in transcritor.ouvir(q)]

    assert eventos, "nenhum parcial saiu"
    assert transcritor.fechar()[0].payload["text"] == TEXTO


def test_motor_fora_do_registro_nao_abre_e_nem_tenta_importar_o_runtime() -> None:
    """O portão vem **antes** do runtime: a recusa é de registro, não de `ImportError`."""
    with pytest.raises(MotorRecusado, match="não está em"):
        MotorWhisper(registrado="asr-que-ninguem-verificou").abrir()


def test_o_whisper_local_esta_registrado_e_passa_no_portao() -> None:
    motor = exigir_motor(MotorWhisper().registrado)
    assert motor.onde is Onde.LOCAL
    assert motor.licenca_do_cliente == "MIT"  # faster-whisper
    assert motor.modelo.startswith("openai/whisper")
    assert motor.frase_de_aviso == "", "motor local não avisa: nada sai da máquina"


def test_o_oraculo_esta_registrado_para_o_ci_nao_virar_excecao() -> None:
    """Se o oráculo não estivesse no registro, o CI precisaria de um desvio no portão."""
    assert exigir_motor(MotorDeReferencia(texto="", duracao_ms=0).registrado).onde is Onde.LOCAL
