"""Cartão F1-04: a cadeia AEC → NR → AGC, com os quatro aceites do cartão.

(a) ERLE por condição; (b) **o aceite que importa**: sem AEC o detector dispara no nosso
próprio TTS e com AEC não dispara; (c) troca de dispositivo vira `aec_fail` e o playback para;
(d) deriva de ±100 ppm não trava nem estoura a cadeia.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from jarvis.audio_io import (
    AMOSTRAS_POR_QUADRO,
    TAXA_PADRAO,
    DetectorDeEnergia,
    FilaDePlayback,
    Pedaco,
    SumidouroEmMemoria,
    TipoDeTrecho,
    Trecho,
    gerar,
)
from jarvis.audio_io.aec import CadeiaDeAec, MotivoDeFalha, quadros_de
from jarvis.audio_io.dsp import (
    LIMIAR_DO_DETECTOR_DB,
    CanceladorDeEco,
    ControleDeGanho,
    erle_db,
    para_bytes,
    para_float,
)
from jarvis.audio_io.energia import LIMIAR_PADRAO_DB
from jarvis.barramento.envelope import Tipo

SEGUNDOS = 6.0
CONDICOES = [(atraso, ganho) for atraso in (60, 120, 240) for ganho in (-6, -12, -20)]


def nosso_tts(segundos: float = SEGUNDOS, semente: int = 11) -> np.ndarray[Any, np.dtype[Any]]:
    return para_float(gerar((Trecho(TipoDeTrecho.FALA, segundos * 1000),), semente=semente))


def com_eco(
    referencia: np.ndarray[Any, np.dtype[Any]], *, atraso_ms: int, ganho_db: int
) -> np.ndarray[Any, np.dtype[Any]]:
    atraso = int(TAXA_PADRAO * atraso_ms / 1000)
    atrasada = np.concatenate([np.zeros(atraso), referencia])[: len(referencia)]
    return np.asarray(atrasada * 10.0 ** (ganho_db / 20.0), dtype=np.float64)


def rodar(
    microfone: np.ndarray[Any, np.dtype[Any]],
    referencia: np.ndarray[Any, np.dtype[Any]],
    *,
    cadeia: CadeiaDeAec | None,
    pular_quadros: int = 150,
) -> tuple[np.ndarray[Any, np.dtype[Any]], int]:
    """Passa o microfone pela cadeia (ou não) e conta quadros com fala vistos pelo detector."""
    detector = DetectorDeEnergia()
    residuos: list[np.ndarray[Any, np.dtype[Any]]] = []
    com_fala = 0
    for i, quadro in enumerate(quadros_de(para_bytes(microfone))):
        if cadeia is not None:
            fatia = referencia[i * AMOSTRAS_POR_QUADRO : (i + 1) * AMOSTRAS_POR_QUADRO]
            cadeia.referencia(para_bytes(fatia))
            quadro = cadeia.processar(quadro, tocando=True).quadro
        detector.ver(quadro)
        residuos.append(para_float(quadro.amostras))
        if i >= pular_quadros and detector.falando:
            com_fala += 1
    return np.concatenate(residuos), com_fala


@pytest.mark.parametrize(("atraso_ms", "ganho_db"), CONDICOES)
def test_erle_por_condicao_fica_acima_de_20_db_convergido(atraso_ms: int, ganho_db: int) -> None:
    """Aceite (a): o número publicado em docs/medicoes/f1-04-aec.md é 24 a 39 dB."""
    referencia = nosso_tts()
    microfone = com_eco(referencia, atraso_ms=atraso_ms, ganho_db=ganho_db)

    residuo, _ = rodar(microfone, referencia, cadeia=CadeiaDeAec())

    metade = len(residuo) // 2
    assert erle_db(microfone[metade : len(residuo)], residuo[metade:]) > 20.0


@pytest.mark.parametrize(("atraso_ms", "ganho_db"), CONDICOES)
def test_sem_aec_o_detector_dispara_no_nosso_tts_e_com_aec_nao(
    atraso_ms: int, ganho_db: int
) -> None:
    """Aceite (b), o que importa: primeiro provar o problema, depois provar a solução."""
    referencia = nosso_tts()
    microfone = com_eco(referencia, atraso_ms=atraso_ms, ganho_db=ganho_db)

    _, sem_aec = rodar(microfone, referencia, cadeia=None)
    _, com_aec = rodar(microfone, referencia, cadeia=CadeiaDeAec())

    assert sem_aec > 0, "sem AEC o assistente ouve a si mesmo — é o problema existindo"
    assert com_aec == 0, "com AEC o detector não pode disparar no nosso próprio áudio"


def test_o_limiar_do_agc_e_o_mesmo_do_detector() -> None:
    """Medido no cartão: AGC perseguindo alvo em cima do resíduo desfazia o trabalho da AEC."""
    assert LIMIAR_DO_DETECTOR_DB == LIMIAR_PADRAO_DB
    assert ControleDeGanho().limiar_de_silencio_dbfs == LIMIAR_PADRAO_DB


def test_troca_de_dispositivo_no_meio_marca_aec_fail_e_zera_o_filtro() -> None:
    """Aceite (c), primeira parte: outro caminho acústico, aprendizado velho não serve."""
    referencia = nosso_tts(1.0)
    cadeia = CadeiaDeAec(device_id_de_saida="alsa:0")
    for i, quadro in enumerate(
        quadros_de(para_bytes(com_eco(referencia, atraso_ms=60, ganho_db=-6)))
    ):
        fatia = referencia[i * AMOSTRAS_POR_QUADRO : (i + 1) * AMOSTRAS_POR_QUADRO]
        cadeia.referencia(para_bytes(fatia), device_id="alsa:0")
        cadeia.processar(quadro, tocando=True)
    # Guardado em local de propósito: `assert cadeia.aec_ok` estreitaria o atributo para
    # `Literal[True]` e o mypy (warn_unreachable) passaria a chamar o resto do teste de
    # inalcançável — o atributo muda por efeito da chamada seguinte.
    ok_antes = cadeia.aec_ok
    aprendido = float(np.abs(cadeia.cancelador._pesos).sum())
    assert ok_antes
    assert aprendido > 0.0

    cadeia.referencia(para_bytes(referencia[:AMOSTRAS_POR_QUADRO]), device_id="bluetooth:fone")

    assert not cadeia.aec_ok
    assert cadeia.motivo is MotivoDeFalha.DISPOSITIVO_TROCADO
    assert float(np.abs(cadeia.cancelador._pesos).sum()) == 0.0


def test_referencia_em_outra_taxa_e_recusada() -> None:
    cadeia = CadeiaDeAec()

    cadeia.referencia(para_bytes(nosso_tts(0.1)), taxa=48_000)

    assert not cadeia.aec_ok
    assert cadeia.motivo is MotivoDeFalha.TAXA_DIFERENTE
    assert cadeia.referencia_pendente == 0


def test_tocando_sem_referencia_e_falha_e_parar_de_tocar_limpa() -> None:
    cadeia = CadeiaDeAec()
    quadro = quadros_de(para_bytes(nosso_tts(0.1)))[0]

    cadeia.processar(quadro, tocando=True)
    falhou = (cadeia.aec_ok, cadeia.motivo)
    cadeia.processar(quadro, tocando=False)
    limpou = (cadeia.aec_ok, cadeia.motivo)

    assert falhou == (False, MotivoDeFalha.REFERENCIA_AUSENTE)
    assert limpou == (True, None), "sem playback não há o que cancelar: a falha não sobrevive"


def test_referencia_acumulada_demais_e_atraso_e_nao_fica_em_silencio() -> None:
    cadeia = CadeiaDeAec()

    cadeia.referencia(para_bytes(nosso_tts(5.0)))  # muito mais do que o filtro cobre

    assert not cadeia.aec_ok
    assert cadeia.motivo is MotivoDeFalha.REFERENCIA_ATRASADA
    assert cadeia.referencia_pendente * 2 <= cadeia.limite_de_atraso


def test_playback_pausado_nao_toca_e_nao_descarta() -> None:
    """Aceite (c), segunda parte: com `aec_fail` o assistente para de falar, sem perder a fila."""
    sumidouro = SumidouroEmMemoria()
    fila = FilaDePlayback(sumidouro=sumidouro, session_id="0193f0a0-0000-7000-8000-000000000000")
    fila.enfileirar(Pedaco(chunk_id="k-1", epoch=0, amostras=para_bytes(nosso_tts(0.5))))

    fila.pausado = True
    assert [e for _ in range(10) for e in fila.tick()] == []
    assert sumidouro.amostras_consumidas == 0
    assert fila.pedacos_na_fila == 1

    fila.pausado = False
    fila.tick()
    assert sumidouro.amostras_consumidas == AMOSTRAS_POR_QUADRO


def test_a_referencia_da_fila_de_playback_e_o_que_saiu() -> None:
    """O loopback vem do sumidouro, não do que foi enfileirado (F1-03 + F1-04)."""
    sumidouro = SumidouroEmMemoria()
    fila = FilaDePlayback(sumidouro=sumidouro, session_id="0193f0a0-0000-7000-8000-000000000000")
    cadeia = CadeiaDeAec()
    fila.escuta = cadeia.referencia
    fila.enfileirar(Pedaco(chunk_id="k-1", epoch=0, amostras=para_bytes(nosso_tts(0.5))))

    for _ in range(3):
        fila.tick()

    assert cadeia.amostras_de_referencia == 3 * AMOSTRAS_POR_QUADRO


@pytest.mark.parametrize("ppm", [-100.0, 100.0])
def test_deriva_de_relogio_nao_trava_nem_estoura_a_cadeia(ppm: float) -> None:
    """Aceite (d): ±100 ppm degrada o ERLE, mas a saída continua finita e limitada."""
    referencia = nosso_tts(4.0)
    indices = np.arange(len(referencia)) * (1.0 + ppm / 1e6)
    esticada = np.interp(indices, np.arange(len(referencia)), referencia)
    atraso = int(TAXA_PADRAO * 0.12)
    microfone = np.concatenate([np.zeros(atraso), esticada])[: len(referencia)] * 0.25

    residuo, _ = rodar(microfone, referencia, cadeia=CadeiaDeAec())

    assert bool(np.all(np.isfinite(residuo)))
    assert float(np.max(np.abs(residuo))) <= 1.0
    assert erle_db(microfone[: len(residuo)], residuo) > 10.0


def test_agentd_transforma_aec_ok_falso_em_cancel_aec_fail(sessao: str) -> None:
    """Aceite (c), terceira parte: quem emite Cancel é o agentd (§3.2), não o audio-io."""
    from jarvis.agentd.__main__ import Percepcao
    from jarvis.barramento.epoch import DonoDoEpoch
    from tests.fabricas import evento

    percepcao = Percepcao(DonoDoEpoch(session_id=sessao))

    nada = percepcao(evento(Tipo.AUDIO_ACTIVITY, sessao, speech=False, aec_ok=True), 1)
    falha = percepcao(evento(Tipo.AUDIO_ACTIVITY, sessao, speech=False, aec_ok=False), 2)
    repetido = percepcao(evento(Tipo.AUDIO_ACTIVITY, sessao, speech=False, aec_ok=False), 3)

    assert nada == []
    assert len(falha) == 1
    assert falha[0].type is Tipo.CANCEL
    assert falha[0].payload["reason"] == "aec_fail"
    assert falha[0].source == "agentd"
    assert repetido == [], "a falha avisa uma vez, não a cada quadro"


def test_cancelador_zerado_esquece_o_que_aprendeu() -> None:
    cancelador = CanceladorDeEco()
    referencia = nosso_tts(1.0)
    for i in range(50):
        fatia = referencia[i * AMOSTRAS_POR_QUADRO : (i + 1) * AMOSTRAS_POR_QUADRO]
        cancelador.processar(fatia * 0.5, fatia)

    cancelador.zerar()

    residuo, _ = cancelador.processar(
        referencia[:AMOSTRAS_POR_QUADRO] * 0.5, referencia[:AMOSTRAS_POR_QUADRO]
    )
    assert np.allclose(residuo, referencia[:AMOSTRAS_POR_QUADRO] * 0.5)
