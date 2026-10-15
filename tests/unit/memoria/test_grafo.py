"""Aceite F0-05 (b), (c) e a equivalência entre as implementações (SPEC §6.8)."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Iterator, Sequence

import pytest

from jarvis.memoryd.esquema import abrir
from jarvis.memoryd.grafo import (
    Ativacao,
    Tetos,
    ativar_em_memoria,
    ativar_por_no,
    ativar_por_salto,
    ativar_recursivo_sql,
    penalidade_de_hub,
    semear_por_termo,
)
from jarvis.memoryd.sintetico import Escala, atualizar_graus, gerar

Travessia = Callable[..., Ativacao]
IMPLEMENTACOES: tuple[Travessia, ...] = (ativar_por_no, ativar_por_salto, ativar_em_memoria)


@pytest.fixture
def grafo() -> Iterator[sqlite3.Connection]:
    con = abrir()
    gerar(con, Escala.de_corpus("teste", episodios_base=122, fator=1))
    yield con
    con.close()


@pytest.fixture
def grafo_com_hub() -> Iterator[sqlite3.Connection]:
    """Aceite (c): hub com grau 10 000, como o cartão pede."""
    con = abrir()
    gerar(con, Escala.de_corpus("hub", episodios_base=122, fator=1), hub_grau=10_000)
    yield con
    con.close()


def sementes(con: sqlite3.Connection, termo: str = "entidade 7") -> Sequence[tuple[str, float]]:
    encontradas = semear_por_termo(con, [termo])
    assert encontradas, f"semente {termo!r} não resolveu: o teste não provaria nada"
    return encontradas


# --- propagação -------------------------------------------------------------------
@pytest.mark.parametrize("travessia", IMPLEMENTACOES)
def test_um_salto_so_alcanca_vizinhos_diretos(
    travessia: Travessia, grafo: sqlite3.Connection
) -> None:
    ativacao = travessia(grafo, sementes(grafo), Tetos(saltos=1))

    assert {no.salto for no in ativacao.nos} <= {0, 1}
    assert len(ativacao.nos) > 1


@pytest.mark.parametrize("travessia", IMPLEMENTACOES)
def test_dois_saltos_alcancam_mais_que_um(travessia: Travessia, grafo: sqlite3.Connection) -> None:
    um = travessia(grafo, sementes(grafo), Tetos(saltos=1))
    dois = travessia(grafo, sementes(grafo), Tetos(saltos=2))

    assert len(dois.nos) > len(um.nos)
    assert max(no.salto for no in dois.nos) == 2


def test_as_implementacoes_concordam_no_conjunto_de_nos(grafo: sqlite3.Connection) -> None:
    """Aceite (d), parte da corretude: comparar custo só vale se o resultado é o mesmo."""
    tetos = Tetos(saltos=2, arestas_por_no=1024)
    conjuntos = [
        {no.entity_id for no in travessia(grafo, sementes(grafo), tetos).nos}
        for travessia in (*IMPLEMENTACOES, ativar_recursivo_sql)
    ]

    assert all(c == conjuntos[0] for c in conjuntos), {i: len(c) for i, c in enumerate(conjuntos)}


@pytest.mark.parametrize("travessia", IMPLEMENTACOES)
def test_energia_decai_por_salto(travessia: Travessia, grafo: sqlite3.Connection) -> None:
    ativacao = travessia(grafo, sementes(grafo), Tetos(saltos=2))
    por_salto: dict[int, list[float]] = {}
    for no in ativacao.nos:
        por_salto.setdefault(no.salto, []).append(no.energia)

    assert max(por_salto[2]) < max(por_salto[1]) <= max(por_salto[0])


@pytest.mark.parametrize("travessia", IMPLEMENTACOES)
def test_cada_no_vem_com_o_caminho_que_o_explica(
    travessia: Travessia, grafo: sqlite3.Connection
) -> None:
    """§6.8 passo 3: evidência vem com o caminho — é o "por que eu lembrei disto"."""
    ativacao = travessia(grafo, sementes(grafo), Tetos(saltos=2))

    for no in ativacao.por_energia(5):
        assert no.caminho
        assert no.explicacao
        if no.salto > 0:
            assert "→" in no.explicacao


# --- (b) orçamento ----------------------------------------------------------------
@pytest.mark.parametrize("travessia", IMPLEMENTACOES)
def test_orcamento_estourado_devolve_parcial_e_nao_espera(
    travessia: Travessia, grafo_com_hub: sqlite3.Connection
) -> None:
    """Aceite (b): `graph_truncated: true`, resultado utilizável, sem esperar."""
    inicio = time.monotonic()
    ativacao = travessia(
        grafo_com_hub, sementes(grafo_com_hub, "entidade 0"), Tetos(saltos=2, orcamento_ms=0.0)
    )
    gasto_ms = (time.monotonic() - inicio) * 1000.0

    assert ativacao.graph_truncated
    assert ativacao.motivo
    assert ativacao.nos, "mesmo truncada, a travessia devolve as sementes"
    assert gasto_ms < 200.0, f"esperou {gasto_ms:.0f} ms com orçamento zero"


def test_orcamento_interrompe_a_consulta_recursiva(grafo_com_hub: sqlite3.Connection) -> None:
    """O `progress_handler` corta dentro do SQL: "nunca espera" não depende de boa sorte."""
    ativacao = ativar_recursivo_sql(
        grafo_com_hub, sementes(grafo_com_hub, "entidade 0"), Tetos(saltos=2, orcamento_ms=1.0)
    )

    assert ativacao.graph_truncated
    assert "interrompida" in ativacao.motivo or "teto" in ativacao.motivo


# --- (c) hub ----------------------------------------------------------------------
def test_hub_com_grau_dez_mil_nao_explode_a_travessia(grafo_com_hub: sqlite3.Connection) -> None:
    """Aceite (c): o teto comprovado é o de fan-out por nó, dentro da varredura."""
    grau = int(
        grafo_com_hub.execute("SELECT MAX(degree) AS g FROM graph_node_stats").fetchone()["g"]
    )
    assert grau >= 10_000, f"o hub do teste tem grau {grau}"

    tetos = Tetos(saltos=2, arestas_por_no=32, orcamento_ms=200.0)
    ativacao = ativar_por_no(grafo_com_hub, sementes(grafo_com_hub, "entidade 0"), tetos)

    assert not ativacao.graph_truncated
    assert ativacao.arestas_lidas <= tetos.arestas_lidas
    # O teto de fan-out é o que segura: 2 saltos a partir do hub leem muito menos que o grau.
    assert ativacao.arestas_lidas < grau
    assert ativacao.nos_visitados <= tetos.nos_visitados


def test_penalidade_de_hub_desconta_o_atalho() -> None:
    assert penalidade_de_hub(1) == 1.0
    assert penalidade_de_hub(10) > penalidade_de_hub(10_000)
    assert penalidade_de_hub(10_000) < 0.15


def test_no_alcancado_por_hub_recebe_menos_energia(grafo_com_hub: sqlite3.Connection) -> None:
    ativacao = ativar_por_no(grafo_com_hub, sementes(grafo_com_hub, "entidade 0"), Tetos(saltos=1))
    graus = {
        str(linha["entity_id"]): int(linha["degree"])
        for linha in grafo_com_hub.execute("SELECT entity_id, degree FROM graph_node_stats")
    }
    por_grau = sorted(
        (no for no in ativacao.nos if no.salto == 1), key=lambda n: graus.get(n.entity_id, 1)
    )

    assert (
        por_grau[0].energia > por_grau[-1].energia
        or graus[por_grau[0].entity_id] == graus[por_grau[-1].entity_id]
    )


# --- tetos e validade temporal ----------------------------------------------------
def test_teto_de_nos_visitados_trunca(grafo: sqlite3.Connection) -> None:
    ativacao = ativar_por_no(grafo, sementes(grafo), Tetos(saltos=2, nos_visitados=5))

    assert ativacao.graph_truncated
    assert "nós visitados" in ativacao.motivo


def test_aresta_vencida_nao_e_atravessada(grafo: sqlite3.Connection) -> None:
    """§6.8 passo 4: tudo filtrado por validade contra o instante da pergunta."""
    antes = ativar_por_no(grafo, sementes(grafo), Tetos(saltos=1))
    grafo.execute(
        "UPDATE entity_edge SET valid_to = '2026-01-01T00:00:00+00:00' WHERE src = ? OR dst = ?",
        (sementes(grafo)[0][0], sementes(grafo)[0][0]),
    )

    depois = ativar_por_no(grafo, sementes(grafo), Tetos(saltos=1))

    assert len(antes.nos) > 1
    assert len(depois.nos) == 1  # sobra só a semente


def test_aresta_apenas_proposta_nao_e_atravessada(grafo: sqlite3.Connection) -> None:
    """§6.7: aresta nasce `proposed` e só entra na consulta quando vira `active`."""
    semente = sementes(grafo)[0][0]
    grafo.execute(
        "UPDATE entity_edge SET status = 'proposed' WHERE src = ? OR dst = ?",
        (semente, semente),
    )
    atualizar_graus(grafo)

    ativacao = ativar_por_no(grafo, sementes(grafo), Tetos(saltos=2))

    assert len(ativacao.nos) == 1
