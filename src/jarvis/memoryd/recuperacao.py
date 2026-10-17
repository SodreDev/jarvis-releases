"""A recuperação da memória do cérebro (SPEC §6.8), com os três braços da medição §8.2.

- **A — vetor puro:** só a lista densa da `MemoryIndex`.
- **B — híbrido:** densa ∪ léxica (FTS5) → RRF.
- **C — grafo+vetor:** B + ativação por propagação, semeada (1a) pelos nomes e apelidos que a
  consulta cita e (1b) pelas entidades que os acertos densos mencionam.

Sem reranker e sem MMR nesta fatia: o reranker comercial (ADR-0011) ainda não está baixado
nem medido, e o SLO-12 é **sem** reranker. Tudo filtra por memória **ativa e vigente** no
instante da pergunta (gate 4): o índice filtra `tipo`/`status` antes do ranking, a validade
temporal é conferida no livro.

**Abstinência (passo 5):** se o melhor cosseno denso fica abaixo do limiar **e** o grafo não
trouxe evidência nova, a resposta é "não encontrei" — lista vazia, nunca lembrança inventada.
"Nova" é a que veio de uma entidade que a **pergunta** nomeia (1a): a propagação a partir dos
próprios acertos densos (1b) acha sempre alguma coisa, e não é evidência independente deles —
contá-la zerava a abstinência (primeira rodada da medição §8.2).

Os parâmetros (braço, limiar, saltos, acumular) saem de `parametros.toml`, calibrados em 70% do
corpus da medição e reportados nos 30% retidos (`docs/medicoes/f3-02-grafo.md`).
"""

from __future__ import annotations

import json
import sqlite3
import time
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Literal

from jarvis.memoryd.fusao import K_RRF, rrf, termos
from jarvis.memoryd.grafo import Tetos, ativar_por_salto
from jarvis.memoryd.indice import MemoryIndex
from jarvis.politica.memoria import normalizar

Braco = Literal["A", "B", "C"]
ARQUIVO_DE_PARAMETROS: Final = Path(__file__).with_name("parametros.toml")
SO_MEMORIA_ATIVA: Final = {"tipo": "memoria", "status": "active"}
CAMINHOS_POR_EVIDENCIA: Final = 3
MAIOR_APELIDO: Final = 4
"""Apelido com até 4 palavras ("Escritório Nogueira & Lima" normaliza para 4)."""


@dataclass(frozen=True, slots=True)
class Parametros:
    braco: Braco = "B"
    k_lista: int = 40
    """Top 40 léxico + top 40 denso, como a §6.3."""
    limiar: float = 0.0
    acumular: bool = True
    tetos: Tetos = field(default_factory=lambda: Tetos(saltos=1))
    k_rrf: int = K_RRF

    @classmethod
    def do_arquivo(cls, arquivo: Path = ARQUIVO_DE_PARAMETROS) -> Parametros:
        dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
        bruto = dados["recuperacao"]
        return cls(
            braco=bruto["braco"],
            k_lista=int(bruto["k_lista"]),
            limiar=float(bruto["limiar"]),
            acumular=bool(bruto["acumular"]),
            tetos=Tetos(saltos=int(bruto["saltos"]), orcamento_ms=float(bruto["orcamento_ms"])),
        )

    def com(self, **mudancas: Any) -> Parametros:
        return replace(self, **mudancas)


@dataclass(frozen=True, slots=True)
class Evidencia:
    memory_unit_id: str
    escore: float
    fontes: tuple[str, ...]
    caminho: str


@dataclass(slots=True)
class Lembranca:
    """O que o cérebro recebe: evidências ranqueadas, ou a abstinência dita."""

    evidencias: list[Evidencia] = field(default_factory=list)
    abstencao: bool = False
    melhor_cosseno: float = 0.0
    grafo_trouxe_novas: bool = False
    """O grafo achou evidência que nem a densa nem a léxica tinham (passo 5: não abster)."""
    graph_truncated: bool = False
    motivo: str = ""
    ms_densa: float = 0.0
    ms_lexica: float = 0.0
    ms_grafo: float = 0.0
    ms_fusao: float = 0.0

    @property
    def ms_total(self) -> float:
        return self.ms_densa + self.ms_lexica + self.ms_grafo + self.ms_fusao


def _vigentes(con: sqlite3.Connection, ids: Sequence[str], instante: str) -> set[str]:
    if not ids:
        return set()
    return {
        str(linha["id"])
        for linha in con.execute(
            "SELECT m.id FROM memory_unit m JOIN assertion a ON a.id = m.assertion_id"
            " WHERE m.id IN (SELECT value FROM json_each(?)) AND a.status = 'active'"
            " AND a.valid_from <= ? AND (a.valid_to IS NULL OR a.valid_to > ?)",
            (json.dumps(list(ids)), instante, instante),
        )
    }


