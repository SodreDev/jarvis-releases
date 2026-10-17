"""Ativação por propagação em SQL puro, com tetos e orçamento (SPEC §6.8, ADR-0008).

Zero chamada de LLM na consulta — não por economia, por orçamento: a §6.8 cita travessia de
grafo com LLM no laço em **segundos**, e o nosso teto é SLO-11/SLO-12, em milissegundos.

Três implementações, de propósito (cartão F0-05, aceite d):

* `ativar_por_salto` — a de produção: uma consulta por salto, com teto de fan-out por nó,
  teto de arestas e verificação de orçamento entre saltos;
* `ativar_recursivo_sql` — `WITH RECURSIVE`, uma consulta só, para comparar;
* `ativar_em_memoria` — carrega as arestas dos nós da fronteira e propaga em Python.

Estourar o orçamento **devolve o que tem** com `graph_truncated=True` e segue (P9). Nunca
espera: o `progress_handler` do SQLite interrompe a consulta no meio, se precisar.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Final

INSTANTE_PADRAO: Final = "2026-10-15T00:00:00+00:00"


@dataclass(frozen=True, slots=True)
class Tetos:
    """Os limites simultâneos da §6.8. Nada aqui é parâmetro mágico: tudo é calibrável.

    Os valores padrão são **[SUPOSIÇÃO]** inicial; a calibração em corpus anotado (70/30)
    é da F3, e o harness da F0-05 só mede o custo de cada combinação.
    """

    saltos: int = 2
    nos_por_salto: int = 64
    nos_visitados: int = 512
    arestas_lidas: int = 4096
    arestas_por_no: int = 32
    orcamento_ms: float = 40.0
    decaimento: float = 0.5
    energia_minima: float = 1e-4


TETOS_PADRAO: Final = Tetos()
"""Tetos iniciais, num só lugar: mudar parâmetro é commit, não ajuste em produção (§6.8)."""


@dataclass(frozen=True, slots=True)
class No:
    """Um nó ativado, com o caminho que explica por que ele apareceu (§6.8, passo 3)."""

    entity_id: str
    energia: float
    salto: int
    caminho: tuple[str, ...]

    @property
    def explicacao(self) -> str:
        return " → ".join(self.caminho) if self.caminho else self.entity_id


@dataclass(slots=True)
class Ativacao:
    """Resultado da travessia: sempre utilizável, truncado ou não."""

    nos: list[No] = field(default_factory=list)
    graph_truncated: bool = False
    motivo: str = ""
    arestas_lidas: int = 0
    nos_visitados: int = 0
    ms: float = 0.0
    implementacao: str = ""

    def por_energia(self, limite: int | None = None) -> list[No]:
        ordenados = sorted(self.nos, key=lambda n: (-n.energia, n.entity_id))
        return ordenados if limite is None else ordenados[:limite]


def penalidade_de_hub(grau: int) -> float:
    """`1/log(1+grau)` (§6.7): sem isso, "arquivo" e o nome do dono viram atalho para tudo."""
    return 1.0 / math.log(1.0 + max(grau, 1)) if grau > 1 else 1.0


@contextmanager
def _orcamento(con: sqlite3.Connection, prazo: float) -> Iterator[None]:
    """Interrompe a consulta quando o prazo passa — "nunca espera" vale dentro do SQL."""

    def vigia() -> int:
        return 1 if time.monotonic() > prazo else 0

    con.set_progress_handler(vigia, 2000)
    try:
        yield
    finally:
        con.set_progress_handler(None, 0)


CONSULTA_VIZINHOS: Final = """
WITH fronteira(entity_id) AS (SELECT value FROM json_each(:fronteira)),
vizinhos AS (
    SELECT e.src AS de, e.dst AS para, e.relation AS relacao, e.weight AS peso,
           e.confidence AS confianca
    FROM entity_edge e
    JOIN fronteira f ON f.entity_id = e.src
    WHERE e.status = 'active'
      AND e.valid_from <= :instante
      AND (e.valid_to IS NULL OR e.valid_to > :instante)
    UNION ALL
    SELECT e.dst AS de, e.src AS para, e.relation AS relacao, e.weight AS peso,
           e.confidence AS confianca
    FROM entity_edge e
    JOIN fronteira f ON f.entity_id = e.dst
    WHERE e.status = 'active'
      AND e.valid_from <= :instante
      AND (e.valid_to IS NULL OR e.valid_to > :instante)
),
ranqueado AS (
    SELECT v.de, v.para, v.relacao, v.peso, v.confianca,
           COALESCE(g.degree, 1) AS grau,
           ROW_NUMBER() OVER (
               PARTITION BY v.de ORDER BY v.peso * v.confianca DESC, v.para
           ) AS pos
    FROM vizinhos v
    LEFT JOIN graph_node_stats g ON g.entity_id = v.para
)
SELECT de, para, relacao, peso, confianca, grau
FROM ranqueado
WHERE pos <= :arestas_por_no
ORDER BY peso * confianca / (1.0 + grau) DESC
LIMIT :arestas_lidas
"""


def ativar_por_salto(
    con: sqlite3.Connection,
    sementes: Sequence[tuple[str, float]],
    tetos: Tetos = TETOS_PADRAO,
    *,
    instante: str = INSTANTE_PADRAO,
    acumular: bool = False,
) -> Ativacao:
    """Travessia de produção: uma consulta SQL por salto, com todos os tetos da §6.8.

    `acumular=False` guarda a **maior** energia que chega a cada nó (o que a F0-05 mediu);
    `acumular=True` **soma** as chegadas, como na ativação por propagação clássica: o nó que
    é vizinho de duas sementes (o arquivo que a irmã mandou **e** que é sobre o contrato) passa
    à frente dos vizinhos de uma só. Qual das duas vale é calibração (§6.8), não gosto.
    """

    inicio = time.monotonic()
    prazo = inicio + tetos.orcamento_ms / 1000.0
    resultado = Ativacao(implementacao="sql-por-salto")

    energia: dict[str, float] = {}
    caminho: dict[str, tuple[str, ...]] = {}
    salto_de: dict[str, int] = {}
    for entidade, peso in sementes:
        energia[entidade] = max(energia.get(entidade, 0.0), peso)
        caminho[entidade] = (entidade,)
        salto_de[entidade] = 0

    fronteira = [e for e, _ in sementes]
    melhor_chegada: dict[str, float] = {}
    for salto in range(1, tetos.saltos + 1):
        if not fronteira:
            break
        if time.monotonic() > prazo:
            resultado.graph_truncated = True
            resultado.motivo = f"orçamento de {tetos.orcamento_ms:.0f} ms antes do salto {salto}"
            break
        try:
            with _orcamento(con, prazo):
                linhas = con.execute(
                    CONSULTA_VIZINHOS,
                    {
                        "fronteira": json.dumps(fronteira[: tetos.nos_por_salto]),
                        "instante": instante,
                        "arestas_por_no": tetos.arestas_por_no,
                        "arestas_lidas": tetos.arestas_lidas,
                    },
                ).fetchall()
        except sqlite3.OperationalError as erro:
            resultado.graph_truncated = True
            resultado.motivo = f"consulta interrompida no salto {salto}: {erro}"
            break

        resultado.arestas_lidas += len(linhas)
        proxima: list[str] = []
        for linha in linhas:
            de = str(linha["de"])
            para = str(linha["para"])
            nova = (
                energia.get(de, 0.0)
                * tetos.decaimento
                * float(linha["peso"])
                * float(linha["confianca"])
                * penalidade_de_hub(int(linha["grau"]))
            )
            if nova < tetos.energia_minima:
                continue
            if acumular and para in energia and salto_de.get(para) == 0:
                continue  # semente não recebe de volta o que ela mesma espalhou
            melhor = nova > melhor_chegada.get(para, 0.0)
            if acumular:
                energia[para] = energia.get(para, 0.0) + nova
            elif nova > energia.get(para, 0.0):
                energia[para] = nova
            else:
                continue
            if melhor:
                melhor_chegada[para] = nova
                caminho[para] = (*caminho.get(de, (de,)), f"{linha['relacao']}→{para}")
                salto_de[para] = salto
            if para not in proxima:
                proxima.append(para)
            if len(energia) >= tetos.nos_visitados:
                resultado.graph_truncated = True
                resultado.motivo = f"teto de {tetos.nos_visitados} nós visitados no salto {salto}"
                break
        if resultado.graph_truncated:
            break
        fronteira = sorted(proxima, key=lambda e: -energia[e])[: tetos.nos_por_salto]
        if len(linhas) >= tetos.arestas_lidas:
            resultado.graph_truncated = True
            resultado.motivo = f"teto de {tetos.arestas_lidas} arestas lidas no salto {salto}"
            break

    resultado.nos = [
        No(entity_id=e, energia=v, salto=salto_de.get(e, 0), caminho=caminho.get(e, (e,)))
        for e, v in energia.items()
    ]
    resultado.nos_visitados = len(energia)
    resultado.ms = (time.monotonic() - inicio) * 1000.0
    return resultado


CONSULTA_VIZINHOS_DE_UM_NO: Final = """
SELECT :de AS de, para, relacao, peso, confianca, grau FROM (
    SELECT e.dst AS para, e.relation AS relacao, e.weight AS peso, e.confidence AS confianca,
           COALESCE(g.degree, 1) AS grau
    FROM entity_edge e
    LEFT JOIN graph_node_stats g ON g.entity_id = e.dst
    WHERE e.src = :de AND e.status = 'active'
      AND e.valid_from <= :instante AND (e.valid_to IS NULL OR e.valid_to > :instante)
    ORDER BY e.weight * e.confidence DESC
    LIMIT :arestas_por_no
)
UNION ALL
SELECT :de AS de, para, relacao, peso, confianca, grau FROM (
    SELECT e.src AS para, e.relation AS relacao, e.weight AS peso, e.confidence AS confianca,
           COALESCE(g.degree, 1) AS grau
    FROM entity_edge e
    LEFT JOIN graph_node_stats g ON g.entity_id = e.src
    WHERE e.dst = :de AND e.status = 'active'
      AND e.valid_from <= :instante AND (e.valid_to IS NULL OR e.valid_to > :instante)
    ORDER BY e.weight * e.confidence DESC
    LIMIT :arestas_por_no
)
"""


def ativar_por_no(
    con: sqlite3.Connection,
    sementes: Sequence[tuple[str, float]],
    tetos: Tetos = TETOS_PADRAO,
    *,
    instante: str = INSTANTE_PADRAO,
) -> Ativacao:
    """Igual à travessia por salto, mas com o teto de fan-out **dentro** da varredura.

    Achado do harness da F0-05: aplicar `ROW_NUMBER() ... WHERE pos <= teto` obriga o SQLite a
    ranquear **todas** as arestas do nó antes de cortar — num hub de grau 10 000 isso custou
    ~20 ms por consulta. Uma consulta por nó da fronteira, com `ORDER BY ... LIMIT`, para de
    ler no teto e usa o índice direto. Mais consultas, menos trabalho.
    """
    inicio = time.monotonic()
    prazo = inicio + tetos.orcamento_ms / 1000.0
    resultado = Ativacao(implementacao="sql-por-no")

    energia: dict[str, float] = {}
    caminho: dict[str, tuple[str, ...]] = {}
    salto_de: dict[str, int] = {}
    for entidade, peso in sementes:
        energia[entidade] = max(energia.get(entidade, 0.0), peso)
        caminho[entidade] = (entidade,)
        salto_de[entidade] = 0
    fronteira = [e for e, _ in sementes]

    for salto in range(1, tetos.saltos + 1):
        if not fronteira:
            break
        proxima: list[str] = []
        for de in fronteira[: tetos.nos_por_salto]:
            if time.monotonic() > prazo:
                resultado.graph_truncated = True
                resultado.motivo = f"orçamento de {tetos.orcamento_ms:.0f} ms no salto {salto}"
                break
            try:
                with _orcamento(con, prazo):
                    linhas = con.execute(
                        CONSULTA_VIZINHOS_DE_UM_NO,
                        {
                            "de": de,
                            "instante": instante,
                            "arestas_por_no": tetos.arestas_por_no,
                        },
                    ).fetchall()
            except sqlite3.OperationalError as erro:
                resultado.graph_truncated = True
                resultado.motivo = f"consulta interrompida no salto {salto}: {erro}"
                break
            resultado.arestas_lidas += len(linhas)
            for linha in linhas:
                para = str(linha["para"])
                nova = (
                    energia.get(de, 0.0)
                    * tetos.decaimento
                    * float(linha["peso"])
                    * float(linha["confianca"])
                    * penalidade_de_hub(int(linha["grau"]))
                )
                if nova < tetos.energia_minima or nova <= energia.get(para, 0.0):
                    continue
                energia[para] = nova
                caminho[para] = (*caminho.get(de, (de,)), f"{linha['relacao']}→{para}")
                salto_de[para] = salto
                if para not in proxima:
                    proxima.append(para)
            if len(energia) >= tetos.nos_visitados:
                resultado.graph_truncated = True
                resultado.motivo = f"teto de {tetos.nos_visitados} nós visitados"
                break
            if resultado.arestas_lidas >= tetos.arestas_lidas:
                resultado.graph_truncated = True
                resultado.motivo = f"teto de {tetos.arestas_lidas} arestas lidas"
                break
        if resultado.graph_truncated:
            break
        fronteira = sorted(proxima, key=lambda e: -energia[e])[: tetos.nos_por_salto]

    resultado.nos = [
        No(entity_id=e, energia=v, salto=salto_de.get(e, 0), caminho=caminho.get(e, (e,)))
        for e, v in energia.items()
    ]
    resultado.nos_visitados = len(energia)
    resultado.ms = (time.monotonic() - inicio) * 1000.0
    return resultado


CONSULTA_RECURSIVA: Final = """
WITH RECURSIVE
semente(entity_id, energia, salto) AS (
    SELECT value, 1.0, 0 FROM json_each(:fronteira)
),
ativado(entity_id, energia, salto) AS (
    SELECT entity_id, energia, salto FROM semente
    UNION ALL
    SELECT v.para,
           a.energia * :decaimento * v.peso * v.confianca / (1.0 + log(1.0 + v.grau)),
           a.salto + 1
    FROM ativado a
    JOIN (
        SELECT e.src AS de, e.dst AS para, e.weight AS peso, e.confidence AS confianca,
               COALESCE(g.degree, 1) AS grau
        FROM entity_edge e LEFT JOIN graph_node_stats g ON g.entity_id = e.dst
        WHERE e.status = 'active'
          AND e.valid_from <= :instante AND (e.valid_to IS NULL OR e.valid_to > :instante)
        UNION ALL
        SELECT e.dst AS de, e.src AS para, e.weight AS peso, e.confidence AS confianca,
               COALESCE(g.degree, 1) AS grau
        FROM entity_edge e LEFT JOIN graph_node_stats g ON g.entity_id = e.src
        WHERE e.status = 'active'
          AND e.valid_from <= :instante AND (e.valid_to IS NULL OR e.valid_to > :instante)
    ) v ON v.de = a.entity_id
    WHERE a.salto < :saltos AND a.energia > :energia_minima
)
SELECT entity_id, MAX(energia) AS energia, MIN(salto) AS salto
FROM ativado
GROUP BY entity_id
ORDER BY energia DESC
LIMIT :nos_visitados
"""


def ativar_recursivo_sql(
    con: sqlite3.Connection,
    sementes: Sequence[tuple[str, float]],
    tetos: Tetos = TETOS_PADRAO,
    *,
    instante: str = INSTANTE_PADRAO,
) -> Ativacao:
    """Mesma propagação numa `WITH RECURSIVE` só — comparação do aceite (d).

    Sem teto de fan-out por nó: é justamente o que a comparação mostra. O orçamento continua
    valendo, porque o `progress_handler` interrompe a consulta.
    """

    inicio = time.monotonic()
    prazo = inicio + tetos.orcamento_ms / 1000.0
    resultado = Ativacao(implementacao="sql-recursivo")
    try:
        with _orcamento(con, prazo):
            linhas = con.execute(
                CONSULTA_RECURSIVA,
                {
                    "fronteira": json.dumps([e for e, _ in sementes]),
                    "instante": instante,
                    "saltos": tetos.saltos,
                    "decaimento": tetos.decaimento,
                    "energia_minima": tetos.energia_minima,
                    "nos_visitados": tetos.nos_visitados,
                },
            ).fetchall()
    except sqlite3.OperationalError as erro:
        resultado.graph_truncated = True
        resultado.motivo = f"consulta recursiva interrompida: {erro}"
        linhas = []

    resultado.nos = [
        No(
            entity_id=str(linha["entity_id"]),
            energia=float(linha["energia"]),
            salto=int(linha["salto"]),
            caminho=(str(linha["entity_id"]),),
        )
        for linha in linhas
    ]
    resultado.nos_visitados = len(resultado.nos)
    resultado.ms = (time.monotonic() - inicio) * 1000.0
    if len(resultado.nos) >= tetos.nos_visitados:
        resultado.graph_truncated = True
        resultado.motivo = f"teto de {tetos.nos_visitados} nós na recursiva"
    return resultado


def ativar_em_memoria(
    con: sqlite3.Connection,
    sementes: Sequence[tuple[str, float]],
    tetos: Tetos = TETOS_PADRAO,
    *,
    instante: str = INSTANTE_PADRAO,
) -> Ativacao:
    """Propagação em Python, com as arestas da fronteira trazidas por consulta simples."""

    inicio = time.monotonic()
    prazo = inicio + tetos.orcamento_ms / 1000.0
    resultado = Ativacao(implementacao="memoria")

    energia = {e: p for e, p in sementes}
    caminho: dict[str, tuple[str, ...]] = {e: (e,) for e, _ in sementes}
    salto_de: dict[str, int] = dict.fromkeys(energia, 0)
    fronteira = list(energia)

    for salto in range(1, tetos.saltos + 1):
        if not fronteira or time.monotonic() > prazo:
            if fronteira:
                resultado.graph_truncated = True
                resultado.motivo = f"orçamento antes do salto {salto}"
            break
        linhas = con.execute(
            """
            SELECT e.src AS de, e.dst AS para, e.relation AS relacao, e.weight AS peso,
                   e.confidence AS confianca, COALESCE(g.degree, 1) AS grau
            FROM entity_edge e
            LEFT JOIN graph_node_stats g ON g.entity_id = e.dst
            WHERE e.status = 'active' AND e.src IN (SELECT value FROM json_each(?))
              AND e.valid_from <= ? AND (e.valid_to IS NULL OR e.valid_to > ?)
            UNION ALL
            SELECT e.dst AS de, e.src AS para, e.relation AS relacao, e.weight AS peso,
                   e.confidence AS confianca, COALESCE(g.degree, 1) AS grau
            FROM entity_edge e
            LEFT JOIN graph_node_stats g ON g.entity_id = e.src
            WHERE e.status = 'active' AND e.dst IN (SELECT value FROM json_each(?))
              AND e.valid_from <= ? AND (e.valid_to IS NULL OR e.valid_to > ?)
            """,
            (
                json.dumps(fronteira[: tetos.nos_por_salto]),
                instante,
                instante,
                json.dumps(fronteira[: tetos.nos_por_salto]),
                instante,
                instante,
            ),
        ).fetchall()
        resultado.arestas_lidas += len(linhas)

        vistos_por_no: dict[str, int] = {}
        proxima: list[str] = []
        for linha in sorted(linhas, key=lambda r: -(r["peso"] * r["confianca"])):
            de, para = str(linha["de"]), str(linha["para"])
            vistos_por_no[de] = vistos_por_no.get(de, 0) + 1
            if vistos_por_no[de] > tetos.arestas_por_no:
                continue
            nova = (
                energia.get(de, 0.0)
                * tetos.decaimento
                * float(linha["peso"])
                * float(linha["confianca"])
                * penalidade_de_hub(int(linha["grau"]))
            )
            if nova < tetos.energia_minima or nova <= energia.get(para, 0.0):
                continue
            energia[para] = nova
            caminho[para] = (*caminho.get(de, (de,)), f"{linha['relacao']}→{para}")
            salto_de[para] = salto
            if para not in proxima:
                proxima.append(para)
            if len(energia) >= tetos.nos_visitados:
                resultado.graph_truncated = True
                resultado.motivo = f"teto de nós visitados no salto {salto}"
                break
        if resultado.graph_truncated:
            break
        fronteira = sorted(proxima, key=lambda e: -energia[e])[: tetos.nos_por_salto]

    resultado.nos = [
        No(entity_id=e, energia=v, salto=salto_de.get(e, 0), caminho=caminho.get(e, (e,)))
        for e, v in energia.items()
    ]
    resultado.nos_visitados = len(energia)
    resultado.ms = (time.monotonic() - inicio) * 1000.0
    return resultado


def semear_por_termo(
    con: sqlite3.Connection, termos: Sequence[str], *, limite: int = 8
) -> list[tuple[str, float]]:
    """Passo 1 da §6.8: termos → `entity_resolution` → entidades, com peso normalizado."""

    linhas = con.execute(
        "SELECT entity_id, MAX(score) AS score FROM entity_resolution"
        " WHERE alias_norm IN (SELECT value FROM json_each(?))"
        " GROUP BY entity_id ORDER BY score DESC LIMIT ?",
        (json.dumps([t.casefold() for t in termos]), limite),
    ).fetchall()
    return [(str(linha["entity_id"]), float(linha["score"])) for linha in linhas]
