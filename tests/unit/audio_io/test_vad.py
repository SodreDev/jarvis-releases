"""Cartão F1-05: histerese em dado, `silero-vad` atrás da interface, e nada de decidir turno."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.audio_io import TipoDeTrecho, Trecho, gerar
from jarvis.audio_io.aec import quadros_de
from jarvis.audio_io.energia import DetectorDeEnergia
from jarvis.audio_io.quadro import BYTES_POR_QUADRO, MS_POR_QUADRO, Quadro, de_int16
from jarvis.audio_io.vad import (
    ARQUIVO_SILERO,
    CONTEXTO_SILERO,
    JANELA_SILERO,
    PASTA_MODELOS_PADRAO,
    Histerese,
    MaquinaDeHisterese,
    ModeloIndisponivel,
    Vad,
    VadDeEnergia,
    VadSilero,
    vad_do_ambiente,
)

MODELO = PASTA_MODELOS_PADRAO / ARQUIVO_SILERO
sem_modelo = pytest.mark.skipif(
    not MODELO.exists(), reason=f"peso do silero-vad não está em {MODELO} (modelo não é versionado)"
)


def quadro_de(nivel: float, indice: int = 0) -> Quadro:
    valor = int(nivel * 32767)
    return Quadro(
        indice=indice,
        amostras=de_int16([valor if i % 2 else -valor for i in range(320)]),
        ts_mono_ns=indice * 20_000_000,
    )


def test_as_duas_implementacoes_cumprem_o_protocolo() -> None:
    assert isinstance(VadDeEnergia(), Vad)
    assert isinstance(DetectorDeEnergia(), Vad), "o limiar do F1-01 também é um Vad"
    assert isinstance(VadSilero(), Vad)


def test_ligar_custa_um_quadro_porque_speech_started_e_o_gatilho_do_barge_in() -> None:
    maquina = MaquinaDeHisterese(histerese=Histerese(quadros_para_ligar=1))

    assert maquina.ver(0.9) is True
    assert maquina.ver(0.9) is None, "ligar duas vezes não é mudança"


def test_desligar_espera_os_quadros_e_o_hangover() -> None:
    """A assimetria é a política: pausa entre palavras não é fim de fala."""
    histerese = Histerese(quadros_para_desligar=3, hangover_ms=100.0)
    maquina = MaquinaDeHisterese(histerese=histerese)
    maquina.ver(0.9)

    quadros_de_silencio = histerese.quadros_para_silencio
    assert quadros_de_silencio == 3 + 5
    for _ in range(quadros_de_silencio - 1):
        assert maquina.ver(0.0) is None
    assert maquina.ver(0.0) is False


def test_um_quadro_acima_do_limiar_reinicia_a_contagem_de_silencio() -> None:
    maquina = MaquinaDeHisterese(histerese=Histerese(quadros_para_desligar=2, hangover_ms=0.0))
    maquina.ver(0.9)
    maquina.ver(0.0)
    maquina.ver(0.9)  # voltou a falar: a contagem de silêncio zera

    assert maquina.ver(0.0) is None
    assert maquina.ver(0.0) is False


def test_vad_de_energia_tem_histerese_e_o_limiar_do_f1_01_nao() -> None:
    """Dois componentes de propósito: a trilha do F1-01 não pode ser suavizada."""
    com = VadDeEnergia(histerese=Histerese(quadros_para_desligar=5, hangover_ms=100.0))
    sem = DetectorDeEnergia()
    alto = quadro_de(0.3)
    baixo = quadro_de(0.0)

    assert com.ver(alto) is True
    assert sem.ver(alto) is True
    assert com.ver(baixo) is None, "histerese segura"
    assert sem.ver(baixo) is False, "limiar cru não segura"


def test_o_nome_do_vad_vai_no_relatorio() -> None:
    """Número de VAD de energia nunca se compara com número de silero como se fosse o mesmo."""
    assert VadDeEnergia().nome == "energia@1"
    assert VadSilero().nome == "silero-vad@v5"
    assert DetectorDeEnergia().nome == "limiar-de-energia@1"


def test_sem_o_peso_o_silero_recusa_dizendo_de_onde_baixar(tmp_path: Path) -> None:
    vad = VadSilero(caminho=tmp_path / "nao-existe.onnx")

    with pytest.raises(ModeloIndisponivel, match="silero-vad"):
        vad.abrir()


def test_sem_o_peso_o_ambiente_cai_no_vad_de_energia(tmp_path: Path) -> None:
    escolhido = vad_do_ambiente(caminho=tmp_path / "nao-existe.onnx")

    assert isinstance(escolhido, VadDeEnergia)
    assert escolhido.nome == "energia@1"


@sem_modelo
def test_silero_detecta_fala_e_silencio_do_roteiro_sintetico() -> None:
    roteiro = (
        Trecho(TipoDeTrecho.SILENCIO, 300.0),
        Trecho(TipoDeTrecho.FALA, 600.0),
        Trecho(TipoDeTrecho.SILENCIO, 600.0),
    )
    vad = VadSilero(caminho=MODELO)

    mudancas = [
        (i * MS_POR_QUADRO, m)
        for i, q in enumerate(quadros_de(gerar(roteiro, semente=3)))
        if (m := vad.ver(q)) is not None
    ]

    assert [m for _, m in mudancas] == [True, False]
    inicio = mudancas[0][0]
    assert 300 <= inicio <= 500, f"início em {inicio} ms"
    assert vad.janelas > 0


@sem_modelo
def test_a_janela_do_modelo_e_de_512_amostras_com_64_de_contexto() -> None:
    """O quadro de 20 ms não alinha com a janela de 32 ms: o atraso é inerente e está medido."""
    vad = VadSilero(caminho=MODELO)
    vad.abrir()

    primeiro = vad.ver(quadro_de(0.3, 0))
    segundo = vad.ver(quadro_de(0.3, 1))

    assert JANELA_SILERO == 512
    assert CONTEXTO_SILERO == 64
    assert primeiro is None, "320 amostras não completam a janela de 512"
    assert segundo is not None or vad.janelas == 1


@sem_modelo
def test_zerar_esquece_o_estado_recorrente() -> None:
    vad = VadSilero(caminho=MODELO)
    for quadro in quadros_de(gerar(semente=1))[:20]:
        vad.ver(quadro)

    vad.zerar()

    assert vad.falando is None
    assert vad._buffer == vad._buffer[:0]


def test_antes_de_decidir_o_vad_diz_nao_sei_em_vez_de_dizer_silencio() -> None:
    """`None` é "ainda não sei". Com histerese, declarar silêncio exige os quadros da política.

    Isso importa para quem consome: um `None` no primeiro quadro não é `AudioActivity(false)`,
    e o `audio-io` só publica evento quando há mudança de verdade (F1-03).
    """
    vad = VadDeEnergia(histerese=Histerese(quadros_para_desligar=2, hangover_ms=0.0))
    assert len(quadro_de(0.0).amostras) == BYTES_POR_QUADRO

    assert vad.ver(quadro_de(0.0)) is None
    assert vad.falando is None
    assert vad.ver(quadro_de(0.0)) is False
    assert vad.ultima_probabilidade == 0.0
