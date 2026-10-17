"""SPEC §6.8 no caminho do cérebro: três braços, caminho de cada evidência, tempo e abstinência."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jarvis.memoryd.cofre import CofreFernet, nova_chave
from jarvis.memoryd.grafo import Tetos, ativar_por_salto
from jarvis.memoryd.indice import IndiceEmMemoria
from jarvis.memoryd.livro import LivroDeMemoria
from jarvis.memoryd.recuperacao import Parametros, lembrar, semear_por_apelido
from jarvis.politica.memoria import Estado

SESSAO = "01a1c000-0000-7000-8000-0000000000aa"


class Relogio:
    def __init__(self) -> None:
        self.momento = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.momento += timedelta(minutes=1)
        return self.momento


@pytest.fixture
def livro() -> LivroDeMemoria:
    livro = LivroDeMemoria.abrir(
        ":memory:", cofre=CofreFernet(nova_chave()), indice=IndiceEmMemoria(), agora=Relogio()
    )
    falas = {
        "irma": "A Beatriz é minha irmã.",
        "envio": "A Beatriz mandou o proposta-sol-v2.ods na terça.",
        "outro_envio": "A Beatriz mandou o cardapio-ipe-v1.pdf na sexta.",
        "sobre": "O proposta-sol-v2.ods é a proposta da Construtora Sol.",
        "navegador": "Uso o Firefox como navegador.",
    }
    fontes: dict[str, str] = {}
    for chave, texto in falas.items():
        fontes[chave] = livro.gravar_turno(
            session_id=SESSAO, papel="dono", texto=texto, trust="user_voice"
        )
        livro.lembrar(texto, estado=Estado.ATIVA, fonte=fontes[chave], extrator="dono")
    for nome, tipo, apelidos in (
        ("Beatriz", "pessoa", ("Bia", "minha irmã")),
        ("Construtora Sol", "organizacao", ("Sol",)),
        ("proposta-sol-v2.ods", "arquivo", ()),
        ("cardapio-ipe-v1.pdf", "arquivo", ()),
    ):
        livro.criar_no(
            tipo, nome, apelidos=apelidos, estado=Estado.ATIVA, fonte=fontes["irma"], extrator="t"
        )
    livro.criar_aresta(
        "Beatriz",
        "enviou",
        "proposta-sol-v2.ods",
        estado=Estado.ATIVA,
        fonte=fontes["envio"],
        extrator="t",
    )
    livro.criar_aresta(
        "Beatriz",
        "enviou",
        "cardapio-ipe-v1.pdf",
        estado=Estado.ATIVA,
        fonte=fontes["outro_envio"],
        extrator="t",
    )
    livro.criar_aresta(
        "proposta-sol-v2.ods",
        "sobre",
        "Construtora Sol",
        estado=Estado.ATIVA,
        fonte=fontes["sobre"],
        extrator="t",
    )
    antiga = livro.con.execute(
        "SELECT a.id FROM assertion a JOIN memory_unit m ON m.assertion_id = a.id"
        " WHERE m.text_redacted LIKE '%Firefox%'"
    ).fetchone()["id"]
    troca = livro.gravar_turno(
        session_id=SESSAO, papel="dono", texto="Agora uso o Brave.", trust="user_voice"
    )
    livro.atualizar(antiga, "Agora uso o Brave como navegador.", motivo="mudou", fonte=troca)
    livro.processar_outbox()
    return livro


def _agora(livro: LivroDeMemoria) -> str:
    return (
        (livro.agora() + timedelta(minutes=1))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _textos(livro: LivroDeMemoria, ids: list[str]) -> list[str]:
    return [
        livro.con.execute("SELECT text_redacted FROM memory_unit WHERE id = ?", (i,)).fetchone()[0]
        for i in ids
    ]


def test_consolidacao_liga_memoria_as_entidades_que_ela_cita(livro: LivroDeMemoria) -> None:
    linhas = livro.con.execute(
        "SELECT m.text_redacted, e.canonical_name FROM entity_mention x"
        " JOIN memory_unit m ON m.id = x.memory_unit_id JOIN entity e ON e.id = x.entity_id"
    ).fetchall()
    citadas = {(str(r[0]), str(r[1])) for r in linhas}
    assert ("A Beatriz é minha irmã.", "Beatriz") in citadas
    assert ("O proposta-sol-v2.ods é a proposta da Construtora Sol.", "Construtora Sol") in citadas


def test_apelido_de_varias_palavras_semeia_a_entidade(livro: LivroDeMemoria) -> None:
    sementes = dict(semear_por_apelido(livro.con, "o que minha irmã mandou?"))
    assert livro.resolver("Beatriz") in sementes


def test_somar_energia_poe_na_frente_o_vizinho_das_duas_sementes(livro: LivroDeMemoria) -> None:
    beatriz, sol = livro.resolver("Beatriz"), livro.resolver("Sol")
    assert beatriz and sol
    instante = _agora(livro)
    soma = ativar_por_salto(
        livro.con, [(beatriz, 1.0), (sol, 1.0)], Tetos(saltos=1), instante=instante, acumular=True
    )
    energia = {n.entity_id: n.energia for n in soma.nos}
    assert (
        energia[str(livro.resolver("proposta-sol-v2.ods"))]
        > energia[str(livro.resolver("cardapio-ipe-v1.pdf"))]
    )


def test_braco_c_acha_pelo_grafo_e_explica_o_caminho(livro: LivroDeMemoria) -> None:
    lembranca = lembrar(
        livro.con,
        livro.indice,
        "qual arquivo minha irmã mandou sobre a proposta da Sol?",
        instante=_agora(livro),
        parametros=Parametros(braco="C"),
    )
    textos = _textos(livro, [e.memory_unit_id for e in lembranca.evidencias])
    assert "A Beatriz mandou o proposta-sol-v2.ods na terça." in textos[:3]
    assert all(e.caminho for e in lembranca.evidencias), "gate 6: sem caminho não entra"
    envio = lembranca.evidencias[textos.index("A Beatriz mandou o proposta-sol-v2.ods na terça.")]
    assert "grafo" in envio.fontes
    assert "grafo:" in envio.caminho and "Beatriz" in envio.caminho


def test_bracos_a_e_b_nao_usam_grafo(livro: LivroDeMemoria) -> None:
    for braco in ("A", "B"):
        lembranca = lembrar(
            livro.con,
            livro.indice,
            "proposta da Sol",
            instante=_agora(livro),
            parametros=Parametros(braco=braco),
        )
        assert all("grafo" not in e.fontes for e in lembranca.evidencias)
    so_densa = lembrar(
        livro.con,
        livro.indice,
        "proposta da Sol",
        instante=_agora(livro),
        parametros=Parametros(braco="A"),
    )
    assert all(e.fontes == ("densa",) for e in so_densa.evidencias)


def test_vencida_nunca_volta_como_atual(livro: LivroDeMemoria) -> None:
    """Gate 4: a preferência antiga sai da densa, da léxica e do grafo."""
    for braco in ("A", "B", "C"):
        lembranca = lembrar(
            livro.con,
            livro.indice,
            "qual navegador eu uso? Firefox?",
            instante=_agora(livro),
            parametros=Parametros(braco=braco),
        )
        textos = _textos(livro, [e.memory_unit_id for e in lembranca.evidencias])
        assert not any("Firefox" in t for t in textos), braco
        assert any("Brave" in t for t in textos), braco


def test_abaixo_do_limiar_e_sem_grafo_novo_nao_inventa(livro: LivroDeMemoria) -> None:
    lembranca = lembrar(
        livro.con,
        livro.indice,
        "qual é o meu time de futebol?",
        instante=_agora(livro),
        parametros=Parametros(braco="C", limiar=0.5),
    )
    assert lembranca.abstencao
    assert lembranca.evidencias == []
