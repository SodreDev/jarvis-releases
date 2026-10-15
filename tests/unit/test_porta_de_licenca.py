"""Aceite F0-09: a porta de licença falha em NC injetado, e a tabela comitada não apodrece.

ADR-0011: licença é requisito de produto. O que este arquivo prova é que a porta bloqueia de
verdade — num modelo não comercial e numa dependência não comercial.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from tools.license_gate import (
    ARQUIVO_MODELOS,
    inventariar_dependencias,
    inventariar_ferramentas,
    inventariar_modelos,
    main,
)

from jarvis.licencas import Categoria, classificar

RAIZ = Path(__file__).resolve().parents[2]

MODELOS_NOMEADOS_NO_CARTAO = (
    "BAAI/bge-reranker-v2-m3",
    "Qwen/Qwen3-Reranker-0.6B",
    "mixedbread-ai/mxbai-rerank-large-v2",
    "intfloat/multilingual-e5-base",
    "BAAI/bge-m3",
    "Qwen/Qwen3-Embedding-0.6B",
)

MODELO_NC = """
data_da_verificacao = "2026-10-15"

[[modelo]]
id = "exemplo/reranker-de-pesquisa"
papel = "reranker"
licenca = "CC-BY-NC-4.0"
estado = "candidato"
fonte = "https://huggingface.co/api/models/exemplo/reranker-de-pesquisa"
data_de_acesso = "2026-10-15"
"""

MODELO_LIMPO = MODELO_NC.replace("CC-BY-NC-4.0", "Apache-2.0")


def escrever_pacote_falso(pasta: Path, nome: str, licenca: str) -> None:
    """Cria um `.dist-info` mínimo — é assim que um pacote declara licença ao Python."""
    info = pasta / f"{nome}-1.0.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.4\nName: {nome}\nVersion: 1.0.0\nLicense-Expression: {licenca}\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("licenca", "categoria"),
    [
        ("Apache-2.0", Categoria.PERMISSIVA),
        ("MIT", Categoria.PERMISSIVA),
        ("Mozilla Public License 2.0 (MPL 2.0)", Categoria.PERMISSIVA),
        ("CC-BY-4.0", Categoria.ATRIBUICAO),
        ("GPL-3.0", Categoria.COPYLEFT_FORTE),
        ("AGPL-3.0", Categoria.COPYLEFT_FORTE),
        ("CC-BY-NC-4.0", Categoria.NAO_COMERCIAL),
        ("cc-by-nc-sa-4.0", Categoria.NAO_COMERCIAL),
        ("coqui-public-model-license", Categoria.NAO_COMERCIAL),
        ("PolyForm Noncommercial 1.0.0", Categoria.NAO_COMERCIAL),
        ("Research only, no commercial use", Categoria.NAO_COMERCIAL),
        ("other", Categoria.DESCONHECIDA),
        (None, Categoria.DESCONHECIDA),
    ],
)
def test_classificacao_de_licenca(licenca: str | None, categoria: Categoria) -> None:
    assert classificar(licenca) is categoria


def test_porta_passa_no_repositorio_como_esta() -> None:
    assert main([]) == 0


def test_porta_falha_em_modelo_nao_comercial_injetado(tmp_path: Path) -> None:
    """Aceite (a), parte dos modelos."""
    arquivo = tmp_path / "modelos.toml"
    arquivo.write_text(MODELO_NC, encoding="utf-8")

    assert main(["--modelos", str(arquivo)]) == 1
    arquivo.write_text(MODELO_LIMPO, encoding="utf-8")
    assert main(["--modelos", str(arquivo)]) == 0


def test_porta_falha_em_dependencia_nao_comercial_injetada(tmp_path: Path) -> None:
    """Aceite (a), parte das dependências: um `.dist-info` de verdade, com licença NC."""
    pacotes = tmp_path / "site-packages"
    escrever_pacote_falso(pacotes, "reranker_nc", "CC-BY-NC-4.0")
    escrever_pacote_falso(pacotes, "biblioteca_ok", "MIT")

    codigo = main(["--pasta-pacotes", str(pacotes)])

    assert codigo == 1
    nomes = {item.nome.split()[0] for item in inventariar_dependencias([str(pacotes)])}
    assert nomes == {"reranker_nc", "biblioteca_ok"}


def test_porta_falha_em_dependencia_sem_licenca_declarada(tmp_path: Path) -> None:
    pacotes = tmp_path / "site-packages"
    info = pacotes / "misterio-1.0.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        "Metadata-Version: 2.4\nName: misterio\nVersion: 1.0.0\n", encoding="utf-8"
    )

    assert main(["--pasta-pacotes", str(pacotes)]) == 1


def test_modelo_barrado_nao_derruba_a_porta_mas_fica_registrado() -> None:
    """Registrar um NC como `barrado` é documentação, não uso: a porta continua verde."""
    barrados = [m for m in inventariar_modelos() if m.estado == "barrado"]

    assert {m.nome for m in barrados} == {
        "jinaai/jina-reranker-v2-base-multilingual",
        "coqui/XTTS-v2",
    }
    assert all(m.categoria is Categoria.NAO_COMERCIAL for m in barrados)
    assert not any(m.bloqueia for m in barrados)


@pytest.mark.parametrize("modelo", MODELOS_NOMEADOS_NO_CARTAO)
def test_os_seis_model_cards_do_cartao_estao_verificados(modelo: str) -> None:
    """Aceite (b): cada um com licença, fonte oficial e data de acesso."""
    registro = {m.nome: m for m in inventariar_modelos()}[modelo]

    assert registro.categoria in (Categoria.PERMISSIVA, Categoria.ATRIBUICAO)
    assert registro.origem.startswith("https://huggingface.co/api/models/")
    assert registro.data_de_acesso == "2026-10-15"


def test_registro_cobre_os_cinco_papeis_de_modelo() -> None:
    """O cartão pede embedding, reranker, VAD, ASR e TTS."""
    papeis = {m.tipo.removeprefix("modelo/") for m in inventariar_modelos()}

    assert papeis == {"embedding", "reranker", "vad", "asr", "tts"}


def test_tabela_comitada_esta_atualizada() -> None:
    """Aceite (b): a tabela em docs/licencas.md não pode divergir do registro."""
    assert main(["--verificar-tabela"]) == 0


def test_porta_roda_como_processo_do_zero() -> None:
    """Aceite (c): é isso que o CI executa nos dois sistemas."""
    concluido = subprocess.run(
        [sys.executable, str(RAIZ / "tools" / "license_gate.py"), "--verificar-tabela"],
        capture_output=True,
        text=True,
        check=False,
        cwd=RAIZ,
    )

    assert concluido.returncode == 0, concluido.stdout + concluido.stderr
    assert "OK: nenhuma licença não comercial" in concluido.stdout
    assert ARQUIVO_MODELOS.exists()


FERRAMENTA_FORA = """
data_da_verificacao = "2026-10-15"
verificado_por = "teste"

