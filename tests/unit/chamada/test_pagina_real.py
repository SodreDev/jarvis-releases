"""A porta real da aba do WhatsApp (ADR-0074, fatia A) contra uma ponte FALSA que valida cada
pedido pelo protocolo da ponte 7 — nenhum navegador, conta ou CDP de verdade."""

from __future__ import annotations

import random
from typing import Any

import pytest

from jarvis.chamada.pagina_real import ListaMudou, PaginaPelaPonte
from jarvis.navegador.protocolo import validar_pedido


class PonteFalsa:
    def __init__(self) -> None:
        self.pedidos: list[tuple[str, dict[str, Any]]] = []
        self.linhas = [
            {"indice": 0, "nome": "Carlos", "trecho": "oi", "grupo": False},
            {"indice": 1, "nome": "Família", "trecho": "foto", "grupo": True},
            {"indice": 2, "nome": "Você", "trecho": "nota", "grupo": False},
            {"indice": "x", "nome": "quebrado"},
        ]
        self.cabecalhos = ["Você"]
        self.mudar_lista = False

    def pedir(self, metodo: str, navegador: str, **params: Any) -> dict[str, Any]:
        validar_pedido({"id": "p1", "method": metodo, "params": params})  # o contrato de verdade
        assert navegador == "chromium"
        self.pedidos.append((metodo, params))
        if metodo == "social.lista":
            return {"conversas": self.linhas, "total": len(self.linhas)}
        if metodo == "social.abrirLinha":
            return {"mudou": self.mudar_lista}
        if metodo == "social.cabecalho":
            nome = self.cabecalhos.pop(0) if len(self.cabecalhos) > 1 else self.cabecalhos[0]
            return {"nome": nome, "telefone": "", "grupo": False, "ambiguo": False}
        return {}


def _pagina(ponte: PonteFalsa) -> PaginaPelaPonte:
    return PaginaPelaPonte(ponte, familia=lambda: "chromium", aleatorio=random.Random(7))


def test_lista_vira_linhas_com_id_e_abrir_usa_indice_e_nome_lidos() -> None:
    ponte = PonteFalsa()
    pagina = _pagina(ponte)
    linhas = pagina.conversas()
    assert [(x.id, x.nome, x.grupo) for x in linhas] == [
        ("c0", "Carlos", False),
        ("c1", "Família", True),
        ("c2", "Você", False),
    ]
    pagina.abrir("c2")
    assert ponte.pedidos[-1] == (
        "social.abrirLinha",
        {"rede": "whatsapp", "indice": 2, "nome": "Você"},
    )
    with pytest.raises(LookupError):
        pagina.abrir("c9")


def test_lista_que_reordenou_nao_abre() -> None:
    ponte = PonteFalsa()
    pagina = _pagina(ponte)
    pagina.conversas()
    ponte.mudar_lista = True
    with pytest.raises(ListaMudou):
        pagina.abrir("c2")


def test_enviar_digita_no_ritmo_reconfere_o_cabecalho_e_solta() -> None:
    ponte = PonteFalsa()
    pagina = _pagina(ponte)
    pagina.conversas()
    pagina.abrir("c2")
    pagina.cabecalho()
    texto = "Jarvis: pediram na chamada mandar a planilha. Código K7QX4M, vale 10 min. " * 3
    pagina.enviar(texto.strip())
    metodos = [m for m, _ in ponte.pedidos]
    digitado = "".join(p["texto"] for m, p in ponte.pedidos if m == "social.digitar")
    assert digitado == texto.strip()
    assert metodos[-3:] == ["social.cabecalho", "social.enviar", "social.soltar"]


def test_chat_que_mudou_durante_a_digitacao_nao_envia_e_solta() -> None:
    ponte = PonteFalsa()
    ponte.cabecalhos = ["Você", "Carlos"]
    pagina = _pagina(ponte)
    pagina.conversas()
    pagina.abrir("c2")
    pagina.cabecalho()
    with pytest.raises(LookupError, match="mudou"):
        pagina.enviar("oi")
    metodos = [m for m, _ in ponte.pedidos]
    assert "social.enviar" not in metodos and metodos[-1] == "social.soltar"


def test_enviar_sem_ler_o_cabecalho_depois_de_abrir_recusa() -> None:
    ponte = PonteFalsa()
    pagina = _pagina(ponte)
    pagina.conversas()
    pagina.abrir("c2")
    with pytest.raises(LookupError):
        pagina.enviar("oi")
    assert not any(m == "social.digitar" for m, _ in ponte.pedidos)
