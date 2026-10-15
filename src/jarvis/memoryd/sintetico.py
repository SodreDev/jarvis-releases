"""Gerador de grafo sintético para o harness da F0-05.

Dimensionado pelo corpus real do dono: `n` base vem da contagem de memórias que o
Orchestrator guarda hoje para este projeto (ver `docs/medicoes/`), e as escalas 10× e 100×
multiplicam episódios, entidades e arestas na mesma proporção.

O gerador é **determinístico** (semente fixa): a medição de amanhã mede o mesmo grafo.
"""

from __future__ import annotations

import math
import random
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

RELACOES: Final = ("menciona", "trabalha_em", "mora_em", "usa_app", "arquivo_de", "falou_com")
TIPOS: Final = ("pessoa", "projeto", "arquivo", "app", "lugar", "tema")
SEMENTE_PADRAO: Final = 20261015


@dataclass(frozen=True, slots=True)
class Escala:
    """Tamanho do grafo gerado. `fator` 1 é o corpus do dono; 10 e 100 são as projeções."""

    nome: str
    episodios: int
    entidades: int
    arestas: int
    fator: int

    @classmethod
    def de_corpus(cls, nome: str, *, episodios_base: int, fator: int) -> Escala:
        """Razões declaradas: 3 entidades e 8 arestas por episódio.

        **[SUPOSIÇÃO]** calibrada pelo que uma memória do Orchestrator costuma citar
        (pessoa, projeto, arquivo). O cartão F0-08 substitui isso pela contagem real do
        exportador; a forma do grafo (grau médio ~5) é o que a travessia sente.
        """
        episodios = episodios_base * fator
        return cls(
            nome=nome,
            episodios=episodios,
            entidades=episodios * 3,
            arestas=episodios * 8,
            fator=fator,
        )


def gerar(
    con: sqlite3.Connection,
    escala: Escala,
    *,
    semente: int = SEMENTE_PADRAO,
    hub_grau: int = 0,
) -> dict[str, int]:
    """Preenche o banco com um grafo sintético. Devolve as contagens reais inseridas.

    `hub_grau` > 0 cria um nó com esse grau (o teste do aceite (c) usa 10 000) para provar
    que a penalidade de hub e os tetos seguram a travessia.
    """
    # Gerador de grafo de teste: a semente é fixa de propósito, para a medição ser
    # repetível. Nada aqui é segredo nem vai para produção.
    sorteio = random.Random(semente)  # noqa: S311
    agora = datetime(2026, 10, 15, tzinfo=UTC)

    episodios = [f"ep-{i:07d}" for i in range(escala.episodios)]
    entidades = [f"en-{i:07d}" for i in range(escala.entidades)]

    con.execute("BEGIN")
    con.executemany(
        "INSERT INTO episode (id, occurred_at, ingested_at, session_id, actor, source, kind,"
        " sha256, trust) VALUES (?, ?, ?, 'sessao-sintetica', 'dono', 'orchestrator',"
        " 'memoria', ?, 'user_ui')",
        [
            (
                ep,
                (agora - timedelta(hours=i)).isoformat(),
                agora.isoformat(),
                f"{i:064x}",
            )
            for i, ep in enumerate(episodios)
        ],
    )
    con.executemany(
        "INSERT INTO entity (id, type, canonical_name, created_at) VALUES (?, ?, ?, ?)",
        [
            (en, TIPOS[i % len(TIPOS)], f"entidade {i}", agora.isoformat())
            for i, en in enumerate(entidades)
        ],
    )
    con.executemany(
        "INSERT INTO entity_resolution (alias_norm, entity_id, score, method)"
        " VALUES (?, ?, 1.0, 'exato')",
        [(f"entidade {i}", en) for i, en in enumerate(entidades)],
    )
    con.executemany(
        "INSERT INTO memory_unit (id, episode_id, text_redacted, content_hash) VALUES (?, ?, ?, ?)",
        [
            (
                f"mu-{i:07d}",
                ep,
                f"nota {i} sobre entidade {i % len(entidades)} e entidade "
                f"{(i * 7) % len(entidades)}",
                f"{i:064x}",
            )
            for i, ep in enumerate(episodios)
        ],
    )

    arestas: list[tuple[str, str, str, str, str, float, str, float, int]] = []
    for i in range(escala.arestas):
        src = entidades[sorteio.randrange(len(entidades))]
        dst = entidades[sorteio.randrange(len(entidades))]
        if src == dst:
            continue
        arestas.append(
            (
                f"ed-{i:08d}",
                src,
                RELACOES[i % len(RELACOES)],
                dst,
                episodios[i % len(episodios)],
                round(sorteio.uniform(0.5, 1.0), 3),
                (agora - timedelta(days=sorteio.randrange(0, 400))).isoformat(),
                round(sorteio.uniform(0.3, 1.0), 3),
                sorteio.randrange(1, 5),
            )
        )
    if hub_grau > 0:
        hub = entidades[0]
        for j in range(hub_grau):
            arestas.append(
                (
                    f"ed-hub-{j:08d}",
                    hub,
                    "menciona",
                    entidades[(j + 1) % len(entidades)],
                    episodios[j % len(episodios)],
                    0.9,
                    agora.isoformat(),
                    0.9,
                    3,
                )
            )

    con.executemany(
        "INSERT INTO entity_edge (id, src, relation, dst, source_episode_id, confidence,"
        " valid_from, weight, support_count, status, last_seen_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
        [(*linha, agora.isoformat()) for linha in arestas],
    )
    con.execute("COMMIT")

    atualizar_graus(con)
    indexar_fts(con)
    return {
        "episodios": len(episodios),
        "entidades": len(entidades),
        "arestas": len(arestas),
        "unidades": len(episodios),
    }


def atualizar_graus(con: sqlite3.Connection) -> None:
    """Recalcula `graph_node_stats` — a §6.7 manda fazer isso em ociosidade, não na consulta."""
    con.executescript(
        """
        DELETE FROM graph_node_stats;
        INSERT INTO graph_node_stats (entity_id, degree, hubness, updated_at)
        SELECT entity_id, COUNT(*) AS grau, 0.0, datetime('now')
        FROM (
            SELECT src AS entity_id FROM entity_edge WHERE status = 'active'
            UNION ALL
            SELECT dst AS entity_id FROM entity_edge WHERE status = 'active'
        )
        GROUP BY entity_id;
        """
    )
    con.execute("UPDATE graph_node_stats SET hubness = 1.0 / (1.0 + ?) * degree", (math.e,))


def indexar_fts(con: sqlite3.Connection) -> None:
    con.execute("INSERT INTO memory_unit_fts (memory_unit_fts) VALUES ('rebuild')")
