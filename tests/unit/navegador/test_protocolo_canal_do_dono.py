"""ADR-0074, canal do dono: `social.lista` e `social.abrirLinha` no vocabulário da ponte — só no
WhatsApp, com índice e nome lidos da lista; nada de seletor nem nome solto para procurar."""

from __future__ import annotations

import pytest

from jarvis.navegador.protocolo import PedidoInvalido, prazo_do_metodo, validar_pedido


def _pedido(metodo: str, **params: object) -> dict[str, object]:
    return {"id": "c1", "method": metodo, "params": params}


def test_lista_e_abrir_linha_validos() -> None:
    assert validar_pedido(_pedido("social.lista", rede="whatsapp")).method == "social.lista"
    pedido = validar_pedido(_pedido("social.abrirLinha", rede="whatsapp", indice=3, nome="Você"))
    assert pedido.params == {"rede": "whatsapp", "indice": 3, "nome": "Você"}
    assert prazo_do_metodo("social.lista") == prazo_do_metodo("social.abrirLinha") < 10


@pytest.mark.parametrize(
    ("metodo", "params"),
    [
        ("social.lista", {"rede": "instagram"}),
        ("social.lista", {}),
        ("social.abrirLinha", {"rede": "whatsapp", "indice": -1, "nome": "Você"}),
        ("social.abrirLinha", {"rede": "whatsapp", "indice": 500, "nome": "Você"}),
        ("social.abrirLinha", {"rede": "whatsapp", "indice": 1, "nome": "  "}),
        ("social.abrirLinha", {"rede": "whatsapp", "indice": True, "nome": "Você"}),
        ("social.abrirLinha", {"rede": "whatsapp", "nome": "Você"}),
        ("social.abrirLinha", {"rede": "whatsapp", "indice": 1, "nome": "Você", "seletor": "x"}),
    ],
)
def test_recusa_o_que_nao_cabe(metodo: str, params: dict[str, object]) -> None:
    with pytest.raises(PedidoInvalido):
        validar_pedido(_pedido(metodo, **params))
