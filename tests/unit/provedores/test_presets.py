"""Presets de modelo: arquivo do dono, sem segredo, o da configuração em memória, troca por voz."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from jarvis.provedores.presets import (
    DA_CONFIGURACAO,
    FonteDePresets,
    Preset,
    Presets,
    PresetsInvalidos,
    TrocaPorVoz,
    do_dono,
    gravar,
    ler,
    padrao,
)
from jarvis.voz.config import Configuracao

UM = """
versao = 1
[ativos]
cerebro = "Rápido"
[[preset]]
nome = "rápido"
papel = "cerebro"
provedor = "conversa-groq"
modelo = "openai/gpt-oss-20b"
esforco = "low"
"""


def test_o_padrao_do_repositorio_e_valido_e_nao_liga_cerebro() -> None:
    presets = padrao()
    assert presets.origem == "padrao" and presets.avisos == ()
    assert presets.ativos["cerebro"] == ""  # vale o da configuração
    assert presets.ativo("jev") is not None
    assert {p.papel for p in presets.presets} == {"cerebro", "jev", "visao", "resumo"}


def test_o_arquivo_do_dono_vence_e_o_ativo_acha_sem_acento_nem_caixa(tmp_path: Path) -> None:
    (tmp_path / "jarvis").mkdir()
    (tmp_path / "jarvis" / "presets.toml").write_text(UM, encoding="utf-8")
    presets = do_dono(ambiente={"XDG_CONFIG_HOME": str(tmp_path)})
    ativo = presets.ativo("cerebro")
    assert ativo is not None and ativo.nome == "rápido" and ativo.esforco == "low"
    assert presets.por_nome("RAPIDO") is ativo


def test_arquivo_quebrado_vale_o_padrao_com_o_aviso(tmp_path: Path) -> None:
    (tmp_path / "jarvis").mkdir()
    (tmp_path / "jarvis" / "presets.toml").write_text("[[preset]\nnome=", encoding="utf-8")
    presets = do_dono(ambiente={"XDG_CONFIG_HOME": str(tmp_path)})
    assert presets.avisos and "não serviu" in presets.avisos[0]


@pytest.mark.parametrize(
    "linha",
    [
        'api_key = "qualquer"',
        'modelo = "sk-proj-abcdefghijklmnopqrstu"',
        'nota = "minha chave gsk_abcdefghijklmnopqrstu"',
    ],
)
def test_segredo_no_arquivo_recusa_o_arquivo_inteiro(tmp_path: Path, linha: str) -> None:
    arquivo = tmp_path / "presets.toml"
    arquivo.write_text(UM + linha + "\n", encoding="utf-8")
    with pytest.raises(PresetsInvalidos):
        ler(arquivo)


def test_preset_fora_da_forma_fica_de_fora_com_aviso(tmp_path: Path) -> None:
    arquivo = tmp_path / "presets.toml"
    arquivo.write_text(
        UM
        + '[[preset]]\nnome = "x"\npapel = "chefe"\nprovedor = "conversa-eco"\n'
        + '[[preset]]\nnome = "y"\npapel = "cerebro"\nprovedor = "conversa-eco"\nmodelo = "a b"\n'
        + '[[preset]]\nnome = "rapido"\npapel = "cerebro"\nprovedor = "conversa-eco"\n',
        encoding="utf-8",
    )
    presets = ler(arquivo)
    assert [p.nome for p in presets.presets] == ["rápido"]
    assert len(presets.avisos) == 3  # papel inexistente, modelo com espaço, nome repetido


def test_o_preset_da_configuracao_so_existe_em_memoria(tmp_path: Path) -> None:
    configuracao = Configuracao(s2="claude", modelo_do_s2="sonnet")
    presets = do_dono(configuracao, ambiente={})
    legado = presets.ativo("cerebro")
    assert legado is not None and legado.da_configuracao and legado.modelo == "sonnet"
    gravado = gravar(presets, tmp_path / "presets.toml")
    relido = ler(gravado)
    assert all(p.nome != DA_CONFIGURACAO for p in relido.presets)
    assert relido.ativos["cerebro"] == ""


def test_com_preset_troca_o_de_mesmo_nome_e_sem_preset_desliga_o_ativo() -> None:
    base = Presets((Preset("a", "cerebro", "conversa-eco"),), {"cerebro": "a"})
    trocado = base.com_preset(Preset("A", "visao", "conversa-groq", "qwen/qwen3.8-27b"))
    assert [p.papel for p in trocado.presets] == ["visao"]
    assert trocado.ativo("cerebro") is None  # mudou de papel: não fica ativo onde não cabe
    assert base.sem_preset("a").ativo("cerebro") is None
    with pytest.raises(PresetsInvalidos):
        base.com_ativo("visao", "a")


def test_a_fonte_rele_quando_o_arquivo_muda(tmp_path: Path) -> None:
    fonte = FonteDePresets(pasta=tmp_path)
    assert fonte.atuais().origem == "padrao"
    (tmp_path / "presets.toml").write_text(UM, encoding="utf-8")
    assert fonte.atuais().origem.endswith("presets.toml")
    fonte.gravar(fonte.atuais().com_ativo("cerebro", ""))
    os.utime(tmp_path / "presets.toml", (time.time() + 5, time.time() + 5))
    assert fonte.atuais().ativos["cerebro"] == ""


def troca(tmp_path: Path, ligados: set[str]) -> tuple[TrocaPorVoz, FonteDePresets]:
    fonte = FonteDePresets(pasta=tmp_path, configuracao=Configuracao(s2="eco"))
    return TrocaPorVoz(fonte, ligado=lambda p: p in ligados or p == "conversa-eco"), fonte


def test_troca_por_voz_ativa_grava_e_desfaz_para_o_da_configuracao(tmp_path: Path) -> None:
    voz, fonte = troca(tmp_path, {"conversa-groq"})
    assert fonte.atuais().ativo("cerebro").da_configuracao  # type: ignore[union-attr]

    dados = voz.usar("rapido")

    assert dados["preset"] == "rápido" and dados["papel"] == "cerebro"
    assert dados["desfazer"] == "cerebro="  # antes valia o da configuração
    assert fonte.atuais().ativo("cerebro").nome == "rápido"  # type: ignore[union-attr]
    voz.voltar(dados["desfazer"])
    assert fonte.atuais().ativo("cerebro").da_configuracao  # type: ignore[union-attr]


def test_troca_por_voz_nao_liga_nuvem_nem_inventa_preset(tmp_path: Path) -> None:
    voz, _ = troca(tmp_path, set())
    with pytest.raises(ValueError, match="desligado"):
        voz.usar("rápido")
    with pytest.raises(ValueError, match="não há preset"):
        voz.usar("turbo máximo")
    assert not (tmp_path / "presets.toml").exists()
