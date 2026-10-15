"""Fusão das três listas por RRF e recuperação completa (SPEC §6.8, passo 3).

Três listas ranqueadas: **densa** (vetor), **léxica** (FTS5) e **grafo** (ativação). O RRF
soma `1/(k+posição)` de cada lista, que é o que permite fundir escores de naturezas
diferentes sem calibrar um contra o outro.

Uma honestidade importante para a medição: a lista densa aqui é **simulada** — sobreposição
de termos, determinística, sem modelo de embedding. O harness da F0-05 mede *custo* da
travessia e da fusão, não *qualidade* de recuperação; qualidade é a medição da §8.1/§8.2, com
corpus anotado, em F3. Onde esta função aparece em número publicado, aparece com essa
ressalva.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from jarvis.memoryd.grafo import TETOS_PADRAO, Ativacao, Tetos, ativar_por_salto, semear_por_termo

K_RRF: Final = 60
"""Constante clássica do Reciprocal Rank Fusion. Calibrável em corpus (§6.8), não mágica."""

PALAVRA: Final = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class Achado:
    """Uma evidência, com a lista que a trouxe e o caminho que a explica."""

    memory_unit_id: str
    texto: str
    escore: float
    fontes: tuple[str, ...]
    caminho: str = ""


@dataclass(slots=True)
class Recuperacao:
    """O que o `s2` recebe. Sempre utilizável, truncado ou não (P9)."""

    achados: list[Achado] = field(default_factory=list)
    graph_truncated: bool = False
    motivo: str = ""
    ms_densa: float = 0.0
    ms_lexica: float = 0.0
    ms_grafo: float = 0.0
    ms_fusao: float = 0.0

    @property
    def ms_total(self) -> float:
        return self.ms_densa + self.ms_lexica + self.ms_grafo + self.ms_fusao


def termos(consulta: str) -> list[str]:
    return [t.casefold() for t in PALAVRA.findall(consulta)]


def buscar_lexico(con: sqlite3.Connection, consulta: str, *, k: int = 8) -> list[str]:
    """FTS5 com bm25 — a lista léxica da §6.8."""
    alvo = " OR ".join(termos(consulta)) or '""'
    linhas = con.execute(
        """
        SELECT m.id AS id
        FROM memory_unit_fts f
        JOIN memory_unit m ON m.rowid = f.rowid
        WHERE memory_unit_fts MATCH ?
        ORDER BY bm25(memory_unit_fts)
        LIMIT ?
        """,
        (alvo, k),
    ).fetchall()
    return [str(linha["id"]) for linha in linhas]


def buscar_densa_simulada(con: sqlite3.Connection, consulta: str, *, k: int = 8) -> list[str]:
    """Stand-in da `MemoryIndex` densa: sobreposição de termos, determinística.

    **Não é medida de qualidade.** Existe para que a fusão tenha três listas de verdade e o
    custo da fusão seja medido com o número real de candidatos.
    """
    alvo = set(termos(consulta))
    linhas = con.execute("SELECT id, text_redacted FROM memory_unit LIMIT 5000").fetchall()
    pontuados = [
        (
            len(alvo & set(termos(str(linha["text_redacted"])))),
            str(linha["id"]),
        )
        for linha in linhas
    ]
    pontuados.sort(key=lambda par: (-par[0], par[1]))
    return [identificador for pontos, identificador in pontuados[:k] if pontos > 0]


def unidades_dos_nos(
    con: sqlite3.Connection, ativacao: Ativacao, *, k: int = 8
) -> list[tuple[str, str]]:
    """Nós ativados → `memory_unit` (pelas menções e pelo texto), com o caminho de cada um."""

    melhores = ativacao.por_energia(k * 4)
    if not melhores:
        return []
    por_entidade = {no.entity_id: no.explicacao for no in melhores}
    linhas = con.execute(
        """
        SELECT m.id AS id, e.id AS entidade
        FROM entity_mention mencao
        JOIN memory_unit m ON m.id = mencao.memory_unit_id
        JOIN entity e ON e.id = mencao.entity_id
        WHERE mencao.status = 'active'
          AND mencao.entity_id IN (SELECT value FROM json_each(?))
        LIMIT ?
        """,
        (json.dumps(list(por_entidade)), k),
    ).fetchall()
    if linhas:
        return [(str(linha["id"]), por_entidade[str(linha["entidade"])]) for linha in linhas]

    # Sem menções materializadas (grafo sintético da F0-05): cai no nome canônico da entidade.
    nomes = con.execute(
        "SELECT id, canonical_name FROM entity WHERE id IN (SELECT value FROM json_each(?))",
        (json.dumps(list(por_entidade)),),
    ).fetchall()
    achados: list[tuple[str, str]] = []
    for linha in nomes[:k]:
        unidade = con.execute(
            "SELECT m.id AS id FROM memory_unit_fts f JOIN memory_unit m ON m.rowid = f.rowid"
            " WHERE memory_unit_fts MATCH ? LIMIT 1",
            (f'"{linha["canonical_name"]}"',),
        ).fetchone()
        if unidade is not None:
            achados.append((str(unidade["id"]), por_entidade[str(linha["id"])]))
    return achados


def rrf(
    listas: Sequence[tuple[str, Sequence[str]]], *, k: int = K_RRF
) -> list[tuple[str, float, tuple[str, ...]]]:
    """Reciprocal Rank Fusion: soma `1/(k+posição)` por lista, mantendo de onde cada um veio."""
    escores: dict[str, float] = {}
    fontes: dict[str, list[str]] = {}
    for nome, itens in listas:
        for posicao, identificador in enumerate(itens, start=1):
            escores[identificador] = escores.get(identificador, 0.0) + 1.0 / (k + posicao)
            fontes.setdefault(identificador, []).append(nome)
    ordenados = sorted(escores.items(), key=lambda par: (-par[1], par[0]))
    return [(i, e, tuple(fontes[i])) for i, e in ordenados]


def recuperar(
    con: sqlite3.Connection,
    consulta: str,
    *,
    tetos: Tetos = TETOS_PADRAO,
    k: int = 8,
    evidencias: int = 8,
) -> Recuperacao:
    """Caminho completo da §6.8 sem reranker: é o que o SLO-12 mede."""
    resultado = Recuperacao()

    inicio = time.monotonic()
    densa = buscar_densa_simulada(con, consulta, k=k)
    resultado.ms_densa = (time.monotonic() - inicio) * 1000.0

    inicio = time.monotonic()
    lexica = buscar_lexico(con, consulta, k=k)
    resultado.ms_lexica = (time.monotonic() - inicio) * 1000.0

    inicio = time.monotonic()
    sementes = semear_por_termo(con, [consulta, *termos(consulta)], limite=k)
    ativacao = ativar_por_salto(con, sementes, tetos) if sementes else Ativacao()
    do_grafo = unidades_dos_nos(con, ativacao, k=k)
    resultado.ms_grafo = (time.monotonic() - inicio) * 1000.0
    resultado.graph_truncated = ativacao.graph_truncated
    resultado.motivo = ativacao.motivo

    inicio = time.monotonic()
    caminhos = dict(do_grafo)
    fundidos = rrf(
        [
            ("densa", densa),
            ("lexica", lexica),
            ("grafo", [identificador for identificador, _ in do_grafo]),
        ]
    )
    textos = {
        str(linha["id"]): str(linha["text_redacted"])
        for linha in con.execute("SELECT id, text_redacted FROM memory_unit")
        if str(linha["id"]) in {i for i, _, _ in fundidos[:evidencias]}
    }
    resultado.achados = [
        Achado(
            memory_unit_id=identificador,
            texto=textos.get(identificador, ""),
            escore=escore,
            fontes=fontes,
            caminho=caminhos.get(identificador, ""),
        )
        for identificador, escore, fontes in fundidos[:evidencias]
    ]
    resultado.ms_fusao = (time.monotonic() - inicio) * 1000.0
    return resultado
