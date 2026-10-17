"""ADR-0026, fatias M1 e M2: histórico cifrado, retenção D19, escrita com proveniência e cascata."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jarvis.memoryd.cofre import BrutoAdulterado, CofreFernet, nova_chave
from jarvis.memoryd.indice import IndiceEmMemoria
from jarvis.memoryd.livro import AlvoInexistente, BancoSemCofre, LivroDeMemoria
from jarvis.politica.memoria import Estado

SESSAO = "01a1c000-0000-7000-8000-000000000001"
SEGREDO = "sk-ABCDEFGHIJKLMNOPQRSTUVWX123456"


class Relogio:
    def __init__(self) -> None:
        self.momento = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.momento


@pytest.fixture
def relogio() -> Relogio:
    return Relogio()


@pytest.fixture
def livro(relogio: Relogio) -> LivroDeMemoria:
    return LivroDeMemoria.abrir(
        ":memory:", cofre=CofreFernet(nova_chave()), indice=IndiceEmMemoria(), agora=relogio
    )


def _conversa(livro: LivroDeMemoria) -> list[str]:
    return [
        livro.gravar_turno(
            session_id=SESSAO,
            papel="dono",
            texto="minha irmã Beatriz faz aniversário dia três de maio",
            trust="user_voice",
        ),
        livro.gravar_turno(
            session_id=SESSAO,
            papel="jarvis",
            texto="Anotado, dia três de",
            trust="system",
            played_ms=900,
            interrompida=True,
        ),
        livro.gravar_turno(
            session_id=SESSAO,
            papel="dono",
            texto=f"e a chave da API é {SEGREDO}, guarda pra mim",
            trust="user_voice",
        ),
    ]


# --- cofre (regra 6) -----------------------------------------------------------------
def test_cofre_decifra_o_que_cifrou_e_recusa_bruto_adulterado() -> None:
    cofre = CofreFernet(nova_chave())
    cifrado = cofre.cifrar(b"texto do dono")
    assert b"texto do dono" not in cifrado
    assert cofre.decifrar(cifrado) == b"texto do dono"
    with pytest.raises(BrutoAdulterado):
        cofre.decifrar(cifrado[:-3] + b"xyz")
    with pytest.raises(BrutoAdulterado):
        CofreFernet(nova_chave()).decifrar(cifrado)


def test_a_chave_nunca_aparece_no_repr() -> None:
    chave = nova_chave()
    assert chave.decode() not in repr(CofreFernet(chave))


def test_banco_em_disco_sem_cofre_nao_abre(tmp_path: Path) -> None:
    with pytest.raises(BancoSemCofre, match="sem cofre"):
        LivroDeMemoria.abrir(tmp_path / "memoria.sqlite", cofre=None, indice=IndiceEmMemoria())


def test_em_disco_o_bruto_vai_cifrado(tmp_path: Path) -> None:
    caminho = tmp_path / "memoria.sqlite"
    livro = LivroDeMemoria.abrir(caminho, cofre=CofreFernet(nova_chave()), indice=IndiceEmMemoria())
    episodio = livro.gravar_turno(
        session_id=SESSAO, papel="dono", texto=f"guarda {SEGREDO}", trust="user_voice"
    )
    bruto = livro.con.execute("SELECT cifrado FROM raw_blob").fetchone()["cifrado"]
    assert SEGREDO.encode() not in bytes(bruto)
    assert SEGREDO in livro.texto_bruto(episodio)
    livro.con.close()
    assert SEGREDO.encode() not in caminho.read_bytes(), "o segredo foi para o disco em claro"


# --- turnos (M1) -----------------------------------------------------------------------
def test_turno_do_jarvis_sem_played_ms_e_recusado(livro: LivroDeMemoria) -> None:
    with pytest.raises(ValueError, match="só entra o que tocou"):
        livro.gravar_turno(session_id=SESSAO, papel="jarvis", texto="oi", trust="system")


def test_buscar_no_historico_acha_o_turno_com_o_caminho(livro: LivroDeMemoria) -> None:
    dono, _, _ = _conversa(livro)
    achados = livro.buscar_historico("aniversário da Beatriz")

    assert achados[0]["episode_id"] == dono
    assert achados[0]["caminho"].startswith("acerto lexico")
    assert livro.buscar_historico("bicicleta vermelha") == []

    livro.processar_outbox()
    assert "denso" in livro.buscar_historico("Beatriz aniversário")[0]["caminho"]


def test_o_segredo_dito_na_conversa_nao_volta_na_busca(livro: LivroDeMemoria) -> None:
    """Gate 3: segredo sintético não aparece em consulta sem escopo."""
    _, _, com_segredo = _conversa(livro)
    livro.processar_outbox()

    achados = livro.buscar_historico("chave da API")
    assert achados[0]["episode_id"] == com_segredo
    assert SEGREDO not in str(achados)
    assert "[REDIGIDO:chave_openai]" in achados[0]["texto"]
    assert SEGREDO not in str(livro.ler_mensagem(com_segredo))


def test_filtro_de_data_do_historico(livro: LivroDeMemoria, relogio: Relogio) -> None:
    _conversa(livro)
    assert livro.buscar_historico("Beatriz", ate="2026-10-15T00:00:00.000Z") == []
    assert livro.buscar_historico("Beatriz", desde="2026-10-16T00:00:00.000Z")


def test_ler_mensagem_traz_os_vizinhos_em_ordem(livro: LivroDeMemoria) -> None:
    dono, jarvis, ultimo = _conversa(livro)
    turnos = livro.ler_mensagem(jarvis, vizinhos=1)

    assert [t["episode_id"] for t in turnos] == [dono, jarvis, ultimo]
    assert [t["alvo"] for t in turnos] == [False, True, False]
    assert turnos[1]["interrompida"] is True
    with pytest.raises(AlvoInexistente):
        livro.ler_mensagem("ep-nao-existe")


def test_retencao_d19_apaga_o_nao_citado_e_guarda_o_citado(
    livro: LivroDeMemoria, relogio: Relogio
) -> None:
    dono, jarvis, ultimo = _conversa(livro)
    livro.lembrar(
        "Beatriz faz aniversário dia três de maio",
        estado=Estado.ATIVA,
        fonte=dono,
        extrator="s2:teste",
    )

    relogio.momento += timedelta(days=89)
    assert livro.expirar() == 0
    relogio.momento += timedelta(days=2)
    assert livro.expirar() == 2

    restantes = [r["id"] for r in livro.con.execute("SELECT id FROM episode")]
    assert restantes == [dono], "turno citado por memória fica até o dono apagar"
    del jarvis, ultimo


# --- memória e grafo (M2) ---------------------------------------------------------------
def test_lembrar_atualizar_e_buscar_so_o_vigente(livro: LivroDeMemoria) -> None:
    dono, _, ultimo = _conversa(livro)
    gravada = livro.lembrar(
        "Beatriz faz aniversário dia três de maio",
        estado=Estado.ATIVA,
        fonte=dono,
        extrator="s2:teste",
        sujeito="Beatriz",
        predicado="aniversario",
    )
    assert gravada["estado"] == "active"
    assert livro.buscar("aniversário da Beatriz")[0]["assertion_id"] == gravada["assertion_id"]

    nova = livro.atualizar(
        gravada["assertion_id"],
        "Beatriz faz aniversário dia quatro de maio",
        motivo="o dono corrigiu",
        fonte=ultimo,
    )
    achados = livro.buscar("aniversário da Beatriz")
    assert [a["assertion_id"] for a in achados] == [nova["assertion_id"]], "gate 4: vencido"
    assert all(a["caminho"] for a in achados), "gate 6: sem caminho não entra"
    with pytest.raises(AlvoInexistente):
        livro.atualizar(gravada["assertion_id"], "x", motivo="y", fonte=ultimo)


def test_memoria_proposta_nao_aparece_como_fato(livro: LivroDeMemoria) -> None:
    dono, _, _ = _conversa(livro)
    livro.lembrar("Beatriz gosta de jazz", estado=Estado.PROPOSTA, fonte=dono, extrator="s2:t")
    assert livro.buscar("Beatriz jazz") == []


def test_retratar_tira_da_busca_e_deixa_rastro(livro: LivroDeMemoria) -> None:
    dono, _, _ = _conversa(livro)
    gravada = livro.lembrar(
        "Beatriz mora em Recife", estado=Estado.ATIVA, fonte=dono, extrator="s2:t"
    )
    livro.retratar(gravada["assertion_id"])

    assert livro.buscar("Beatriz Recife") == []
    status = livro.con.execute(
        "SELECT status, valid_to FROM assertion WHERE id = ?", (gravada["assertion_id"],)
    ).fetchone()
    assert status["status"] == "retracted"
    assert status["valid_to"] is not None
    with pytest.raises(AlvoInexistente):
        livro.retratar("ast-nao-existe")


def test_criar_no_nao_duplica_e_a_aresta_resolve_por_apelido(livro: LivroDeMemoria) -> None:
    dono, _, _ = _conversa(livro)
    beatriz = livro.criar_no(
        "pessoa", "Beatriz", apelidos=["Bia"], estado=Estado.ATIVA, fonte=dono, extrator="s2:t"
    )
    de_novo = livro.criar_no("pessoa", "bia", estado=Estado.ATIVA, fonte=dono, extrator="s2:t")
    assert de_novo == {"entity_id": beatriz["entity_id"], "estado": "active", "existente": True}

    livro.criar_no("pessoa", "dono", estado=Estado.ATIVA, fonte=dono, extrator="s2:t")
    aresta = livro.criar_aresta(
        "Bia", "irma_de", "dono", estado=Estado.ATIVA, fonte=dono, extrator="s2:t"
    )
    linha = livro.con.execute(
        "SELECT src, source_episode_id, status FROM entity_edge WHERE id = ?", (aresta["edge_id"],)
    ).fetchone()
    assert linha["src"] == beatriz["entity_id"]
    assert linha["source_episode_id"] == dono, "toda aresta tem proveniência (§6.7)"
    with pytest.raises(AlvoInexistente, match="não existe no grafo"):
        livro.criar_aresta(
            "Carlos", "amigo_de", "dono", estado=Estado.ATIVA, fonte=dono, extrator="s2:t"
        )


def test_escrita_sem_episodio_de_origem_falha(livro: LivroDeMemoria) -> None:
    with pytest.raises(AlvoInexistente, match="episódio de origem"):
        livro.lembrar("x y", estado=Estado.ATIVA, fonte="ep-inventado", extrator="s2:t")


# --- gate 2: exclusão em cascata --------------------------------------------------------
def test_apagar_a_sessao_nao_deixa_resto_em_camada_nenhuma(livro: LivroDeMemoria) -> None:
    dono, _, _ = _conversa(livro)
    livro.lembrar(
        "Beatriz faz aniversário dia três de maio",
        estado=Estado.ATIVA,
        fonte=dono,
        extrator="s2:t",
        sujeito="Beatriz",
    )
    livro.criar_no("pessoa", "Pedro", estado=Estado.ATIVA, fonte=dono, extrator="s2:t")
    livro.criar_aresta(
        "Beatriz", "irma_de", "Pedro", estado=Estado.ATIVA, fonte=dono, extrator="s2:t"
    )
    livro.processar_outbox()
    assert livro.varrer("Beatriz")["memory_unit"] > 0

    removidos = livro.apagar(SESSAO, "sessao")

    assert removidos["episode"] == 3
    assert livro.varrer("Beatriz") == {
        "bruto": 0,
        "memory_unit": 0,
        "fts": 0,
        "assertion": 0,
        "indice": 0,
    }
    for tabela in (
        "entity_edge",
        "entity_mention",
        "entity",
        "entity_resolution",
        "turno",
        "raw_blob",
        "outbox",
    ):
        assert livro.con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0] == 0, tabela  # noqa: S608
    with pytest.raises(AlvoInexistente):
        livro.apagar(SESSAO, "sessao")


def test_apagar_tira_o_texto_do_arquivo_do_banco(tmp_path: Path, relogio: Relogio) -> None:
    """Gate 2 no disco: sem `secure_delete`, sem fundir o FTS5 e sem checkpoint do WAL, o texto
    redigido apagado continua nos bytes do banco (o bruto é cifrado; a redação, não)."""
    caminho = tmp_path / "memoria.sqlite"
    livro = LivroDeMemoria.abrir(
        caminho, cofre=CofreFernet(nova_chave()), indice=IndiceEmMemoria(), agora=relogio
    )
    for n in range(30):
        livro.gravar_turno(
            session_id=SESSAO, papel="dono", texto=f"conversa comum número {n}", trust="user_voice"
        )
    alvo = livro.gravar_turno(
        session_id=SESSAO, papel="dono", texto="xilofonezumbido marcante", trust="user_voice"
    )
    livro.processar_outbox()
    assert b"xilofonezumbido" in b"".join(p.read_bytes() for p in tmp_path.iterdir())

    livro.apagar(alvo, "turno")
    livro.con.close()

    resto = b"".join(p.read_bytes() for p in tmp_path.iterdir() if p.is_file())
    assert b"xilofonezumbido" not in resto


def test_apagar_uma_memoria_deixa_o_turno(livro: LivroDeMemoria) -> None:
    dono, _, _ = _conversa(livro)
    gravada = livro.lembrar("Beatriz toca violão", estado=Estado.ATIVA, fonte=dono, extrator="s2:t")
    livro.apagar(gravada["assertion_id"], "memoria")

    assert livro.buscar("violão") == []
    assert livro.buscar_historico("aniversário")[0]["episode_id"] == dono
