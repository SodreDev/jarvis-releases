"""Aceite F0-02 (e): adulterar um registro do log quebra a verificação da cadeia."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jarvis.barramento import CadeiaRompida, LogDeEventos, Tipo
from jarvis.barramento.log import GENESE
from tests.fabricas import evento


def gravar_alguns(log: LogDeEventos, sessao: str, quantos: int = 5) -> None:
    for i in range(quantos):
        log.anexar(evento(Tipo.FINAL_TRANSCRIPT, sessao, text=f"frase {i}"))


def destravar(caminho: Path) -> sqlite3.Connection:
    """Simula quem tem acesso ao arquivo: derruba os gatilhos e edita o banco direto."""
    con = sqlite3.connect(caminho, isolation_level=None)
    con.execute("DROP TRIGGER event_log_sem_update")
    con.execute("DROP TRIGGER event_log_sem_delete")
    return con


def test_cadeia_de_hash_encadeia_do_genese_ao_ultimo(tmp_path: Path, sessao: str) -> None:
    with LogDeEventos(tmp_path / "eventos.sqlite") as log:
        primeiro = log.anexar(evento(Tipo.AUDIO_ACTIVITY, sessao, speech=True))
        segundo = log.anexar(evento(Tipo.PARTIAL_TRANSCRIPT, sessao))

        assert primeiro.prev_sha256 == GENESE
        assert segundo.prev_sha256 == primeiro.sha256
        assert log.verificar_cadeia() == 2
        assert log.ultimo_hash == segundo.sha256


def test_adulterar_registro_quebra_a_verificacao(tmp_path: Path, sessao: str) -> None:
    """Aceite (e). O UPDATE só passa depois de derrubar o gatilho — e mesmo assim é pego."""
    caminho = tmp_path / "eventos.sqlite"
    with LogDeEventos(caminho) as log:
        gravar_alguns(log, sessao)
        assert log.verificar_cadeia() == 5

    con = destravar(caminho)
    con.execute("UPDATE event_log SET payload_json = ? WHERE seq = 3", ['{"text":"outra coisa"}'])
    con.close()

    with LogDeEventos(caminho) as log, pytest.raises(CadeiaRompida, match="adulterado no seq 3"):
        log.verificar_cadeia()


def test_apagar_registro_quebra_a_verificacao(tmp_path: Path, sessao: str) -> None:
    caminho = tmp_path / "eventos.sqlite"
    with LogDeEventos(caminho) as log:
        gravar_alguns(log, sessao)

    con = destravar(caminho)
    con.execute("DELETE FROM event_log WHERE seq = 3")
    con.close()

    with LogDeEventos(caminho) as log, pytest.raises(CadeiaRompida, match="fora de ordem"):
        log.verificar_cadeia()


def test_banco_recusa_update_e_delete_enquanto_os_gatilhos_estao_de_pe(
    tmp_path: Path, sessao: str
) -> None:
    """Append-only é regra do banco, não boa intenção da aplicação."""
    caminho = tmp_path / "eventos.sqlite"
    with LogDeEventos(caminho) as log:
        gravar_alguns(log, sessao, quantos=2)

    con = sqlite3.connect(caminho, isolation_level=None)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute("UPDATE event_log SET source = 'ui' WHERE seq = 1")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute("DELETE FROM event_log WHERE seq = 1")
    con.close()


def test_log_grava_tudo_inclusive_o_que_o_epoch_descarta(tmp_path: Path, sessao: str) -> None:
    """A auditoria é o log: evento descartado pelo epoch continua registrado (§5.5)."""
    with LogDeEventos(tmp_path / "eventos.sqlite") as log:
        log.anexar(evento(Tipo.PARTIAL_TRANSCRIPT, sessao, epoch=0, text="liga o"))
        log.anexar(evento(Tipo.CANCEL, sessao, epoch=1, epoch_invalidado=0))
        log.anexar(evento(Tipo.POLICY_DECISION, sessao, epoch=0, verdict="deny"))

        tipos = [r.envelope.type for r in log.ler()]

        assert tipos == [Tipo.PARTIAL_TRANSCRIPT, Tipo.CANCEL, Tipo.POLICY_DECISION]
        assert log.verificar_cadeia() == 3


def test_leitura_devolve_o_envelope_identico_ao_gravado(tmp_path: Path, sessao: str) -> None:
    with LogDeEventos(tmp_path / "eventos.sqlite") as log:
        original = evento(Tipo.STATE_REVISION, sessao, epoch=2, objetivo="achar o PDF")
        log.anexar(original)

        lido = next(iter(log.ler(session_id=sessao)))

        assert lido.envelope == original


def test_evento_duplicado_e_recusado_pelo_banco(tmp_path: Path, sessao: str) -> None:
    with LogDeEventos(tmp_path / "eventos.sqlite") as log:
        envelope = evento(Tipo.FINAL_TRANSCRIPT, sessao)
        log.anexar(envelope)

        with pytest.raises(sqlite3.IntegrityError, match="event_id"):
            log.anexar(envelope)
