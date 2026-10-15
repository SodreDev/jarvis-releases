"""Cartão F1-01, aceite (d): a comparação de trilhas aponta a primeira divergência."""

from __future__ import annotations

from pathlib import Path

from jarvis.audio_io import EventoDeTrilha, atividade
from jarvis.audio_io import trilha as modulo_trilha
from jarvis.barramento.envelope import Prioridade


def evento(
    *, fala: bool = True, epoch: int = 0, ts: int = 20_000_000, energia: float = -18.0
) -> EventoDeTrilha:
    envelope = atividade(
        session_id="0193f0a0-0000-7000-8000-000000000000",
        epoch=epoch,
        device_id="sintetico:0",
        fala=fala,
        energia_db=energia,
        ts_mono_ns=ts,
    )
    return EventoDeTrilha.de_envelope(envelope)


def test_a_trilha_guarda_a_decisao_e_descarta_o_que_muda_sem_significar() -> None:
    linha = evento().para_dict()

    assert set(linha) == {"type", "epoch", "ts_mono_ns", "payload"}
    assert set(linha["payload"]) == {"speech", "device_id", "energy_db", "aec_ok"}
    assert "event_id" not in linha and "ts_wall" not in linha


def test_fala_sai_em_p0_e_nao_fala_em_p1_como_a_secao_3_2_manda() -> None:
    assert (
        atividade(
            session_id="0193f0a0-0000-7000-8000-000000000000",
            epoch=0,
            device_id="d",
            fala=True,
            energia_db=-18.0,
            ts_mono_ns=0,
        ).priority
        is Prioridade.P0
    )
    assert (
        atividade(
            session_id="0193f0a0-0000-7000-8000-000000000000",
            epoch=0,
            device_id="d",
            fala=False,
            energia_db=-80.0,
            ts_mono_ns=0,
        ).priority
        is Prioridade.P1
    )


def test_escrever_e_ler_devolve_a_mesma_trilha(tmp_path: Path) -> None:
    eventos = [evento(fala=False, ts=20_000_000), evento(fala=True, ts=40_000_000)]
    caminho = tmp_path / "t.jsonl"

    modulo_trilha.escrever(caminho, eventos)

    assert modulo_trilha.ler(caminho) == eventos
    assert modulo_trilha.comparar(eventos, modulo_trilha.ler(caminho)) is None


def test_divergencia_de_payload_aponta_indice_e_chave() -> None:
    a = [evento(), evento(fala=True, energia=-18.0)]
    b = [evento(), evento(fala=True, energia=-24.0)]

    divergencia = modulo_trilha.comparar(a, b)

    assert divergencia is not None
    assert divergencia.indice == 1
    assert "payload.energy_db" in str(divergencia)
    assert "-18.0" in str(divergencia) and "-24.0" in str(divergencia)


def test_divergencia_de_tempo_e_de_tipo_vem_antes_do_payload() -> None:
    cedo = modulo_trilha.comparar([evento(ts=20_000_000)], [evento(ts=40_000_000)])
    assert cedo is not None and "ts_mono_ns" in cedo.o_que


def test_trilha_mais_curta_e_divergencia_e_nao_empate() -> None:
    divergencia = modulo_trilha.comparar([evento()], [evento(), evento(fala=False)])

    assert divergencia is not None
    assert divergencia.indice == 1
    assert "tamanhos diferentes" in divergencia.o_que