[[ferramenta]]
id = "espeak-ng"
papel = "fonemizador do gerador de corpus"
licenca = "GPL-3.0"
estado = "fora_do_produto"
fonte = "https://api.github.com/repos/espeak-ng/espeak-ng/license"
data_de_acesso = "2026-10-15"
"""
FERRAMENTA_NO_PRODUTO = FERRAMENTA_FORA.replace("fora_do_produto", "em_uso")
FERRAMENTA_NAO_COMERCIAL = FERRAMENTA_FORA.replace("GPL-3.0", "CC-BY-NC-4.0")


def test_copyleft_forte_fora_do_produto_avisa_mas_nao_bloqueia(tmp_path: Path) -> None:
    """Cartão F1-02: o espeak-ng gera o corpus em processo separado e não entra no produto."""
    arquivo = tmp_path / "ferramentas.toml"
    arquivo.write_text(FERRAMENTA_FORA, encoding="utf-8")

    assert main(["--ferramentas", str(arquivo)]) == 0

    itens = inventariar_ferramentas(arquivo)
    assert [i.categoria for i in itens] == [Categoria.COPYLEFT_FORTE]
    assert not any(i.bloqueia for i in itens)


def test_a_mesma_ferramenta_no_caminho_do_produto_bloqueia(tmp_path: Path) -> None:
    """Abrir o derivado é decisão do dono, não de uma dependência que entrou de lado."""
    arquivo = tmp_path / "ferramentas.toml"
    arquivo.write_text(FERRAMENTA_NO_PRODUTO, encoding="utf-8")

    assert main(["--ferramentas", str(arquivo)]) == 1
    assert all(i.bloqueia for i in inventariar_ferramentas(arquivo))


def test_ferramenta_nao_comercial_bloqueia_mesmo_fora_do_produto(tmp_path: Path) -> None:
    """Dado gerado por ferramenta não comercial é dado contaminado (ADR-0011)."""
    arquivo = tmp_path / "ferramentas.toml"
    arquivo.write_text(FERRAMENTA_NAO_COMERCIAL, encoding="utf-8")

    assert main(["--ferramentas", str(arquivo)]) == 1


def test_o_registro_do_repositorio_tem_o_espeak_fora_do_produto() -> None:
    registro = {i.nome.split()[0]: i for i in inventariar_ferramentas()}

    assert registro["espeak-ng"].estado == "fora_do_produto"
    assert registro["espeak-ng"].categoria is Categoria.COPYLEFT_FORTE
    assert "piper-tts" in registro["espeak-ng"].nota


def test_a_voz_do_corpus_esta_verificada_voz_por_voz() -> None:
    """Cartão F1-02: a voz escolhida tem licença permissiva e dataset CC0, com fonte oficial."""
    registro = {m.nome: m for m in inventariar_modelos()}
    voz = registro["rhasspy/piper-voices:pt_BR-faber-medium"]

    assert voz.categoria is Categoria.PERMISSIVA
    assert voz.estado == "em_uso"
    assert voz.origem.startswith("https://huggingface.co/api/models/")
    assert "CC0" in voz.nota and "edresson" in voz.nota
