"""O quadro do Native Messaging e o vocabulário fechado: bytes em memória, nada de navegador."""

from __future__ import annotations

import io
import struct
from typing import Any

import pytest

from jarvis.navegador.protocolo import (
    PedidoInvalido,
    validar_evento,
    validar_pedido,
    validar_resposta,
)
from jarvis.navegador.quadro import QuadroInvalido, codificar, ler_quadro


def _quadro(corpo: bytes) -> io.BytesIO:
    return io.BytesIO(struct.pack("=I", len(corpo)) + corpo)


def test_o_quadro_vai_e_volta_e_o_fim_limpo_e_none() -> None:
    fluxo = io.BytesIO(codificar({"id": "a", "texto": "ação"}, 1000))
    assert ler_quadro(fluxo, 1000) == {"id": "a", "texto": "ação"}
    assert ler_quadro(fluxo, 1000) is None


@pytest.mark.parametrize(
    "bytes_",
    [
        b"\x05\x00",  # cabeçalho cortado
        struct.pack("=I", 50) + b"{}",  # corpo cortado
        struct.pack("=I", 5000) + b"x" * 5000,  # maior que o limite
        struct.pack("=I", 3) + b"[1]",  # JSON que não é objeto
        struct.pack("=I", 2) + b"\xff\xfe",  # não é UTF-8
        struct.pack("=I", 3) + b"{x}",  # não é JSON
    ],
)
def test_quadro_truncado_grande_ou_torto_e_erro(bytes_: bytes) -> None:
    with pytest.raises(QuadroInvalido):
        ler_quadro(io.BytesIO(bytes_), 1000)


def test_mensagem_grande_demais_nao_sai() -> None:
    with pytest.raises(QuadroInvalido):
        codificar({"x": "a" * 2000}, 1000)


def _pedido(metodo: str, **params: Any) -> dict[str, Any]:
    return {"id": "j1-1", "method": metodo, "params": params}


def test_pedidos_do_vocabulario_passam() -> None:
    assert validar_pedido(_pedido("tabs.list")).method == "tabs.list"
    assert validar_pedido(_pedido("page.click", tabId=7, alvo="Próxima")).params["tabId"] == 7
    pedido = validar_pedido(_pedido("page.type", alvo="Busca", texto="oi", limpar=True))
    assert pedido.params["limpar"] is True
    assert validar_pedido(_pedido("tabs.navigate", url="https://exemplo.org/a?b=1")).id == "j1-1"
    # Aba nova só quando o dono pede (2026-10-20): o padrão continua sendo navegar na atual.
    assert validar_pedido(_pedido("tabs.open", url="https://exemplo.org")).method == "tabs.open"
    # O mapa da página e a ação pela referência dele (ADR-0032).
    assert validar_pedido(_pedido("page.map", tabId=7)).method == "page.map"
    assert validar_pedido(_pedido("page.capture", tabId=7)).method == "page.capture"
    # A aba de fundo nasce na janela do dono; a janela própria só no modo da automação social
    # (ADR-0036, emenda de 2026-10-21).
    fundo = validar_pedido(_pedido("tabs.open", url="https://x.example", fundo=True))
    assert fundo.params["fundo"] is True
    social = validar_pedido(_pedido("tabs.open", url="https://x.example", modo="automacao_social"))
    assert social.params["modo"] == "automacao_social"
    busca_social = _pedido("page.readUrl", url="https://x.example", modo="automacao_social")
    assert validar_pedido(busca_social).params["modo"] == "automacao_social"
    assert validar_pedido(_pedido("windows.focused")).method == "windows.focused"
    lida = validar_pedido(_pedido("page.readUrl", url="https://search.brave.com/search?q=x"))
    assert lida.params == {"url": "https://search.brave.com/search?q=x"}
    assert validar_pedido(_pedido("page.click", ref="k3f2.12")).params == {"ref": "k3f2.12"}
    assert validar_pedido(_pedido("page.type", ref="k3f2.1", texto="o primo rico")).params["ref"]
    acao = validar_pedido(_pedido("page.act", ref="k3f2.1", acao="tecla", tecla="Enter"))
    assert acao.params["tecla"] == "Enter"
    escolha = _pedido("page.act", alvo="Parcelas", acao="selecionar", valor="3x")
    assert validar_pedido(escolha).params["valor"] == "3x"


