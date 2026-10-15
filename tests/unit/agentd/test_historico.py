"""Cartão F1-12: o histórico é o que o dono ouviu — e o log encadeado prova (regra 4 da §3.3)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jarvis.agentd.historico import (
    Historico,
    anexar_ao_log,
    do_log,
    retomar,
    texto_nao_tocado,
)
from jarvis.agentd.turno_completo import NOMES, TurnoCompleto
from jarvis.barramento.envelope import Tipo
from jarvis.barramento.log import CadeiaRompida, LogDeEventos

pytestmark = pytest.mark.cancelamento


@pytest.fixture(scope="module")
def turno() -> TurnoCompleto:
    return TurnoCompleto()


@pytest.mark.parametrize("ponto", NOMES)
def test_o_historico_tem_exatamente_o_prefixo_tocado(ponto: str, turno: TurnoCompleto) -> None:
    """Aceite (a): comparação caractere a caractere com o mapa, nos vinte pontos."""
    resultado = turno.rodar(ponto)

    esperado = resultado.fala.texto_ate(resultado.amostras_tocadas)
    ouvido = resultado.historico.texto_ouvido

    assert ouvido == esperado, f"{ponto}: histórico {ouvido!r} != mapa {esperado!r}"
    assert resultado.fala.texto.startswith(ouvido)


@pytest.mark.parametrize("ponto", NOMES)
def test_o_que_nao_tocou_nao_existe_para_o_modelo(ponto: str, turno: TurnoCompleto) -> None:
    """Aceite (b): o sufixo enfileirado e não tocado tem de estar AUSENTE do histórico."""
    resultado = turno.rodar(ponto)
    sufixo = texto_nao_tocado(resultado.fala, resultado.amostras_tocadas).strip()

    if not sufixo:
        pytest.skip("este ponto não deixou sufixo: a resposta tocou inteira")
    assert not resultado.historico.contem(sufixo), f"{ponto}: {sufixo[:40]!r} apareceu"
    for entrada in resultado.historico.entradas:
        assert sufixo not in entrada.texto


def test_continua_retoma_do_trecho_tocado_e_o_plano_antigo_nao_volta(
    turno: TurnoCompleto,
) -> None:
    """Aceite (c): regra 5 — o modelo decide a retomada do que o dono ouviu."""
    resultado = turno.rodar("no_meio_de_um_pedaco")
    retomada = resultado.retomada

    assert retomada is not None
    assert retomada.ouvido == resultado.historico.texto_ouvido
    assert retomada.contexto == retomada.ouvido, "o contexto é o trecho tocado, e mais nada"
    assert not retomada.ressuscita(resultado.fala.texto), "o plano antigo voltou"
    assert retomada.played_ms > 0
    # E o que não tocou não está em lugar nenhum do que vai para o modelo.
    sufixo = texto_nao_tocado(resultado.fala, resultado.amostras_tocadas).strip()
    assert sufixo and sufixo not in retomada.contexto


def test_o_log_encadeado_mostra_played_ms_e_epoch_de_cada_entrada(tmp_path: Path) -> None:
    """Aceite (d), primeira metade."""
    turno = TurnoCompleto()
    resultado = turno.rodar("no_meio_de_um_pedaco")
    progressos = [e for e in resultado.eventos if e.type is Tipo.PLAYBACK_PROGRESS]
    assert progressos, "a resposta tocou algo antes de ser interrompida"

    with LogDeEventos(tmp_path / "eventos.sqlite") as log:
        seqs = anexar_ao_log(log, progressos)
        assert len(seqs) == len(progressos)
        assert log.verificar_cadeia() == len(progressos)

        registros = [r for r in log.ler() if r.envelope.type is Tipo.PLAYBACK_PROGRESS]
        for registro in registros:
            assert "played_ms" in registro.envelope.payload
            assert "epoch" in registro.envelope.payload
        reconstruido = do_log(log, resultado.fala)

    assert reconstruido.texto_ouvido == resultado.historico.texto_ouvido
    assert reconstruido.played_ms_total == resultado.historico.played_ms_total


def test_adulterar_o_played_ms_quebra_a_cadeia(tmp_path: Path) -> None:
    """Aceite (d), segunda metade: reaproveita a garantia da F0-02."""
    turno = TurnoCompleto()
    resultado = turno.rodar("no_meio_de_um_pedaco")
    progressos = [e for e in resultado.eventos if e.type is Tipo.PLAYBACK_PROGRESS]
    caminho = tmp_path / "eventos.sqlite"

    with LogDeEventos(caminho) as log:
        anexar_ao_log(log, progressos)
        assert log.verificar_cadeia() == len(progressos)

    # Alguém com acesso ao arquivo "corrige" o histórico para o modelo lembrar de mais do que
    # tocou. O log é append-only por gatilho (F0-02), então o UPDATE só passa derrubando os
    # gatilhos — e mesmo assim a cadeia de hash acusa.
    con = sqlite3.connect(caminho, isolation_level=None)
    con.execute("DROP TRIGGER event_log_sem_update")
    con.execute(
        "UPDATE event_log SET payload_json = json_set(payload_json, '$.played_ms', 99999) "
        "WHERE seq = 1"
    )
    con.close()

    with LogDeEventos(caminho) as log, pytest.raises(CadeiaRompida, match="adulterado"):
        log.verificar_cadeia()


def test_o_historico_so_aceita_playback_progress() -> None:
    """Entrada de histórico que não vem de áudio tocado não é entrada de histórico."""
    from jarvis.agentd.tts import Fala
    from jarvis.barramento.envelope import uuid7
    from tests.fabricas import evento

    historico = Historico()
    sessao = uuid7()

    with pytest.raises(ValueError, match="PlaybackProgress"):
        historico.registrar(
            evento(Tipo.FINAL_TRANSCRIPT, sessao), Fala(texto="x"), amostras_tocadas=0
        )


def test_retomada_de_historico_vazio_nao_inventa_contexto() -> None:
    historico = Historico()

    retomada = retomar(historico, epoch=3)

    assert retomada.ouvido == ""
    assert retomada.played_ms == 0
    assert not retomada.ressuscita("Achei três arquivos")
