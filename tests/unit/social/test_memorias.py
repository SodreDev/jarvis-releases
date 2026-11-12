"""Memórias fixas (ADR-0060, fatia C): 0600, só no turno do assunto, sem telefone no prompt."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from jarvis.social.memorias import (
    CABECALHO,
    MemoriaFixa,
    MemoriaInvalida,
    bloco,
    editar,
    gravar,
    ler,
    nova,
    relevantes,
)

Memorias = tuple[MemoriaFixa, ...]


@pytest.fixture
def memorias() -> Memorias:
    return (
        nova(
            "contato", "Ana Souza", "colega do financeiro; trata de relatórios", "+55 11 98888-7777"
        ),
        nova("servico", "João Encanador", "encanador do prédio, atende sábado", "11 97777-6666"),
        nova("instrucao", "tom", "responda curto, sem emoji, e diga que eu retorno à tarde"),
    )


def test_volta_igual_do_arquivo_e_nasce_0600(tmp_path: Path, memorias: Memorias) -> None:
    caminho = tmp_path / "cfg" / "memorias-fixas.toml"
    gravar(memorias, caminho)
    assert ler(caminho) == memorias
    if os.name != "nt":
        assert stat.S_IMODE(caminho.stat().st_mode) == 0o600


def test_fala_fora_do_assunto_nao_leva_nada(memorias: Memorias) -> None:
    assert bloco("que horas são?", memorias) == ""
    assert relevantes("toca uma música", memorias) == []


def test_assunto_de_mensagem_leva_instrucao_e_contatos_sem_telefone(memorias: Memorias) -> None:
    texto = bloco("responde a mensagem do whatsapp", memorias)
    assert texto.startswith(CABECALHO)
    assert "Ana Souza" in texto and "responda curto" in texto
    assert "João Encanador" not in texto, "serviço só quando o assunto é serviço"
    assert "98888" not in texto and "97777" not in texto and "+55" not in texto


def test_servico_e_nome_citado(memorias: Memorias) -> None:
    assert "João Encanador" in bloco("preciso contratar um serviço de encanador", memorias)
    citado = bloco("o que a Ana falou?", memorias)
    assert "Ana Souza" in citado and "responda curto" in citado


def test_orcamento_corta_e_diz_quantas_ficaram_de_fora() -> None:
    muitas = tuple(nova("contato", f"Pessoa {i}", "x" * 300) for i in range(20))
    texto = bloco("mensagem", muitas, orcamento=1_000)
    assert len(texto) <= 1_100
    assert "não couberam neste turno" in texto


@pytest.mark.parametrize(
    ("campos", "trecho"),
    [
        ({"tipo": "senha", "nome": "x"}, "tipo"),
        ({"tipo": "contato", "nome": ""}, "nome"),
        ({"tipo": "contato", "nome": "x" * 81}, "nome"),
        ({"tipo": "contato", "nome": "x", "telefone": "ligue 123"}, "telefone"),
        ({"tipo": "instrucao", "nome": "x", "telefone": "11999998888"}, "instrução"),
    ],
)
def test_memoria_que_nao_cabe_e_recusada(campos: dict[str, str], trecho: str) -> None:
    with pytest.raises(MemoriaInvalida, match=trecho):
        nova(**campos)


def test_nome_com_controle_vira_texto_limpo() -> None:
    assert nova("contato", "Ana‮\nSouza").nome == "Ana Souza"


def test_editar_e_arquivo_quebrado(tmp_path: Path, memorias: Memorias) -> None:
    editadas = editar(memorias, memorias[0].id, texto="agora do RH")
    assert editadas[0].texto == "agora do RH" and editadas[1:] == memorias[1:]
    with pytest.raises(MemoriaInvalida):
        editar(memorias, "000000000000", texto="x")
    caminho = tmp_path / "memorias-fixas.toml"
    caminho.write_text('[[memoria]]\nid = "abc"\ntipo = "contato"\nnome = "x"\n', "utf-8")
    with pytest.raises(MemoriaInvalida, match="id"):
        ler(caminho)
