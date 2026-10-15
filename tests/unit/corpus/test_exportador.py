"""Aceite F0-08 (a) e (b): exportador redige segredo, publica `n`, e o manifesto acusa mudança."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from tools.corpus import gerar_manifesto, resumo, verificar
from tools.exportar_orchestrator import parse_dump, parse_jsonl

from jarvis.memoryd.esquema import abrir
from jarvis.memoryd.importacao import (
    MemoriaDoOrchestrator,
    classe_de_pii,
    exportar,
    extrair_entidades,
    normalizar,
    redigir,
)

SEGREDOS = {
    "chave_openai": "sk-proj-AbCdEf0123456789abcdef",
    "token_github": "ghp_0123456789abcdefghijklmnopqrstuvwx",
    "chave_aws": "AKIAIOSFODNN7EXAMPLE",
    "chave_google": "AIzaSyA-0123456789abcdefghijklmnopqrstu",
    "chave_anthropic": "sk-ant-api03-ABCdef0123456789",
    "token_slack": "xoxb-0123456789-abcdefghij",
    "url_com_credencial": "postgres://sodre:senhaforte@localhost:5432/banco",
    "senha_declarada": "senha: minhaSenhaSecreta123",
    "conteudo_de_env": "API_TOKEN=abcdef0123456789",
    "email": "alguem@exemplo.com",
    "hex_longo": "a" * 64,
}


@pytest.fixture
def con() -> Iterator[sqlite3.Connection]:
    conexao = abrir()
    yield conexao
    conexao.close()


# --- (a) redação ------------------------------------------------------------------
@pytest.mark.parametrize(("tipo", "valor"), sorted(SEGREDOS.items()))
def test_cada_padrao_de_segredo_e_redigido(tipo: str, valor: str) -> None:
    resultado = redigir(f"anotação do dono: {valor} — fim")

    assert valor not in resultado.texto, f"{tipo} passou inteiro"
    assert "[REDIGIDO:" in resultado.texto
    assert resultado.total >= 1


def test_chave_privada_inteira_e_redigida() -> None:
    chave = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAAB\n"
        "-----END OPENSSH PRIVATE KEY-----"
    )

    resultado = redigir(f"colei aqui sem pensar:\n{chave}\npronto")

    assert "BEGIN" not in resultado.texto
    assert "b3BlbnNzaC" not in resultado.texto


def test_texto_sem_segredo_atravessa_intacto() -> None:
    texto = "o executor commitou F0-07 em 5871d30 e o CI ficou verde"

    resultado = redigir(texto)

    assert resultado.texto == texto
    assert resultado.achados == {}


def test_exportador_nao_grava_segredo_no_banco(con: sqlite3.Connection) -> None:
    """Aceite (a): a prova é no banco, depois de gravar — não na função isolada."""
    memorias = [
        MemoriaDoOrchestrator(
            autor="dono",
            tipo="security",
            prioridade=10,
            titulo=f"chave do serviço: {SEGREDOS['chave_openai']}",
            corpo=f"e o token {SEGREDOS['token_github']} com {SEGREDOS['senha_declarada']}",
        )
    ]

    contagem = exportar(con, memorias)

    assert contagem.total_redigido >= 3
    gravado = " ".join(
        str(linha["text_redacted"])
        for linha in con.execute("SELECT text_redacted FROM memory_unit")
    )
    gravado += " ".join(
        str(linha["value_json"]) for linha in con.execute("SELECT value_json FROM assertion")
    )
    for valor in (SEGREDOS["chave_openai"], SEGREDOS["token_github"]):
        assert valor not in gravado


def test_caminho_de_segredo_nao_vira_entidade_do_grafo() -> None:
    """§6.7 + §5.5: `~/.ssh/id_rsa` citado numa memória não entra no grafo como entidade."""
    memoria = MemoriaDoOrchestrator(autor="qa", tipo="practice", prioridade=5, titulo="t", corpo="")
    texto = "o arquivo /home/sodre/.ssh/id_rsa e o /home/sodre/projetos/jarvis/notas.md"

    entidades = extrair_entidades(memoria, texto)
    nomes = [nome for _, nome in entidades]

    assert "/home/sodre/projetos/jarvis/notas.md" in nomes
    assert not any(".ssh" in nome for nome in nomes)


def test_classe_de_pii_sobe_na_duvida() -> None:
    assert classe_de_pii("menção a /home/sodre/.gnupg/secring") == "sensitive"
    assert classe_de_pii("sobrou um [REDIGIDO:email] aqui") == "metadata"
    assert classe_de_pii("o arquivo /home/sodre/doc/nota.md") == "path_only"
    assert classe_de_pii("sem nada demais") == "none"


# --- `n` e proveniência -----------------------------------------------------------
def test_exportador_publica_n_e_proveniencia(con: sqlite3.Connection) -> None:
    """Aceite (a) e (d): o `n` é o que dimensiona o grafo no cartão F0-05."""
    memorias = [
        MemoriaDoOrchestrator(
            autor="executor",
            tipo="practice",
            prioridade=8,
            titulo=f"nota {i}",
            corpo=f"mexi em /home/sodre/projeto/arquivo{i % 3}.py no commit abc123{i}",
            projeto="Jarvis",
        )
        for i in range(10)
    ]

    contagem = exportar(con, memorias)

    assert contagem.episodios == 10
    assert contagem.unidades == 10
    assert contagem.assertivas == 10
    assert contagem.entidades > 0
    assert contagem.mencoes >= contagem.episodios
    assert contagem.entidades_por_episodio > 0

    # P7: todo fato aponta para um episódio que existe.
    orfas = con.execute(
        "SELECT COUNT(*) AS n FROM assertion a"
        " LEFT JOIN episode e ON e.id = a.source_episode_id WHERE e.id IS NULL"
    ).fetchone()["n"]
    assert orfas == 0


def test_aresta_vira_ativa_so_com_duas_evidencias(con: sqlite3.Connection) -> None:
    """§6.7: aresta nasce `proposed`; duas evidências independentes a promovem."""
    # Este episódio cita dois arquivos que ninguém mais cita: o par entre eles tem
    # suporte 1 e precisa ficar `proposed`.
    uma_vez = MemoriaDoOrchestrator(
        autor="qa",
        tipo="practice",
        prioridade=5,
        titulo="x",
        corpo="mexi em /home/sodre/unico/a.py e /home/sodre/unico/b.py",
    )
    duas = [
        MemoriaDoOrchestrator(
            autor="qa", tipo="practice", prioridade=5, titulo=f"y{i}", corpo="o mesmo par de novo"
        )
        for i in range(2)
    ]

    exportar(con, [uma_vez, *duas])

    estados = {
        str(linha["status"]): int(linha["n"])
        for linha in con.execute("SELECT status, COUNT(*) AS n FROM entity_edge GROUP BY status")
    }
    assert estados.get("active", 0) > 0
    assert estados.get("proposed", 0) > 0


def test_reexportar_a_mesma_memoria_nao_duplica(con: sqlite3.Connection) -> None:
    memoria = MemoriaDoOrchestrator(
        autor="dono", tipo="decision", prioridade=9, titulo="decidi", corpo="assim"
    )

    exportar(con, [memoria])
    exportar(con, [memoria])

    assert int(con.execute("SELECT COUNT(*) AS n FROM episode").fetchone()["n"]) == 1
    assert int(con.execute("SELECT COUNT(*) AS n FROM memory_unit").fetchone()["n"]) == 1


# --- leitura do dump --------------------------------------------------------------
def test_parse_dump_le_o_formato_do_list_memories() -> None:
    texto = (
        "[IA: executor · practice · p8] Título da primeira\n"
        "corpo da primeira, com /home/sodre/x.py\n"
        "---\n"
        "[dono · security p10] Regra do dono\n"
        "não apagar bancos de dados\n"
    )

    memorias = parse_dump(texto, projeto="Jarvis")

    assert len(memorias) == 2
    assert memorias[0].autor == "executor"
    assert memorias[0].tipo == "practice"
    assert memorias[0].prioridade == 8
    assert "primeira" in memorias[0].titulo
    assert memorias[1].autor == "dono"
    assert memorias[1].prioridade == 10


def test_parse_jsonl() -> None:
    linhas = "\n".join(
        json.dumps(
            {"autor": "qa", "tipo": "practice", "prioridade": 3, "titulo": "t", "corpo": "c"}
        )
        for _ in range(3)
    )

    memorias = parse_jsonl(linhas, projeto="Jarvis")

    assert len(memorias) == 3
    assert memorias[0].projeto == "Jarvis"


def test_normalizar_tira_acento_e_caixa() -> None:
    assert normalizar("Memória  Semântica") == "memoria semantica"


# --- (b) manifesto de hashes ------------------------------------------------------
def montar_corpus(pasta: Path) -> None:
    (pasta / "turnos").mkdir(parents=True)
    (pasta / "README.md").write_text("corpus de teste\n", encoding="utf-8")
    (pasta / "turnos" / "rotulos.jsonl").write_text(
        '{"id": "t-1", "fim_de_turno": true}\n', encoding="utf-8"
    )


def test_manifesto_detecta_arquivo_alterado(tmp_path: Path) -> None:
    """Aceite (b)."""
    montar_corpus(tmp_path)
    (tmp_path / "manifesto.json").write_text(
        json.dumps(gerar_manifesto(tmp_path), ensure_ascii=False), encoding="utf-8"
    )
    assert verificar(tmp_path) == []

    (tmp_path / "turnos" / "rotulos.jsonl").write_text(
        '{"id": "t-1", "fim_de_turno": false}\n', encoding="utf-8"
    )

    divergencias = verificar(tmp_path)

    assert len(divergencias) == 1
    assert "conteúdo mudou" in divergencias[0].o_que


def test_manifesto_detecta_arquivo_novo_e_removido(tmp_path: Path) -> None:
    montar_corpus(tmp_path)
    (tmp_path / "manifesto.json").write_text(
        json.dumps(gerar_manifesto(tmp_path), ensure_ascii=False), encoding="utf-8"
    )

    (tmp_path / "turnos" / "extra.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "README.md").unlink()

    motivos = {d.o_que for d in verificar(tmp_path)}

    assert "existe e não está no manifesto" in motivos
    assert "está no manifesto e não existe mais" in motivos


def test_exportado_nao_entra_no_manifesto(tmp_path: Path) -> None:
    """`exportado/` é derivado e tem texto do dono: fica fora do repositório e do manifesto."""
    montar_corpus(tmp_path)
    (tmp_path / "exportado").mkdir()
    (tmp_path / "exportado" / "c1.sqlite").write_bytes(b"nao-versionado")

    manifesto = gerar_manifesto(tmp_path)

    assert not any("exportado" in nome for nome in manifesto["arquivos"])


def test_resumo_conta_itens_de_jsonl(tmp_path: Path) -> None:
    montar_corpus(tmp_path)

    contagem = resumo(tmp_path)

    assert contagem["turnos"] == 1
    assert contagem["turnos (itens)"] == 1


def test_corpus_do_repositorio_confere_com_o_manifesto() -> None:
    assert verificar() == []