def lexico_de_memoria(
    con: sqlite3.Connection, consulta: str, *, k: int, instante: str
) -> list[str]:
    """FTS5/bm25 só sobre memória ativa e vigente."""
    alvo = " OR ".join(f'"{t}"' for t in termos(consulta))
    if not alvo:
        return []
    return [
        str(linha["id"])
        for linha in con.execute(
            "SELECT m.id FROM memory_unit_fts f JOIN memory_unit m ON m.rowid = f.rowid"
            " JOIN assertion a ON a.id = m.assertion_id"
            " WHERE memory_unit_fts MATCH ? AND a.status = 'active' AND a.valid_from <= ?"
            " AND (a.valid_to IS NULL OR a.valid_to > ?)"
            " ORDER BY bm25(memory_unit_fts) LIMIT ?",
            (alvo, instante, instante, k),
        )
    ]


def semear_por_apelido(con: sqlite3.Connection, consulta: str) -> list[tuple[str, float]]:
    """Passo 1a: n-gramas da consulta (até 4 palavras) → `entity_resolution`, exato."""
    palavras = normalizar(consulta).split()
    gramas = {
        " ".join(palavras[i : i + n])
        for n in range(1, MAIOR_APELIDO + 1)
        for i in range(len(palavras) - n + 1)
    }
    if not gramas:
        return []
    return [
        (str(linha["entity_id"]), float(linha["score"]))
        for linha in con.execute(
            "SELECT r.entity_id, MAX(r.score) AS score FROM entity_resolution r"
            " JOIN entity e ON e.id = r.entity_id WHERE e.status = 'active'"
            " AND r.alias_norm IN (SELECT value FROM json_each(?)) GROUP BY r.entity_id",
            (json.dumps(sorted(gramas)),),
        )
    ]


def entidades_das_unidades(
    con: sqlite3.Connection, pesos: dict[str, float]
) -> list[tuple[str, float]]:
    """Passo 1b: acertos densos → as entidades que eles mencionam, com o peso do acerto."""
    if not pesos:
        return []
    sementes: dict[str, float] = {}
    for linha in con.execute(
        "SELECT memory_unit_id, entity_id FROM entity_mention WHERE status = 'active'"
        " AND memory_unit_id IN (SELECT value FROM json_each(?))",
        (json.dumps(list(pesos)),),
    ):
        entidade = str(linha["entity_id"])
        sementes[entidade] = max(sementes.get(entidade, 0.0), pesos[str(linha["memory_unit_id"])])
    return list(sementes.items())


def unidades_por_energia(
    con: sqlite3.Connection, energia: dict[str, float], caminhos: dict[str, str], *, k: int
) -> list[tuple[str, tuple[str, ...]]]:
    """Nós ativados → `memory_unit` que os mencionam, pela **soma** da energia das entidades
    citadas (a unidade que cita duas entidades ativadas vem antes da que cita uma). Cada uma
    leva os caminhos das (até) três entidades mais energizadas que ela cita."""
    if not energia:
        return []
    soma: dict[str, float] = {}
    citadas: dict[str, list[tuple[float, str]]] = {}
    for linha in con.execute(
        "SELECT memory_unit_id AS unidade, entity_id FROM entity_mention"
        " WHERE status = 'active' AND memory_unit_id IS NOT NULL"
        " AND entity_id IN (SELECT value FROM json_each(?))",
        (json.dumps(list(energia)),),
    ):
        unidade, entidade = str(linha["unidade"]), str(linha["entity_id"])
        soma[unidade] = soma.get(unidade, 0.0) + energia[entidade]
        citadas.setdefault(unidade, []).append((energia[entidade], caminhos[entidade]))
    ordenadas = sorted(soma, key=lambda u: (-soma[u], u))
    return [
        (
            u,
            tuple(
                c
                for _, c in sorted(citadas[u], key=lambda x: (-x[0], x[1]))[:CAMINHOS_POR_EVIDENCIA]
            ),
        )
        for u in ordenadas[:k]
    ]


