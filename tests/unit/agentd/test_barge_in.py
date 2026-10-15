"""Cartão F1-10: o caminho inteiro da regra 1, e nenhum salto esperando o ASR."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.agentd.barge_in import (
    SALTOS,
    SLO2_P95_MS,
    Interrupcao,
    cenario_para,
    extrair_slo2,
)
from jarvis.agentd.tts import MotorParametrico
from jarvis.audio_io.vad import Histerese, VadDeEnergia
from jarvis.barramento.envelope import Prioridade, Tipo
from jarvis.corpus.rotulos import Rotulo, ler_rotulos
from jarvis.corpus.sintetico import gerar_corpus
from jarvis.corpus.voz import VozParametrica


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    pasta = tmp_path_factory.mktemp("corpus-barge-in")
    gerar_corpus(6, semente=21, pasta=pasta, voz=VozParametrica(), fracao_ruido=0.0, fracao_eco=0.0)
    return pasta


@pytest.fixture(scope="module")
def rotulos(corpus: Path) -> list[Rotulo]:
    return ler_rotulos(corpus / "rotulos.jsonl")


def interromper(corpus: Path, rotulo: Rotulo, *, transcritor_lento_ms: float = 0.0) -> Interrupcao:
    cenario = cenario_para(
        rotulo,
        corpus,
        MotorParametrico(),
        vad=lambda: VadDeEnergia(histerese=Histerese()),
        transcritor_lento_ms=transcritor_lento_ms,
    )
    return cenario.rodar()


def test_o_caminho_inteiro_tem_um_marcador_por_salto(corpus: Path, rotulos: list[Rotulo]) -> None:
    resultado = interromper(corpus, rotulos[0])

    assert [s.nome for s in resultado.saltos] == list(SALTOS)


def test_o_cancel_sai_em_p0_e_a_fila_fica_vazia(corpus: Path, rotulos: list[Rotulo]) -> None:
    resultado = interromper(corpus, rotulos[0])
    tipos = [e.type for e in resultado.eventos]

    assert Tipo.CANCEL in tipos
    cancelamento = next(e for e in resultado.eventos if e.type is Tipo.CANCEL)
    assert cancelamento.priority is Prioridade.P0
    assert resultado.amostras_descartadas > 0, "havia resposta em curso para descartar"
    assert resultado.amostras_tocadas > 0, "o assistente estava falando antes da interrupção"


def test_o_slo2_conta_do_inicio_real_da_fala(corpus: Path, rotulos: list[Rotulo]) -> None:
    """Se o VAD demora, o atraso é do dono — não se conta do instante em que percebemos."""
    resultado = interromper(corpus, rotulos[0])

    assert resultado.atraso_do_vad_ms > 0.0
    assert resultado.slo2_ms >= resultado.atraso_do_vad_ms
    assert resultado.slo2_com_codigo_ms >= resultado.slo2_ms


def test_nenhum_salto_espera_o_asr(corpus: Path, rotulos: list[Rotulo]) -> None:
    """Aceite (b): ASR atrasado em 2 s, SLO-2 intacto. Quem garante é a ORDEM da regra 1."""
    normal = interromper(corpus, rotulos[0])
    lento = interromper(corpus, rotulos[0], transcritor_lento_ms=2000.0)

    assert lento.slo2_ms == normal.slo2_ms
    assert lento.slo2_com_codigo_ms == pytest.approx(
        normal.slo2_com_codigo_ms,
        abs=5.0,
    )


def test_o_piso_de_software_cabe_no_slo2(corpus: Path, rotulos: list[Rotulo]) -> None:
    """Aceite (d) pelo lado bom: se estourasse, o cartão terminaria em precisa_decisao."""
    interrupcoes = [interromper(corpus, r) for r in rotulos]

    resumo = extrair_slo2(interrupcoes)

    assert resumo["n"] == len(rotulos)
    assert resumo["slo2_p95"] < SLO2_P95_MS, "o gatilho da ADR-0014 abriria aqui"


def test_a_decomposicao_mostra_quem_gasta_o_que(corpus: Path, rotulos: list[Rotulo]) -> None:
    """Aceite (c): otimizar depois não pode ser chute."""
    resultado = interromper(corpus, rotulos[0])

    por_audio = resultado.decomposicao_ms()
    por_cpu = resultado.decomposicao_us()

    assert len(por_audio) == len(SALTOS) - 1
    assert por_audio["fala_comecou→vad_detectou"] > 0.0, "o VAD é quem gasta tempo de áudio"
    assert sum(v for k, v in por_audio.items() if k != "fala_comecou→vad_detectou") == 0.0, (
        "os saltos depois da detecção caem no mesmo tique de 20 ms"
    )
    assert sum(por_cpu.values()) > 0.0, "e gastam CPU, que é o que é nosso para otimizar"
