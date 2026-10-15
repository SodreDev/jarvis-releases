"""Cartão F1-03, aceite (d): o botão de privacidade corta na fonte, não na interface."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

from jarvis.audio_io import (
    AMOSTRAS_POR_QUADRO,
    PISO_DB,
    TAXA_PADRAO,
    Captura,
    DetectorDeEnergia,
    FonteSintetica,
    Quadro,
    TipoDeTrecho,
    Trecho,
)
from jarvis.barramento.envelope import Prioridade, Tipo
from jarvis.relogio import RelogioFalso

SESSAO = "0193f0a0-0000-7000-8000-000000000000"
ROTEIRO = (
    Trecho(TipoDeTrecho.SILENCIO, 100.0),
    Trecho(TipoDeTrecho.FALA, 400.0),
    Trecho(TipoDeTrecho.SILENCIO, 200.0),
)


@dataclass(slots=True)
class FonteContada:
    """Conta quantas amostras **saíram da fonte** — é o que o aceite (d) manda contar."""

    interna: FonteSintetica
    device_id: str = "contada:0"
    taxa: int = TAXA_PADRAO
    amostras_entregues: int = 0
    quadros_entregues: int = 0
    _origem: Iterator[Quadro] | None = field(default=None, repr=False)

    def abrir(self) -> None:
        self.interna.abrir()
        self._origem = iter(self.interna.quadros())

    def quadros(self) -> Iterator[Quadro]:
        assert self._origem is not None
        for quadro in self._origem:
            self.quadros_entregues += 1
            self.amostras_entregues += quadro.n_amostras
            yield quadro

    def fechar(self) -> None:
        self.interna.fechar()


def montar() -> tuple[Captura, FonteContada]:
    relogio = RelogioFalso()
    fonte = FonteContada(interna=FonteSintetica(relogio=relogio, semente=3, roteiro=ROTEIRO))
    captura = Captura(
        fonte=fonte,
        relogio=relogio,
        session_id=SESSAO,
        detector=DetectorDeEnergia(),
    )
    captura.abrir()
    return captura, fonte


def test_cada_tick_e_um_quadro_de_20_ms_com_device_id_e_energia() -> None:
    captura, fonte = montar()

    eventos = [e for _ in range(5) for e in captura.tick()]

    assert captura.quadros == 5
    assert captura.amostras_capturadas == 5 * AMOSTRAS_POR_QUADRO
    assert fonte.amostras_entregues == 5 * AMOSTRAS_POR_QUADRO
    assert eventos[0].type is Tipo.AUDIO_ACTIVITY
    assert eventos[0].payload["device_id"] == "contada:0"
    assert eventos[0].payload["energy_db"] == PISO_DB
    assert eventos[0].payload["aec_ok"] is True


def test_inicio_de_fala_sai_em_p0() -> None:
    captura, _ = montar()

    eventos = [e for _ in range(20) for e in captura.tick()]
    fala = [e for e in eventos if e.payload["speech"]]

    assert fala, "a fala simulada do roteiro tem de ser vista"
    assert all(e.priority is Prioridade.P0 for e in fala)


def test_privacidade_ligada_nao_tira_uma_amostra_da_fonte() -> None:
    """Aceite (d), a parte que conta bytes."""
    captura, fonte = montar()
    for _ in range(10):
        captura.tick()
    entregues = fonte.amostras_entregues

    captura.ligar_privacidade()
    eventos = [e for _ in range(25) for e in captura.tick()]

    assert fonte.amostras_entregues == entregues, "nenhuma amostra nova saiu da fonte"
    assert captura.ticks_em_privacidade == 25
    assert captura.quadros == 10
    # Um único anúncio de fim de fala, e depois silêncio de eventos.
    assert len(eventos) <= 1
    assert all(e.payload["speech"] is False for e in eventos)


def test_ligar_privacidade_no_meio_da_fala_anuncia_o_fim_uma_vez_so() -> None:
    captura, _ = montar()
    while not captura.detector.falando:
        captura.tick()

    captura.ligar_privacidade()
    primeiro = captura.tick()
    depois = [e for _ in range(10) for e in captura.tick()]

    assert len(primeiro) == 1
    assert primeiro[0].payload["speech"] is False
    assert primeiro[0].payload["energy_db"] == PISO_DB
    assert depois == []


def test_desligar_a_privacidade_volta_a_capturar() -> None:
    captura, fonte = montar()
    captura.tick()
    captura.ligar_privacidade()
    captura.tick()
    entregues = fonte.amostras_entregues

    captura.desligar_privacidade()
    captura.tick()

    assert fonte.amostras_entregues == entregues + AMOSTRAS_POR_QUADRO


def test_o_tempo_do_evento_e_o_do_quadro_e_o_epoch_vai_no_envelope() -> None:
    captura, _ = montar()
    captura.epoch = 4

    eventos = [e for _ in range(3) for e in captura.tick()]

    assert eventos[0].epoch == 4
    assert eventos[0].ts_mono_ns == 20_000_000


def test_captura_nao_aberta_recusa_em_vez_de_devolver_silencio() -> None:
    relogio = RelogioFalso()
    captura = Captura(
        fonte=FonteSintetica(relogio=relogio, semente=1),
        relogio=relogio,
        session_id=SESSAO,
    )

    with pytest.raises(RuntimeError, match="não foi aberta"):
        captura.tick()


def test_fonte_esgotada_para_de_entregar_sem_erro() -> None:
    captura, _ = montar()
    total = sum(t.duracao_ms for t in ROTEIRO) / 20

    for _ in range(int(total) + 5):
        captura.tick()

    assert captura.quadros == int(total)
    assert captura.tick() == []
