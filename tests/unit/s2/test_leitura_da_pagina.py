"""Ler a página antes de agir, e reler depois do erro (ADR-0069 §2), como VEREDITO ao modelo
(ADR-0072): a ação sem leitura não roda e o porquê volta a ele — o código não lê no lugar dele."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from jarvis.politica.permissao import ModoDePermissao
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.leitura_da_pagina import (
    CAUSA_DA_LEITURA,
    LEITURAS_FORCADAS,
    falta_ler,
    motivo_para_ler,
)
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.s2.roteiro_do_navegador import TENTATIVAS_POR_PASSO, roteiro
from tests.unit.s2.test_relato_verdadeiro import _dizer, _executor, _whatsapp

TODAS = ("browser.inspecionar", "browser.read", "browser.click", "browser.type")
DIGITAR = PedidoDeTool("browser.type", {"alvo": "Mensagem", "texto": "oi", "tab_id": 7})


@pytest.mark.parametrize(
    ("passos", "motivo"),
    [
        ((), "antes"),
        ((("browser.tabs", "ok"),), "antes"),
        ((("browser.navigate", "ok"),), "antes"),
        ((("browser.inspecionar", "ok"),), ""),
        ((("browser.read", "ok"), ("browser.type", "ok")), ""),  # digitar não muda a página
        ((("browser.read", "ok"), ("browser.click", "ok")), "antes"),  # clicar pode mudar
        ((("browser.read", "ok"), ("browser.type", "erro")), "depois_do_erro"),
        ((("browser.read", "ok"), ("browser.navigate", "ok")), "antes"),
        ((("browser.read", "erro"),), "antes"),  # leitura que falhou não vale
        (
            (("browser.read", "ok"), ("browser.click", "erro"), ("browser.inspecionar", "ok")),
            "",
        ),
    ],
)
def test_quando_falta_ler(passos: tuple[tuple[str, str], ...], motivo: str) -> None:
    assert falta_ler(passos) == motivo


def test_a_acao_sem_leitura_ganha_o_veredito_com_a_ferramenta_e_a_aba() -> None:
    motivo = motivo_para_ler(DIGITAR, (("browser.navigate", "ok"),), TODAS)
    assert motivo.startswith("não rodou: browser.type")
    assert "browser.inspecionar (tab_id 7)" in motivo


def test_depois_do_erro_o_veredito_diz_que_falhou() -> None:
    motivo = motivo_para_ler(DIGITAR, (("browser.read", "ok"), ("browser.type", "erro")), TODAS)
    assert "falhou" in motivo


def test_sem_inspecionar_manda_ler_o_texto_e_sem_leitura_nenhuma_segue() -> None:
    assert "browser.read" in motivo_para_ler(DIGITAR, (), ("browser.read", "browser.type"))
    assert motivo_para_ler(DIGITAR, (), ("browser.type",)) == ""


def test_leitura_que_vale_nao_e_cobrada_e_o_que_nao_e_acao_segue() -> None:
    assert motivo_para_ler(DIGITAR, (("browser.inspecionar", "ok"),), TODAS) == ""
    assert motivo_para_ler(PedidoDeTool("browser.read", {}), (), TODAS) == ""
    navegar = PedidoDeTool("browser.navigate", {"url": "https://a.example"})
    assert motivo_para_ler(navegar, (), TODAS) == ""


def test_depois_do_teto_de_vereditos_a_acao_segue() -> None:
    assert motivo_para_ler(DIGITAR, (), TODAS, recusadas=LEITURAS_FORCADAS) == ""


def test_no_turno_a_acao_sem_leitura_volta_ao_modelo_que_le_e_age(tmp_path: Path) -> None:
    """Com o WhatsApp falso: o motor manda digitar sem ter lido a página; a ação NÃO roda, o
    veredito volta a ele, ELE pede a inspeção e só então digita. O código não lê sozinho."""

    def resposta(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
        feitas = sum(1 for m in contexto.mensagens if m.papel == "ferramenta")
        if feitas == 0:
            return [PedidoDeTool("browser.type", {"alvo": "Mensagem", "texto": "Te amo, mãe!"})]
        if feitas == 1:
            return [PedidoDeTool("browser.inspecionar", {})]
        if feitas == 2:
            return [PedidoDeTool("browser.type", {"alvo": "Mensagem", "texto": "Te amo, mãe!"})]
        return ["Digitei a mensagem."]

    pagina = _whatsapp()
    for executor in _executor(tmp_path, pagina, ModoDePermissao.AUTOMATICO):
        cerebro = Cerebro(motor=MotorRoteirizado(resposta=resposta), ferramentas=executor)
        resultado, _falado = _dizer(cerebro, "escreve te amo pra minha mãe")
    primeiro, *resto = resultado.ferramentas
    assert (primeiro.tool_id, primeiro.status, primeiro.causa) == (
        "browser.type",
        "negado",
        CAUSA_DA_LEITURA,
    )
    assert [r.tool_id for r in resto][:2] == ["browser.inspecionar", "browser.type"]
    assert resultado.leituras_forcadas == 1
    digitados = [params for metodo, params in pagina.chamadas if metodo == "page.type"]
    assert len(digitados) == 1, "a ação recusada não chegou à página"


def test_a_orientacao_manda_ler_antes_e_depurar_no_erro() -> None:
    """ADR-0070: a orientação (não um roteiro de passos) diz ao subagente como trabalhar."""
    texto = roteiro(("browser.inspecionar", "browser.click"))
    assert "LEIA A PÁGINA antes de agir" in texto and "browser.inspecionar" in texto
    assert "releia e depure" in texto and f"até {TENTATIVAS_POR_PASSO} vezes por passo" in texto
