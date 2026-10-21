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
from jarvis.voz.interface import Hipotese, MotorDeAsr, Onde, Sinais, transcrever_com_sinais
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


class _Segmento:
    """O que o `faster-whisper` devolve por segmento — só os campos que o motor lê."""

    def __init__(self, texto: str, sem_fala: float, logprob: float, compressao: float) -> None:
        self.text = texto
        self.no_speech_prob = sem_fala
        self.avg_logprob = logprob
        self.compression_ratio = compressao


class _ModeloFalso:
    def __init__(self, *segmentos: _Segmento) -> None:
        self.segmentos = segmentos
        self.chamadas: list[dict[str, object]] = []

    def transcribe(self, _audio: object, **opcoes: object) -> tuple[list[_Segmento], None]:
        self.chamadas.append(opcoes)
        return list(self.segmentos), None


def test_o_whisper_local_devolve_os_sinais_dos_segmentos() -> None:
    """ADR-0043: o maior `no_speech_prob`, a média do `avg_logprob` e a maior compressão."""
    motor = MotorWhisper()
    motor._modelo = _ModeloFalso(
        _Segmento(" Clique no clipe", 0.5, -1.4, 1.0), _Segmento(" para ver.", 0.3, -1.0, 2.5)
    )

    transcricao = motor.transcrever_com_sinais(audio_de(500))

    assert transcricao.hipotese.texto == "Clique no clipe  para ver."
    assert transcricao.sinais.sem_fala == pytest.approx(0.5)
    assert transcricao.sinais.logprob == pytest.approx(-1.2)
    assert transcricao.sinais.compressao == pytest.approx(2.5)
    assert motor.transcrever(audio_de(500)) == transcricao.hipotese


def test_sem_segmento_nao_ha_texto_nem_sinal() -> None:
    motor = MotorWhisper()
    motor._modelo = _ModeloFalso()

    transcricao = motor.transcrever_com_sinais(audio_de(500))

    assert transcricao.hipotese == Hipotese("", 0.0)
    assert transcricao.sinais == Sinais()


def test_motor_sem_sinais_continua_valendo_pelo_texto() -> None:
    """O oráculo (e os falsos dos testes) não medem: o texto vem, e os sinais ficam vazios."""
    oraculo = MotorDeReferencia(texto=TEXTO, duracao_ms=1000.0)

    transcricao = transcrever_com_sinais(oraculo, audio_de(1000))

    assert transcricao.hipotese.texto == TEXTO
    assert transcricao.sinais == Sinais()
