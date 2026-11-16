"""O alvo da ação conferido contra a página antes de agir (ADR-0071), com a forma REAL da resposta.

A resposta do `page.inspect` aqui tem exatamente os campos que `extensao/content.js`
(`dadosDoElemento`) devolve: `tag`, `texto`, `campo`, `sensivel`, `enviaFormulario`,
`acaoDoFormulario`, `metodoDoFormulario`, `formularioDeBusca`, `formularioSensivel`,
`noFormulario`, `editavel`, `campoDeBusca`, `papel`, `rotulo`, `destinoDoLink`, `centro`. Numa linha
de conversa do WhatsApp o `rotulo` (aria-label) costuma vir vazio e o nome do contato está no
`texto`: conferir só `rotulo`/`nome` recusaria todo clique com `esperado` na máquina do dono.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from jarvis.navegador.alvo import AlvoNaoConfere, confere, parecidos
from jarvis.navegador.cliente import ClienteDoNavegador
from jarvis.navegador.ferramentas import CorposDoNavegador
from jarvis.navegador.protocolo import PedidoDaPonte

ABA = 7


def dados_do_elemento(texto: str, *, rotulo: str = "", papel: str = "") -> dict[str, Any]:
    """Como `dadosDoElemento` do content.js devolve um elemento."""
    return {
        "tag": "div",
        "texto": texto,
        "campo": False,
        "sensivel": False,
        "enviaFormulario": False,
        "acaoDoFormulario": "",
        "metodoDoFormulario": "",
        "formularioDeBusca": False,
        "formularioSensivel": False,
        "noFormulario": False,
        "editavel": False,
        "campoDeBusca": False,
        "papel": papel,
        "rotulo": rotulo,
        "destinoDoLink": "",
        "centro": {"x": 100, "y": 200},
    }


class ExtensaoReal:
    """A extensão respondendo com os campos reais; o mapa e a inspeção concordam por `ref`."""

    def __init__(self, linhas: Mapping[str, dict[str, Any]]) -> None:
        self.linhas = dict(linhas)
        self.cliques: list[str] = []

    def chamar(self, pedido: PedidoDaPonte, navegador: str = "") -> dict[str, Any]:
        del navegador
        ok = {"id": pedido.id, "ok": True}
        aba = {"id": ABA, "janelaId": 1, "ativa": True, "url": "https://web.whatsapp.com/"}
        match pedido.method:
            case "tabs.current":
                return ok | {"result": {"aba": aba}}
            case "page.inspect":
                return ok | {"result": self.linhas[str(pedido.params["ref"])]}
            case "page.map":
                elementos = [
                    {"ref": ref, "papel": d["papel"], "rotulo": d["rotulo"], "texto": d["texto"]}
                    for ref, d in self.linhas.items()
                ]
                return ok | {"result": {"instantaneo": 1, "elementos": elementos}}
            case "page.click":
                self.cliques.append(str(pedido.params["ref"]))
                return ok | {"result": {"clicado": True}}
        raise AssertionError(f"método inesperado: {pedido.method}")


def _clicar(extensao: ExtensaoReal, args: Mapping[str, Any]) -> dict[str, Any]:
    corpos = CorposDoNavegador(ClienteDoNavegador(extensao))

    def exigir(_detalhe: str, _motivo: str, _causa: str) -> None:
        raise AssertionError("um clique numa conversa não pede o sim do dono")

    return corpos.executar(
        "browser.click",
        {"tab_id": ABA, **args},
        contaminado=False,
        liberados=frozenset(),
        exigir=exigir,
        cancelado=lambda: False,
    )


LINHAS = {
    "m1.0": dados_do_elemento("Mãe 10:32 ok filho", papel="listitem"),
    "m1.1": dados_do_elemento("Carla: falei com o Bruno ontem", papel="listitem"),
    "m1.2": dados_do_elemento("Bruno", rotulo="Bruno", papel="listitem"),
}


def test_o_nome_no_texto_confere_mesmo_com_o_rotulo_vazio() -> None:
    assert confere("Mãe", LINHAS["m1.0"])
    assert confere("mae", LINHAS["m1.0"])  # sem acento nem caixa


def test_o_nome_no_meio_do_texto_nao_confere() -> None:
    assert not confere("Bruno", LINHAS["m1.1"])


def test_o_clique_pelo_ref_com_o_esperado_certo_acontece() -> None:
    extensao = ExtensaoReal(LINHAS)
    feito = _clicar(extensao, {"ref": "m1.0", "esperado": "Mãe"})
    assert feito["clicado"] is True
    assert extensao.cliques == ["m1.0"]


def test_o_clique_pelo_ref_errado_nao_acontece_e_mostra_o_parecido() -> None:
    extensao = ExtensaoReal(LINHAS)
    with pytest.raises(AlvoNaoConfere) as erro:
        _clicar(extensao, {"ref": "m1.1", "esperado": "Bruno"})
    assert extensao.cliques == []
    mensagem = str(erro.value)
    assert "não aconteceu" in mensagem.lower()
    assert "«Bruno»" in mensagem  # o parecido que está na página


def test_os_parecidos_leem_o_texto_do_mapa() -> None:
    elementos = [{"rotulo": "", "texto": "Mãe 10:32 ok filho"}, {"rotulo": "", "texto": "Pai"}]
    assert parecidos("mae", elementos)[0].startswith("Mãe")
