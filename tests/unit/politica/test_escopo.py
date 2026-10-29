"""O escopo do pedido (dono, 2026-10-29; ADR-0057): o contido roda direto, o resto segue a regra de
sempre. Os dois lados de cada linha da tabela."""

from __future__ import annotations

import pytest

from jarvis.politica.escopo import julgar
from jarvis.politica.objetivo import Objetivo

CNN = Objetivo.do_pedido("abre a cnn no brave")


@pytest.mark.parametrize(
    ("tool_id", "args", "contido"),
    [
        ("browser.navigate", {"url": "https://edition.cnn.com/world"}, True),
        ("sites.open", {"url": "https://www.cnn.com/"}, True),
        ("browser.read", {}, True),
        ("browser.navigate", {"url": "https://mal.example/"}, False),
        ("browser.navigate", {"url": "https://mal.example/?email=dono@exemplo.com"}, False),
        ("browser.launch", {"navegador": "brave"}, True),
        ("apps.launch", {"nome": "Brave"}, True),
        ("window.focus_app", {"app": "brave"}, True),
        ("window.close", {"app": "Brave"}, True),
        ("apps.quit", {"app": "Discord"}, False),
        ("tela.mostrar", {"html": "<p>x</p>"}, True),
        ("files.move_to_trash", {"path": "x"}, False),
        ("script.rodar", {"linguagem": "python", "codigo": "print(1)"}, False),
    ],
)
def test_a_tabela_do_escopo(tool_id: str, args: dict[str, object], contido: bool) -> None:
    assert julgar(tool_id, args, CNN).contido is contido, julgar(tool_id, args, CNN).motivo


def test_fechar_aba_so_a_do_pedido_ou_a_do_site_citado() -> None:
    assert julgar("browser.fechar_aba", {"tab_id": 9}, CNN, abertas_pelo_pedido={9}).contido
    assert julgar(
        "browser.fechar_aba", {"tab_id": 3}, CNN, endereco_da_aba="https://www.cnn.com/x"
    ).contido
    dono = julgar("browser.fechar_aba", {"tab_id": 3}, CNN, endereco_da_aba="https://g1.com/x")
    assert not dono.contido and "não foi aberta por este pedido" in dono.motivo


def test_risco_que_o_pdp_confirma_nunca_e_contido_nem_citado() -> None:
    apagar = Objetivo.do_pedido("apaga o arquivo da cnn")
    assert not julgar("sites.open", {"url": "https://cnn.com"}, apagar, risco="egress").contido
    assert not julgar("window.close", {"app": "cnn"}, apagar, risco="apagar_permanente").contido


def test_sem_pedido_do_dono_nada_e_contido() -> None:
    assert not julgar("browser.navigate", {"url": "https://cnn.com"}, None).contido
