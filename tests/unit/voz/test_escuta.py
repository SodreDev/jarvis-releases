"""Modos de escuta, o estado vivo e a política de confirmação (ADR-0021).

A política é o ponto: o modelo pode **propor** trocar o modo, e o código decide se a troca
passa direto ou espera o sim do dono na tela. A tabela abaixo cobre todas as nove trocas, com
ASR local e com ASR na nuvem.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from jarvis.microfone import Modo
from jarvis.voz.config import Configuracao, ConfiguracaoInvalida, escrever, ler
from jarvis.voz.escuta import (
    ARMADO_POR_S,
    MODOS,
    CombinacaoInvalida,
    Escuta,
    ModoDeEscuta,
    confirmacao_necessaria,
    exigir_combinacao,
    gatilho_do_portal,
    modo_de,
)
from jarvis.voz.palavra import LIMIAR_PADRAO, PalavraInvalida

ATALHO, PALAVRA, CONTINUA = ModoDeEscuta.ATALHO, ModoDeEscuta.PALAVRA, ModoDeEscuta.CONTINUA


def test_valores_antigos_do_arquivo_continuam_valendo() -> None:
    # "ptt" e "vad" são o que o jarvis-voz.toml do dono já tem, e o que o indicador entende.
    assert ATALHO.value == "ptt" == Modo.PTT.value
    assert CONTINUA.value == "vad"
    assert MODOS == ("ptt", "palavra", "vad")
    assert modo_de("palavra") is PALAVRA


def test_modo_inventado_e_recusado_com_os_validos() -> None:
    with pytest.raises(ValueError, match="ptt, palavra, vad"):
        modo_de("sempre")


def test_so_o_atalho_nao_abre_sozinho() -> None:
    assert not ATALHO.abre_sozinho
    assert PALAVRA.abre_sozinho
    assert CONTINUA.abre_sozinho


# --- a política -----------------------------------------------------------------------------
PRECISA_LOCAL = {(ATALHO, CONTINUA), (PALAVRA, CONTINUA)}
PRECISA_NUVEM = PRECISA_LOCAL | {(ATALHO, PALAVRA)}


@pytest.mark.parametrize(("atual", "alvo"), list(itertools.product(ModoDeEscuta, ModoDeEscuta)))
@pytest.mark.parametrize("nuvem", [False, True])
def test_politica_de_confirmacao_em_todas_as_trocas(
    atual: ModoDeEscuta, alvo: ModoDeEscuta, nuvem: bool
) -> None:
    motivo = confirmacao_necessaria(alvo, atual=atual, asr_na_nuvem=nuvem)
    esperado = PRECISA_NUVEM if nuvem else PRECISA_LOCAL
    assert bool(motivo) == ((atual, alvo) in esperado), (atual, alvo, nuvem, motivo)


def test_atalho_e_palavra_trocam_sem_confirmacao_com_asr_local() -> None:
    assert confirmacao_necessaria(PALAVRA, atual=ATALHO, asr_na_nuvem=False) == ""
    assert confirmacao_necessaria(ATALHO, atual=PALAVRA, asr_na_nuvem=False) == ""


def test_escutar_menos_nunca_pede_permissao() -> None:
    for nuvem in (False, True):
        assert confirmacao_necessaria(ATALHO, atual=CONTINUA, asr_na_nuvem=nuvem) == ""
        assert confirmacao_necessaria(PALAVRA, atual=CONTINUA, asr_na_nuvem=nuvem) == ""
        assert confirmacao_necessaria(ATALHO, atual=PALAVRA, asr_na_nuvem=nuvem) == ""


def test_o_motivo_diz_o_que_sai_da_maquina() -> None:
    assert "sai da máquina" in confirmacao_necessaria(CONTINUA, atual=ATALHO, asr_na_nuvem=True)
    assert "fora da máquina" in confirmacao_necessaria(PALAVRA, atual=ATALHO, asr_na_nuvem=True)
    assert "nuvem" not in confirmacao_necessaria(CONTINUA, atual=ATALHO, asr_na_nuvem=False)


# --- o estado vivo --------------------------------------------------------------------------
def test_escuta_padrao_e_atalho_com_jarvis() -> None:
    escuta = Escuta()
    assert escuta.modo is ATALHO
    assert escuta.detector.palavra == "jarvis"
    assert escuta.detector.limiar == LIMIAR_PADRAO


def test_escuta_da_configuracao() -> None:
    escuta = Escuta.de("palavra", palavra="Sexta", limiar=0.8, atalho="Ctrl+Space")
    assert escuta.modo is PALAVRA
    assert escuta.detector.palavra == "sexta"
    assert escuta.detector.limiar == 0.8
    assert escuta.atalho == "Ctrl+Space"


def test_trocar_avisa_e_desarma() -> None:
    avisos: list[int] = []
    escuta = Escuta(modo=PALAVRA)
    escuta.ao_mudar = lambda: avisos.append(1)
    escuta.armar(0)
    escuta.trocar(CONTINUA)
    assert escuta.modo is CONTINUA
    assert escuta.armado_ate_ns == 0
    assert len(avisos) == 2


def test_palavra_invalida_nao_derruba_a_antiga() -> None:
    escuta = Escuta()
    with pytest.raises(PalavraInvalida):
        escuta.trocar_palavra("ô jarvis")
    assert escuta.detector.palavra == "jarvis"
    escuta.trocar_palavra("Sexta", 0.9)
    assert escuta.detector.palavra == "sexta"
    assert escuta.detector.limiar == 0.9
    escuta.trocar_palavra("jarvis")
    assert escuta.detector.limiar == 0.9  # sem limiar, mantém o que estava


def test_armado_vence_e_so_vale_no_modo_palavra() -> None:
    escuta = Escuta(modo=PALAVRA)
    escuta.armar(1_000)
    assert escuta.armado(1_000 + int(ARMADO_POR_S * 1e9) - 1)
    assert not escuta.armado(1_000 + int(ARMADO_POR_S * 1e9))
    escuta.armar(0)
    escuta.modo = ATALHO
    assert not escuta.armado(1)


def test_a_frase_diz_quando_o_jarvis_escuta() -> None:
    escuta = Escuta()
    assert "barra de espaço (com a janela em foco)" in escuta.frase(0)
    escuta.trocar_atalho("Ctrl+Space", global_=True)
    assert escuta.frase(0) == "só ouve enquanto você segura Ctrl+Space"
    escuta.trocar(PALAVRA)
    assert "“jarvis”" in escuta.frase(0)
    escuta.armar(0)
    assert escuta.frase(1) == "chamado: pode falar o pedido"
    escuta.trocar(CONTINUA)
    assert escuta.frase(0) == "todo trecho de fala vira pedido"
    dados = escuta.para_dict(0)
    assert dados["modo"] == "vad" and dados["modoFrase"] == "escuta contínua"
    assert dados["atalhoGlobal"] is True


# --- a combinação de teclas -----------------------------------------------------------------
@pytest.mark.parametrize(
    ("bruta", "normal", "portal"),
    [
        ("Ctrl+Space", "Ctrl+Space", "CTRL+space"),
        ("ctrl+shift+a", "Ctrl+Shift+A", "CTRL+SHIFT+a"),
        ("shift + ctrl + 1", "Ctrl+Shift+1", "CTRL+SHIFT+1"),
        ("Super+Espaço", "Meta+Space", "LOGO+space"),
        ("Ctrl+Alt+Return", "Ctrl+Alt+Return", "CTRL+ALT+Return"),
        ("Alt+Esc", "Alt+Esc", "ALT+Escape"),
        ("F9", "F9", "F9"),
        ("", "", ""),
    ],
)
def test_combinacao_normalizada_e_traduzida_para_o_portal(
    bruta: str, normal: str, portal: str
) -> None:
    assert exigir_combinacao(bruta) == normal
    assert gatilho_do_portal(bruta) == portal
    assert exigir_combinacao(normal) == normal  # idempotente


@pytest.mark.parametrize(
    ("bruta", "trecho"),
    [
        ("a", "modificador"),
        ("Space", "modificador"),
        ("Ctrl+", "sem tecla"),
        ("Hyper+a", "não é modificador"),
        ("Ctrl+ç", "não é uma que o atalho aceita"),
        ("Ctrl+F99", "não é uma que o atalho aceita"),
    ],
)
def test_combinacao_que_nao_serve_e_recusada(bruta: str, trecho: str) -> None:
    with pytest.raises(CombinacaoInvalida, match=trecho):
        exigir_combinacao(bruta)


# --- no arquivo do dono ---------------------------------------------------------------------
def test_palavra_limiar_e_atalho_vao_e_voltam_do_arquivo(tmp_path: Path) -> None:
    caminho = tmp_path / "jarvis-voz.toml"
    escrever(
        Configuracao(escuta="palavra", palavra="sexta", limiar_palavra=0.8, atalho="Ctrl+Space"),
        caminho,
    )
    lida = ler(caminho)
    assert (lida.escuta, lida.palavra, lida.limiar_palavra, lida.atalho) == (
        "palavra",
        "sexta",
        0.8,
        "Ctrl+Space",
    )


def test_arquivo_antigo_sem_os_campos_novos_continua_valendo(tmp_path: Path) -> None:
    caminho = tmp_path / "jarvis-voz.toml"
    caminho.write_text('escuta = "vad"\n', encoding="utf-8")
    lida = ler(caminho)
    assert lida.escuta == "vad"
    assert lida.palavra == "jarvis" and lida.limiar_palavra == LIMIAR_PADRAO
    assert lida.atalho == ""


@pytest.mark.parametrize(
    ("linha", "trecho"),
    [
        ('escuta = "sempre"', "Válidos: ptt, palavra, vad"),
        ('palavra = "ô jarvis"', "mais de uma palavra"),
        ("limiar_palavra = 0.2", "fora da faixa"),
        ('limiar_palavra = "alto"', "esperava número"),
        ('atalho = "j"', "modificador"),
    ],
)
def test_arquivo_com_escuta_que_nao_serve_e_recusado(
    tmp_path: Path, linha: str, trecho: str
) -> None:
    caminho = tmp_path / "jarvis-voz.toml"
    caminho.write_text(linha + "\n", encoding="utf-8")
    with pytest.raises(ConfiguracaoInvalida, match=trecho):
        ler(caminho)
