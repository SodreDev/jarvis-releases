"""O vocabulário fechado entre o Jarvis e a extensão (extensao/background.js).

Só estes métodos existem, cada um com os parâmetros que aceita. Não há `eval`, CDP nem
seletor CSS: o alvo de uma ação é o **texto ou rótulo visível** do elemento ou a **referência**
(`ref`) que o mapa da própria página devolveu (`page.map`, ADR-0032), e o que se faz com ele é
uma ação de uma lista fechada (`page.act`); `page.capture` traz a tela da aba com o mapa do mesmo
instante; `page.readUrl` lê um endereço numa aba de fundo, que fecha no fim (a busca na web,
ADR-0033). O host valida de novo o que o cliente já validou — o socket é uma fronteira, e a
extensão não confia em ninguém.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final
from urllib.parse import urlsplit

NOME_DO_HOST: Final = "br.com.granafacil.jarvis"
ID_CHROMIUM: Final = "eainnehpangdlhmjenljnbfkjjeckoli"
ID_FIREFOX: Final = "jarvis-browser@granafacil.local"
ORIGEM_CHROMIUM: Final = f"chrome-extension://{ID_CHROMIUM}/"

LIMITE_DO_PEDIDO: Final = 1_000_000
"""O navegador recusa mensagem do host para a extensão acima de 1 MB."""
LIMITE_DA_RESPOSTA: Final = 8 * 1024 * 1024
LIMITE_DA_URL: Final = 2_048
LIMITE_DO_ALVO: Final = 500
LIMITE_DO_TEXTO: Final = 10_000
LIMITE_DO_DESLOCAMENTO: Final = 2_000
PADRAO_DO_ID: Final = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
PADRAO_DA_REF: Final = re.compile(r"[a-z0-9]{1,16}\.[0-9]{1,4}")
"""`<instantâneo>.<n>`: o instantâneo leva a marca da página que o mapeou (`content.js`)."""
ACOES: Final = frozenset({"clicar", "focar", "passar_o_mouse", "tecla", "enviar", "selecionar"})
TECLAS: Final = frozenset({"Enter", "Escape", "Tab", "ArrowDown", "ArrowUp"})
LIMITE_DO_VALOR: Final = 200

METODOS: Final[dict[str, dict[str, type]]] = {
    # método → parâmetro → tipo (`int` nunca aceita booleano)
    "tabs.list": {},
    "tabs.current": {"tabId": int},
    "tabs.navigate": {"tabId": int, "url": str},
    "tabs.open": {"url": str},
    "page.read": {"tabId": int},
    "page.map": {"tabId": int},
    "page.capture": {"tabId": int},
    "page.readUrl": {"url": str},
    "page.inspect": {"tabId": int, "alvo": str, "ref": str},
    "page.click": {"tabId": int, "alvo": str, "ref": str},
    "page.type": {"tabId": int, "alvo": str, "ref": str, "texto": str, "limpar": bool},
    "page.act": {"tabId": int, "alvo": str, "ref": str, "acao": str, "tecla": str, "valor": str},
    "page.scroll": {"tabId": int, "pixels": int},
}
OBRIGATORIOS: Final[dict[str, frozenset[str]]] = {
    "tabs.navigate": frozenset({"url"}),
    "tabs.open": frozenset({"url"}),
    "page.readUrl": frozenset({"url"}),
    "page.type": frozenset({"texto"}),
    "page.act": frozenset({"acao"}),
}
COM_ALVO: Final = frozenset({"page.inspect", "page.click", "page.type", "page.act"})
"""Métodos que agem num elemento: exatamente um de `alvo` (texto visível) ou `ref` (do mapa)."""


class PedidoInvalido(ValueError):
    """O pedido não cabe no vocabulário. A mensagem diz o campo."""


@dataclass(frozen=True, slots=True)
class PedidoDaPonte:
    id: str
    method: str
    params: dict[str, Any]

    def como_objeto(self) -> dict[str, Any]:
        return {"id": self.id, "method": self.method, "params": self.params}


def _url_http(valor: str) -> None:
    if len(valor) > LIMITE_DA_URL or any(c in valor for c in "\r\n\t\x00 "):
        raise PedidoInvalido("url longa demais ou com espaço/controle")
    partes = urlsplit(valor)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise PedidoInvalido("a navegação é só para http ou https")
    if partes.username or partes.password:
        raise PedidoInvalido("url com credencial embutida é recusada")


def _tamanho(nome: str, valor: str, maximo: int) -> None:
    if len(valor) > maximo:
        raise PedidoInvalido(f"{nome} passa de {maximo} caracteres")


def validar_pedido(bruto: object) -> PedidoDaPonte:
    if not isinstance(bruto, dict):
        raise PedidoInvalido("o pedido tem de ser um objeto")
    identificador, metodo, params = bruto.get("id"), bruto.get("method"), bruto.get("params", {})
    if not isinstance(identificador, str) or not PADRAO_DO_ID.fullmatch(identificador):
        raise PedidoInvalido("id ausente ou fora de [A-Za-z0-9_.:-]{1,80}")
    if not isinstance(metodo, str) or metodo not in METODOS:
        raise PedidoInvalido("método fora do vocabulário do navegador")
    if not isinstance(params, dict):
        raise PedidoInvalido("params tem de ser um objeto")
    aceitos = METODOS[metodo]
    for nome, valor in params.items():
        tipo = aceitos.get(nome)
        if tipo is None:
            raise PedidoInvalido(f"{metodo}: parâmetro fora do contrato: {nome}")
        if not isinstance(valor, tipo) or (tipo is int and isinstance(valor, bool)):
            raise PedidoInvalido(f"{metodo}: {nome} com tipo errado")
    faltando = OBRIGATORIOS.get(metodo, frozenset()) - set(params)
    if faltando:
        raise PedidoInvalido(f"{metodo}: falta {sorted(faltando)}")
    if "tabId" in params and params["tabId"] < 0:
        raise PedidoInvalido("tabId negativo")
    if "url" in params:
        _url_http(params["url"])
    if metodo in COM_ALVO and ("alvo" in params) == ("ref" in params):
        raise PedidoInvalido(f"{metodo}: diga o alvo pelo texto (alvo) ou pela referência (ref)")
    if "alvo" in params:
        if not params["alvo"].strip():
            raise PedidoInvalido("alvo vazio")
        _tamanho("alvo", params["alvo"], LIMITE_DO_ALVO)
    if "ref" in params and not PADRAO_DA_REF.fullmatch(params["ref"]):
        raise PedidoInvalido("ref fora do formato do mapa da página")
    if "acao" in params and params["acao"] not in ACOES:
        raise PedidoInvalido(f"ação fora da lista: {sorted(ACOES)}")
    if params.get("acao") == "tecla" and params.get("tecla") not in TECLAS:
        raise PedidoInvalido(f"tecla fora da lista: {sorted(TECLAS)}")
    if params.get("acao") == "selecionar" and not params.get("valor"):
        raise PedidoInvalido("selecionar pede o valor (o texto da opção)")
    if "valor" in params:
        _tamanho("valor", params["valor"], LIMITE_DO_VALOR)
    if "texto" in params:
        _tamanho("texto", params["texto"], LIMITE_DO_TEXTO)
    if "pixels" in params and abs(params["pixels"]) > LIMITE_DO_DESLOCAMENTO:
        raise PedidoInvalido(f"pixels passa de {LIMITE_DO_DESLOCAMENTO}")
    return PedidoDaPonte(identificador, metodo, dict(params))


def validar_resposta(bruta: object) -> dict[str, Any]:
    """`{id, ok, result}` ou `{id, ok: false, error: {codigo, mensagem}}` — nada além disso."""
    if not isinstance(bruta, dict):
        raise PedidoInvalido("a resposta tem de ser um objeto")
    identificador = bruta.get("id")
    if identificador is not None and not (
        isinstance(identificador, str) and PADRAO_DO_ID.fullmatch(identificador)
    ):
        raise PedidoInvalido("id da resposta inválido")
    ok = bruta.get("ok")
    if not isinstance(ok, bool):
        raise PedidoInvalido("ok ausente")
    if ok:
        resultado = bruta.get("result")
        if not isinstance(resultado, dict):
            raise PedidoInvalido("result ausente")
        return {"id": identificador, "ok": True, "result": resultado}
    erro = bruta.get("error")
    if not isinstance(erro, dict):
        raise PedidoInvalido("error ausente")
    return {
        "id": identificador,
        "ok": False,
        "error": {
            "codigo": str(erro.get("codigo", "falha"))[:60],
            "mensagem": str(erro.get("mensagem", ""))[:300],
        },
    }
