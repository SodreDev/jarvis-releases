"""Esquema do livro-razão e do grafo (SPEC §6.2, §6.7) — cartão F0-05."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from jarvis.memoryd.esquema import abrir, contagens

TABELAS_DA_SPEC = (
    "episode",
    "entity",
    "assertion",
    "memory_unit",
    "procedure",
    "entity_edge",
    "outbox",
    "entity_mention",
    "entity_resolution",
    "graph_node_stats",
)
INDICES_OBRIGATORIOS = (
    "entity_edge_src",
    "entity_edge_dst",
    "assertion_sujeito",
    "memory_unit_assertion",
    "entity_mention_entidade",
    "entity_resolution_alias",
)


@pytest.fixture
def con() -> Iterator[sqlite3.Connection]:
    conexao = abrir()
    yield conexao
    conexao.close()


def test_todas_as_tabelas_da_spec_existem(con: sqlite3.Connection) -> None:
    existentes = {
        str(linha["name"])
        for linha in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }

    assert set(TABELAS_DA_SPEC) <= existentes


def test_indices_obrigatorios_da_secao_6_7_existem(con: sqlite3.Connection) -> None:
    existentes = {
        str(linha["name"])
        for linha in con.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }

    assert set(INDICES_OBRIGATORIOS) <= existentes


def test_busca_lexica_fts5_existe(con: sqlite3.Connection) -> None:
    assert con.execute("SELECT name FROM sqlite_master WHERE name = 'memory_unit_fts'").fetchone()


def test_fato_sem_episodio_e_recusado_pelo_banco(con: sqlite3.Connection) -> None:
    """Integridade (a) da §6.2: todo fato aponta para ≥1 episódio."""
    con.execute(
        "INSERT INTO entity (id, type, canonical_name, created_at) VALUES"
        " ('en-1', 'pessoa', 'Sodre', '2026-10-15')"
    )

    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO assertion (id, subject_entity, predicate, value_json, confidence,"
            " observed_at, valid_from, status, source_episode_id) VALUES"
            " ('as-1', 'en-1', 'mora_em', '\"Pato Branco\"', 0.9, '2026-10-15',"
            " '2026-10-15', 'active', 'ep-inexistente')"
        )


def test_estado_de_assertiva_fora_do_vocabulario_e_recusado(con: sqlite3.Connection) -> None:
    con.executescript(
        "INSERT INTO episode (id, occurred_at, ingested_at, session_id, actor, source, kind,"
        " sha256, trust) VALUES ('ep-1', '2026-10-15', '2026-10-15', 's', 'dono', 'voz',"
        " 'fala', 'abc', 'user_voice');"
        "INSERT INTO entity (id, type, canonical_name, created_at) VALUES"
        " ('en-1', 'pessoa', 'Sodre', '2026-10-15');"
    )

    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO assertion (id, subject_entity, predicate, value_json, confidence,"
            " observed_at, valid_from, status, source_episode_id) VALUES"
            " ('as-1', 'en-1', 'p', '1', 0.5, '2026-10-15', '2026-10-15', 'talvez', 'ep-1')"
        )


def test_confianca_fora_de_zero_a_um_e_recusada(con: sqlite3.Connection) -> None:
    con.executescript(
        "INSERT INTO episode (id, occurred_at, ingested_at, session_id, actor, source, kind,"
        " sha256, trust) VALUES ('ep-1', '2026-10-15', '2026-10-15', 's', 'dono', 'voz',"
        " 'fala', 'abc', 'user_voice');"
        "INSERT INTO entity (id, type, canonical_name, created_at) VALUES"
        " ('en-1', 'pessoa', 'Sodre', '2026-10-15');"
        "INSERT INTO entity (id, type, canonical_name, created_at) VALUES"
        " ('en-2', 'lugar', 'Pato Branco', '2026-10-15');"
    )

    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO entity_edge (id, src, relation, dst, source_episode_id, valid_from,"
            " confidence, status) VALUES ('ed-1', 'en-1', 'mora_em', 'en-2', 'ep-1',"
            " '2026-10-15', 1.4, 'active')"
        )


def test_contagens_reporta_n_de_cada_tabela(con: sqlite3.Connection) -> None:
    valores = contagens(con)

    assert valores["episode"] == 0
    assert set(valores) == {
        "episode",
        "entity",
        "assertion",
        "memory_unit",
        "entity_edge",
        "entity_mention",
    }
