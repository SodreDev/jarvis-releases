"""Com o navegador fechado, o Jarvis o abre — ele pode e deve (dono, 2026-10-25; ADR-0046).

O relato: «abre um vídeo no YouTube» com o navegador fechado e o Jarvis mandava o dono abrir. A
navegação com endereço já caía no `sites.open` (o navegador do dono abre na página); o passo sem
endereço (as abas, a página) agora abre o navegador (`browser.launch`), espera a extensão
conectar e tenta de novo — pelo mesmo PDP. Extensão e navegador falsos, nada do desktop do dono.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from jarvis.executor.ferramentas import ExecutorDeFerramentas
from jarvis.executor.navegadores import AbridorDeNavegador
from jarvis.navegador.cliente import ClienteDoNavegador, NavegadorIndisponivel
from jarvis.navegador.ferramentas import CorposDoNavegador
from jarvis.navegador.protocolo import PedidoDaPonte
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado


class NavegadorQueAbre:
    """A extensão que só responde depois de o navegador ser lançado (pelo `lancar` falso)."""

    def __init__(self) -> None:
        self.aberto = False
        self.lancados: list[tuple[str, ...]] = []

    def lancar(self, argv: tuple[str, ...], ambiente: object = None) -> int:
        del ambiente
        self.lancados.append(tuple(argv))
        self.aberto = True
        return 4321

    def chamar(self, pedido: PedidoDaPonte, navegador: str = "") -> dict[str, Any]:
        del navegador
        if not self.aberto:
            raise NavegadorIndisponivel("nenhum navegador com a extensão do Jarvis está aberto")
        aba = {
            "id": 3,
            "janelaId": 1,
            "ativa": True,
            "url": "https://g1.globo.com/",
            "titulo": "g1",
        }
        if pedido.method == "tabs.list":
            return {"id": pedido.id, "ok": True, "result": {"abas": [aba]}}
        if pedido.method == "windows.focused":
            return {"id": pedido.id, "ok": True, "result": {"janelaId": 1}}
        return {"id": pedido.id, "ok": False, "error": {"code": "x", "message": pedido.method}}


@pytest.fixture
def navegador() -> NavegadorQueAbre:
    return NavegadorQueAbre()


@pytest.fixture
def executor(tmp_path: Path, navegador: NavegadorQueAbre) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    lar.mkdir()
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
            navegadores=frozenset({"brave"}),
            navegador_principal="brave",
        )
        ex = ExecutorDeFerramentas(
            pdp=pdp,
            lar=lar,
            navegador=CorposDoNavegador(ClienteDoNavegador(navegador)),
            navegadores=AbridorDeNavegador(
                navegadores={"brave": "/usr/bin/true"}, principal="brave", lancar=navegador.lancar
            ),
        )
        ex.preparar()
        yield ex


def _abas(contexto: Contexto) -> list[PedidoDeTool | str]:
    if not any(m.papel == "ferramenta" for m in contexto.mensagens):
        return [PedidoDeTool("browser.tabs", {})]
    return ["Uma aba aberta, no g1."]


def test_o_passo_sem_endereco_abre_o_navegador_espera_e_tenta_de_novo(
    executor: ExecutorDeFerramentas, navegador: NavegadorQueAbre
) -> None:
    publicados: list[dict[str, Any]] = []
    resposta = Cerebro(motor=MotorRoteirizado(resposta=_abas), ferramentas=executor).responder(
        "o que eu tenho aberto no navegador agora?", epoch=0, publicar=publicados.append
    )

    assert [(r.tool_id, r.status) for r in resposta.ferramentas] == [
        ("browser.tabs", "erro"),
        ("browser.launch", "ok"),
        ("browser.tabs", "ok"),
    ]
    assert navegador.lancados == [("/usr/bin/true",)], "o navegador do dono foi aberto, uma vez"
    falado = " ".join(str(p["text"]) for p in publicados if p["text"])
    assert falado == "Uma aba aberta, no g1."
    assert "abra" not in falado.casefold(), "nunca manda o dono abrir o navegador"


def test_sem_navegador_configurado_o_erro_volta_ao_motor_como_antes(
    executor: ExecutorDeFerramentas, navegador: NavegadorQueAbre
) -> None:
    executor.navegadores = None  # nenhum navegador configurado: não há o que abrir
    resposta = Cerebro(motor=MotorRoteirizado(resposta=_abas), ferramentas=executor).responder(
        "o que eu tenho aberto no navegador agora?", epoch=0, publicar=lambda _p: None
    )
    assert [(r.tool_id, r.status) for r in resposta.ferramentas] == [("browser.tabs", "erro")]
    assert navegador.lancados == []