@pytest.mark.parametrize(
    "bruto",
    [
        _pedido("tabs.open"),  # aba nova sem endereço
        _pedido("tabs.open", url="javascript:alert(1)"),
        _pedido("tabs.open", url="https://exemplo.org", reutilizar=True),  # fora do contrato
        _pedido("page.eval", codigo="1+1", mundo="outro"),  # mundo fora da lista (ADR-0051)
        _pedido("page.eval"),  # avaliar o quê? falta o código
        _pedido("page.eval", codigo="x" * 20_001),  # código acima do teto
        _pedido("page.gesture", gesto="voar"),  # gesto fora da lista
        _pedido("page.gesture"),  # falta o gesto
        _pedido("page.click", selector="#enviar", alvo="x"),  # seletor CSS não existe
        _pedido("page.click", seletor="#enviar"),  # nem em português
        _pedido("page.click", alvo="Próxima", ref="k3f2.1"),  # texto ou referência, um só
        _pedido("page.click", ref="#enviar"),  # referência fora do formato do mapa
        _pedido("page.click", ref="k3f2.1; document.cookie"),
        _pedido("page.act", ref="k3f2.1"),  # falta a ação
        _pedido("page.act", ref="k3f2.1", acao="executar"),  # ação fora da lista
        _pedido("page.act", ref="k3f2.1", acao="tecla", tecla="F12"),
        _pedido("page.act", ref="k3f2.1", acao="tecla"),  # tecla sem dizer qual
        _pedido("page.act", ref="k3f2.1", acao="selecionar"),  # escolher sem a opção
        _pedido("page.act", ref="k3f2.1", acao="selecionar", valor="v" * 201),
        _pedido("page.map", alvo="x"),  # o mapa é da página inteira
        _pedido("page.capture", formato="png"),  # a captura não escolhe nada
        _pedido("page.readUrl"),  # ler o quê?
        _pedido("tabs.open", url="https://x.example", janela="jarvis"),  # saiu: é o modo agora
        _pedido("tabs.open", url="https://x.example", modo="outro"),
        _pedido("tabs.open", url="https://x.example", fundo="sim"),  # booleano
        _pedido("page.readUrl", url="https://x.example", modo="jarvis"),
        _pedido("windows.focused", janelaId=3),  # só pergunta, não escolhe
        _pedido("page.readUrl", url="file:///etc/passwd"),
        _pedido("page.readUrl", url="https://x.example", tabId=7),  # a aba é sempre nova, de fundo
        _pedido("page.click"),  # falta o alvo
        _pedido("page.click", alvo="   "),
        _pedido("page.click", alvo="a" * 501),
        _pedido("page.read", tabId=True),  # booleano não é inteiro
        _pedido("page.read", tabId=-1),
        _pedido("page.scroll", pixels=2001),
        _pedido("page.type", alvo="x", texto="y" * 10_001),
        _pedido("tabs.navigate", url="javascript:alert(1)"),
        _pedido("tabs.navigate", url="file:///etc/passwd"),
        _pedido("tabs.navigate", url="https://u:p@exemplo.org/"),
        _pedido("tabs.navigate", url="https://exemplo.org/ a"),
        {"id": "com espaço", "method": "tabs.list", "params": {}},
        {"id": "a", "method": "tabs.list", "params": []},
        ["não é objeto"],
    ],
)
def test_pedido_fora_do_vocabulario_e_recusado(bruto: object) -> None:
    with pytest.raises(PedidoInvalido):
        validar_pedido(bruto)


def test_resposta_so_tem_o_formato_do_contrato() -> None:
    assert validar_resposta({"id": "a", "ok": True, "result": {"x": 1}, "extra": 1}) == {
        "id": "a",
        "ok": True,
        "result": {"x": 1},
    }
    erro = validar_resposta({"id": "a", "ok": False, "error": {"codigo": "c" * 99, "mensagem": 3}})
    assert len(erro["error"]["codigo"]) == 60
    for ruim in ({"id": "a"}, {"id": "a", "ok": True}, {"id": "a", "ok": False}, "texto"):
        with pytest.raises(PedidoInvalido):
            validar_resposta(ruim)


# --- o controle (ADR-0027 regra 4) ---------------------------------------------------------------
def test_a_concessao_vai_nos_pedidos_que_mexem_na_aba_e_so_no_formato() -> None:
    assert validar_pedido(_pedido("page.read", tabId=7, controle="a1b2c3d4e5f60708")).params == {
        "tabId": 7,
        "controle": "a1b2c3d4e5f60708",
    }
    assert validar_pedido(_pedido("controle.soltar", controle="a1b2c3d4")).method == (
        "controle.soltar"
    )
    assert validar_pedido(_pedido("controle.parar")).method == "controle.parar"
    assert validar_pedido(_pedido("eventos.assinar")).method == "eventos.assinar"
    for ruim in ("curta", "COM-MAIUSCULA-E-TRACO", "a" * 33, "../../etc"):
        with pytest.raises(PedidoInvalido, match="concessão"):
            validar_pedido(_pedido("page.read", tabId=7, controle=ruim))
    with pytest.raises(PedidoInvalido, match="fora do contrato"):
        validar_pedido(_pedido("tabs.list", controle="a1b2c3d4"))  # listar não é controlar
    with pytest.raises(PedidoInvalido, match="falta"):
        validar_pedido(_pedido("controle.soltar"))


def test_o_evento_da_extensao_e_so_o_parar_do_dono() -> None:
    bom = {"evento": "parar", "concessoes": ["a1b2c3d4e5f60708"], "origem": "barra"}
    assert validar_evento(bom) == bom
    assert validar_evento({**bom, "extra": 1}) == bom, "o que sobra não passa adiante"
    ruins: tuple[object, ...] = (
        {**bom, "evento": "clicar"},
        {**bom, "origem": "pagina"},
        {**bom, "concessoes": "a1b2c3d4"},
        {**bom, "concessoes": ["x"]},
        {**bom, "concessoes": ["a1b2c3d4"] * 33},
        [],
    )
    for ruim in ruins:
        with pytest.raises(PedidoInvalido):
            validar_evento(ruim)
