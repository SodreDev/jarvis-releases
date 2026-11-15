"""Ler a página antes de agir, e reler depois do erro (ADR-0069 §2): a regra pura, sem navegador."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from jarvis.politica.permissao import ModoDePermissao
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.leitura_da_pagina import (
    LEITURAS_FORCADAS,
    NOTA_DA_LEITURA,
    falta_ler,
    leitura_antes,
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


def test_a_acao_sem_leitura_vira_a_inspecao_da_mesma_aba() -> None:
    leitura = leitura_antes(DIGITAR, (("browser.navigate", "ok"),), TODAS)
    assert leitura == PedidoDeTool("browser.inspecionar", {"tab_id": 7})


def test_sem_inspecionar_le_o_texto_e_sem_leitura_nenhuma_segue() -> None:
    assert leitura_antes(DIGITAR, (), ("browser.read", "browser.type")) == PedidoDeTool(
        "browser.read", {"tab_id": 7}
    )
    assert leitura_antes(DIGITAR, (), ("browser.type",)) is None


def test_leitura_que_vale_nao_e_repetida_e_o_que_nao_e_acao_segue() -> None:
    assert leitura_antes(DIGITAR, (("browser.inspecionar", "ok"),), TODAS) is None
    assert leitura_antes(PedidoDeTool("browser.read", {}), (), TODAS) is None
    assert (
        leitura_antes(PedidoDeTool("browser.navigate", {"url": "https://a.example"}), (), TODAS)
        is None
    )


def test_depois_do_teto_de_leituras_forcadas_a_acao_segue() -> None:
    assert leitura_antes(DIGITAR, (), TODAS, forcadas=LEITURAS_FORCADAS) is None


def test_no_turno_o_jarvis_le_a_pagina_antes_da_acao_que_veio_sem_leitura(tmp_path: Path) -> None:
    """Com o WhatsApp falso: o motor manda digitar sem ter lido a página; o código inspeciona
    antes, o motor vê o mapa (e a nota) e só então digita."""
    vistos: list[str] = []

    def resposta(contexto: Contexto) -> Sequence[str | PedidoDeTool]:
        feitas = sum(1 for m in contexto.mensagens if m.papel == "ferramenta")
        vistos.append(contexto.sistema)
        if feitas == 0:
            return [PedidoDeTool("browser.type", {"alvo": "Mensagem", "texto": "Te amo, mãe!"})]
        if feitas == 1:
            return [PedidoDeTool("browser.type", {"alvo": "Mensagem", "texto": "Te amo, mãe!"})]
        return ["Digitei a mensagem."]

    for executor in _executor(tmp_path, _whatsapp(), ModoDePermissao.AUTOMATICO):
        cerebro = Cerebro(motor=MotorRoteirizado(resposta=resposta), ferramentas=executor)
        resultado, _falado = _dizer(cerebro, "escreve te amo pra minha mãe")
    assert [r.tool_id for r in resultado.ferramentas][:2] == ["browser.inspecionar", "browser.type"]
    assert resultado.leituras_forcadas == 1
    assert any(NOTA_DA_LEITURA in s for s in vistos[1:])


def test_a_orientacao_manda_ler_antes_e_depurar_no_erro() -> None:
    """ADR-0070: a orientação (não um roteiro de passos) diz ao subagente como trabalhar."""
    texto = roteiro("abre o youtube e procura música", ("browser.inspecionar", "browser.click"))
    assert "LEIA A PÁGINA antes de agir" in texto and "browser.inspecionar" in texto
    assert "releia e depure" in texto and f"até {TENTATIVAS_POR_PASSO} vezes por passo" in texto
    envio = roteiro("abre o contato da minha mãe e diz eu te amo", ("browser.inspecionar",))
    assert "LEIA A PÁGINA antes de agir" in envio and "releia e depure" in envio
