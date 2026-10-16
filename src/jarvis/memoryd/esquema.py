"""Migração do livro-razão e do grafo (SPEC §6.2, §6.7) a partir de `schemas/memoria.sql`."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Final

from jarvis.dados import caminho

ARQUIVO_ESQUEMA: Final = caminho("schemas/memoria.sql")


def abrir(caminho: Path | str = ":memory:", *, somente_leitura: bool = False) -> sqlite3.Connection:
    """Abre (e migra) o banco de memória. `:memory:` serve para medição e teste."""
    con = sqlite3.connect(caminho, isolation_level=None)
    con.row_factory = sqlite3.Row
    if not somente_leitura:
        con.executescript(ARQUIVO_ESQUEMA.read_text(encoding="utf-8"))
    # Ajustes de leitura: a travessia é curta e repetida, então cache quente importa.
    con.execute("PRAGMA temp_store = MEMORY")
    con.execute("PRAGMA cache_size = -64000")  # 64 MiB
    con.execute("PRAGMA synchronous = NORMAL")
    return con


def contagens(con: sqlite3.Connection) -> dict[str, int]:
    """`n` de cada tabela — o que vai no relatório de medição, nunca número inventado."""
    tabelas = ("episode", "entity", "assertion", "memory_unit", "entity_edge", "entity_mention")
    return {
        tabela: int(con.execute(f"SELECT COUNT(*) AS n FROM {tabela}").fetchone()["n"])  # noqa: S608
        for tabela in tabelas
    }