def lembrar(
    con: sqlite3.Connection,
    indice: MemoryIndex,
    consulta: str,
    *,
    instante: str,
    parametros: Parametros,
    evidencias: int = 8,
) -> Lembranca:
    """Caminho da §6.8 sem reranker: é o que o SLO-12 mede e o que o cérebro chama a cada turno."""
    resultado = Lembranca()
    k = parametros.k_lista

    inicio = time.monotonic()
    acertos = indice.search(consulta, k, onde=SO_MEMORIA_ATIVA)
    validos = _vigentes(con, [a.id for a in acertos], instante)
    densos = [a for a in acertos if a.id in validos]
    resultado.melhor_cosseno = densos[0].score if densos else 0.0
    resultado.ms_densa = (time.monotonic() - inicio) * 1000.0

    listas: list[tuple[str, Sequence[str]]] = [("densa", [a.id for a in densos])]
    if parametros.braco in ("B", "C"):
        inicio = time.monotonic()
        listas.append(("lexica", lexico_de_memoria(con, consulta, k=k, instante=instante)))
        resultado.ms_lexica = (time.monotonic() - inicio) * 1000.0

    caminhos_do_grafo: dict[str, tuple[str, ...]] = {}
    novas_do_grafo = False
    if parametros.braco == "C":
        inicio = time.monotonic()
        topo = resultado.melhor_cosseno or 1.0
        citadas = dict(semear_por_apelido(con, consulta))
        sementes = dict(citadas)
        for entidade, peso in entidades_das_unidades(
            con, {a.id: max(a.score, 0.0) / topo for a in densos[:8]}
        ):
            sementes[entidade] = max(sementes.get(entidade, 0.0), peso)
        if sementes:
            ativacao = ativar_por_salto(
                con,
                sorted(sementes.items(), key=lambda s: -s[1]),
                parametros.tetos,
                instante=instante,
                acumular=parametros.acumular,
            )
            resultado.graph_truncated = ativacao.graph_truncated
            resultado.motivo = ativacao.motivo
            energia = {n.entity_id: n.energia for n in ativacao.nos}
            nomes = {n.entity_id: n.explicacao for n in ativacao.nos}
            do_grafo = unidades_por_energia(con, energia, nomes, k=k)
            vigentes = _vigentes(con, [u for u, _ in do_grafo], instante)
            do_grafo = [(u, c) for u, c in do_grafo if u in vigentes]
            caminhos_do_grafo = dict(do_grafo)
            ja = {i for _, lista in listas for i in lista}
            # só conta como evidência nova o que veio de entidade que a PERGUNTA cita (1a):
            # o que o grafo espalha a partir dos acertos densos (1b) não é independente deles
            novas_do_grafo = bool(citadas) and any(u not in ja for u, _ in do_grafo)
            resultado.grafo_trouxe_novas = novas_do_grafo
            listas.append(("grafo", [u for u, _ in do_grafo]))
        resultado.ms_grafo = (time.monotonic() - inicio) * 1000.0

    inicio = time.monotonic()
    if resultado.melhor_cosseno < parametros.limiar and not novas_do_grafo:
        resultado.abstencao = True
    else:
        nomes_das_entidades = _nomes(con, [c for cs in caminhos_do_grafo.values() for c in cs])
        resultado.evidencias = [
            Evidencia(
                memory_unit_id=unidade,
                escore=escore,
                fontes=fontes,
                caminho=_explicar(unidade, fontes, caminhos_do_grafo, nomes_das_entidades),
            )
            for unidade, escore, fontes in rrf(listas, k=parametros.k_rrf)[:evidencias]
        ]
    resultado.ms_fusao = (time.monotonic() - inicio) * 1000.0
    return resultado


def _nomes(con: sqlite3.Connection, caminhos: Any) -> dict[str, str]:
    ids = {parte.split("→")[-1] for caminho in caminhos for parte in caminho.split(" → ")}
    if not ids:
        return {}
    return {
        str(linha["id"]): str(linha["canonical_name"])
        for linha in con.execute(
            "SELECT id, canonical_name FROM entity WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(sorted(ids)),),
        )
    }


def _explicar(
    unidade: str,
    fontes: tuple[str, ...],
    caminhos: dict[str, tuple[str, ...]],
    nomes: dict[str, str],
) -> str:
    """Gate 6: toda evidência diz por que veio — acerto direto ou aresta por aresta."""
    diretas = [f for f in fontes if f != "grafo"]
    partes = []
    if diretas:
        partes.append(f"acerto {'+'.join(diretas)} direto")
    legiveis = []
    for caminho in caminhos.get(unidade, ()):
        passos = []
        for passo in caminho.split(" → "):
            relacao, _, alvo = passo.rpartition("→")
            nome = nomes.get(alvo, alvo)
            passos.append(f"{relacao} → {nome}" if relacao else nome)
        legiveis.append(" → ".join(passos))
    if legiveis:
        partes.append("grafo: " + " | ".join(legiveis))
    return "; ".join(partes)
