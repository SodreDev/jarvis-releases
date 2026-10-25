"""As regras do dono e o catálogo do turno (dono, 2026-10-25; ADR-0047).

O dono pediu um system prompt e "regras estruturadas na memória para o Jarvis agir como o Jarvis
agiria", com o catálogo de ferramentas sempre no contexto — nome, quando usar e pedidos naturais —,
gerado do registro real e enxuto, porque vai em todo turno. Aqui: as regras padrão valem e o
arquivo do dono vence (com limites e avisos, sem nunca ler a pasta do dono num teste); o catálogo
sai dos manifestos, uma linha por ferramenta, com os exemplos dos pedidos que importam; e o prompt
inteiro cabe no teto.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from tools.medir_prompt import executor_completo

from jarvis.manifesto.validador import carregar_catalogo as carregar_manifestos
from jarvis.s2.cerebro import Conversa
from jarvis.s2.motor_claude_cli import (
    INSTRUCAO_DE_FERRAMENTAS,
    assinatura,
    linha_da_ferramenta,
    sistema_com_ferramentas,
)
from jarvis.s2.persona import prompt_de_sistema, sistema_do_jarvis
from jarvis.s2.regras import (
    ARQUIVO_PADRAO,
    CABECALHO,
    MAXIMO_DE_REGRAS,
    MAXIMO_DO_TEXTO,
    RegrasInvalidas,
    do_dono,
    ler,
    na_pasta,
    padrao,
)
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao
from jarvis.voz.vocabulario import RepositorioDoVocabulario

TETO_DO_PROMPT = 16_000
"""Caracteres do prompt de sistema de um turno com todas as ferramentas (persona, regras e
catálogo). Antes da ADR-0047 eram 30 550; o teto segura o que cresce em todo pedido."""


# --- as regras -------------------------------------------------------------------------------
def test_as_regras_padrao_sao_poucas_e_fortes_e_vao_depois_da_persona() -> None:
    regras = padrao()
    assert regras.origem == "padrao" and not regras.avisos
    assert 4 <= len(regras.regras) <= MAXIMO_DE_REGRAS
    assert all(len(r.texto) <= MAXIMO_DO_TEXTO for r in regras.regras)
    bloco = regras.bloco()
    assert bloco.startswith(CABECALHO) and len(bloco) <= 1200
    for trecho in ("Conciso e direto", "nunca peça ao dono", "pelo contexto", "Uma resposta"):
        assert trecho in bloco, trecho
    sistema = sistema_do_jarvis()
    assert sistema.startswith(prompt_de_sistema()) and sistema.endswith(bloco)
    assert Conversa().sistema == sistema, "o cérebro já nasce com persona e regras"


def test_o_exemplo_do_dono_e_o_padrao_do_repositorio() -> None:
    exemplo = ler(Path(__file__).parents[3] / "docs" / "exemplos" / "regras.toml")
    assert exemplo.regras == padrao().regras, "o exemplo e o padrão não podem divergir"


def _arquivo(pasta: Path, corpo: str) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "regras.toml"
    arquivo.write_text(corpo, encoding="utf-8")
    return arquivo


def test_o_arquivo_do_dono_vence_desliga_e_corta(tmp_path: Path) -> None:
    longa = "x " * 200
    _arquivo(
        tmp_path / "jarvis",
        "[[regra]]\nid = 'a'\ntexto = 'Fale baixo.'\n"
        "[[regra]]\nid = 'b'\ntexto = 'Nunca diga bom dia.'\nligada = false\n"
        f"[[regra]]\nid = 'c'\ntexto = '{longa}'\n",
    )

    regras = do_dono({"XDG_CONFIG_HOME": str(tmp_path)})

    assert regras.origem.endswith("regras.toml")
    assert [r.id for r in regras.regras] == ["a", "c"], "a desligada fica de fora"
    assert len(regras.regras[1].texto) <= MAXIMO_DO_TEXTO + 1
    assert any("cortada" in aviso for aviso in regras.avisos)


def test_regras_demais_ficam_de_fora_com_aviso(tmp_path: Path) -> None:
    corpo = "".join(f"[[regra]]\nid = 'r{i}'\ntexto = 'Regra {i}.'\n" for i in range(20))
    regras = ler(_arquivo(tmp_path, corpo))
    assert len(regras.regras) == MAXIMO_DE_REGRAS and regras.avisos


@pytest.mark.parametrize("corpo", ["isto não é toml [", "versao = 1\n", "[[regra]]\nid = 'a'\n"])
def test_arquivo_do_dono_que_nao_serve_vale_o_padrao_com_aviso(tmp_path: Path, corpo: str) -> None:
    with pytest.raises(RegrasInvalidas):
        ler(_arquivo(tmp_path, corpo))
    regras = na_pasta(tmp_path)
    assert regras.origem == "padrao" and regras.regras == padrao().regras
    assert regras.avisos and "não serviu" in regras.avisos[0]


def test_ambiente_explicito_sem_pasta_de_configuracao_nunca_le_a_do_dono() -> None:
    assert do_dono({"CI": "1"}).origem == "padrao"
    assert ARQUIVO_PADRAO.name == "regras.toml" and ARQUIVO_PADRAO.is_file()


def test_o_aplicativo_poe_as_regras_do_dono_no_cerebro(tmp_path: Path) -> None:
    configuracao = tmp_path / "config"
    _arquivo(configuracao, "[[regra]]\nid = 'a'\ntexto = 'Responda sempre em uma frase.'\n")
    app = Aplicativo(
        configuracao=Configuracao(tts="tts-parametrico", s2="eco"),
        raiz=tmp_path / "sessao",
        escrever_na_tela=lambda _l: None,
        ambiente={"CI": "1", "JARVIS_AUDIO_BACKEND": "arquivo"},
        vocabulario=RepositorioDoVocabulario(configuracao),
    )
    app.abrir(com_asr=False)
    assert app._cerebro is not None and app.regras is not None
    assert app._cerebro.conversa.sistema.endswith("- Responda sempre em uma frase.")
    assert app._cerebro.conversa.sistema.startswith(prompt_de_sistema())

    sem = Aplicativo(
        configuracao=Configuracao(tts="tts-parametrico", s2="eco"),
        raiz=tmp_path / "outra",
        escrever_na_tela=lambda _l: None,
        ambiente={"CI": "1", "JARVIS_AUDIO_BACKEND": "arquivo"},
    )
    sem.abrir(com_asr=False)
    assert sem._cerebro is not None and sem._cerebro.conversa.sistema == sistema_do_jarvis()


# --- o catálogo do turno -----------------------------------------------------------------------
@pytest.fixture(scope="module")
def catalogo() -> Iterator[tuple[dict[str, Any], ...]]:
    with tempfile.TemporaryDirectory(prefix="catalogo-") as pasta:
        yield executor_completo(Path(pasta)).catalogo_para_o_modelo()


def test_o_catalogo_sai_do_registro_uma_linha_por_ferramenta(
    catalogo: tuple[dict[str, Any], ...],
) -> None:
    manifestos = carregar_manifestos()
    sistema = sistema_com_ferramentas("PERSONA", catalogo)
    linhas = [linha for linha in sistema.splitlines() if linha.startswith("- ")]
    assert len(linhas) == len(catalogo) >= 50
    for ferramenta, linha in zip(catalogo, linhas, strict=True):
        manifesto = manifestos[ferramenta["id"]]
        assert linha.startswith(f"- {ferramenta['id']}("), linha
        assert str(manifesto["quando"]).rstrip(".") in linha, "o quando é o do manifesto"
    assert INSTRUCAO_DE_FERRAMENTAS in sistema and '"input_schema"' not in sistema
    assert '"type": "string"' not in sistema, "o esquema JSON inteiro saiu do prompt"


@pytest.mark.parametrize(
    ("ferramenta", "pedido"),
    [
        ("apps.launch", "abre o Discord"),
        ("window.close", "fecha o Discord"),
        ("window.close", "fecha o navegador"),
        ("apps.quit", "fecha o Discord todo"),
        ("browser.launch", "abre o navegador"),
        ("browser.navigate", "abre o YouTube"),
        ("window.focus_app", "foca no Discord"),
        ("window.focused", "o que está na tela?"),
        ("vocabulario.aprender", "o certo é Discord"),
        ("jarvis.encerrar", "encerra o sistema"),
    ],
)
def test_os_pedidos_naturais_que_importam_estao_no_catalogo(
    catalogo: tuple[dict[str, Any], ...], ferramenta: str, pedido: str
) -> None:
    (item,) = [f for f in catalogo if f["id"] == ferramenta]
    assert f"«{pedido}»" in linha_da_ferramenta(item)


def test_a_assinatura_diz_obrigatorio_tipo_e_valores() -> None:
    argumentos = {
        "url": {"type": "string"},
        "segundo_plano": {"type": "boolean"},
        "acao": {"enum": ["tocar", "pausar"]},
        "pixels": {"type": "integer"},
    }
    assert assinatura(argumentos, ["url", "acao"]) == (
        "url*, segundo_plano:bool, acao*=tocar|pausar, pixels:int"
    )


def test_o_que_so_esta_sessao_sabe_vai_junto(catalogo: tuple[dict[str, Any], ...]) -> None:
    (lancar,) = [f for f in catalogo if f["id"] == "apps.launch"]
    assert "Autorizados agora:" in linha_da_ferramenta(lancar)
    (navegador,) = [f for f in catalogo if f["id"] == "browser.launch"]
    assert "Configurados agora: brave (principal)." in linha_da_ferramenta(navegador)


def test_o_prompt_do_turno_cabe_no_teto(catalogo: tuple[dict[str, Any], ...]) -> None:
    sistema = sistema_com_ferramentas(sistema_do_jarvis(), catalogo)
    assert len(sistema) <= TETO_DO_PROMPT, len(sistema)
