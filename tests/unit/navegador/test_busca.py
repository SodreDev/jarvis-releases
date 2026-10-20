"""A busca na web pelo navegador do dono (ADR-0033): aba de fundo, links para fora, reserva."""

from __future__ import annotations

from typing import Any

import pytest

from jarvis.executor.web import BuscaIndisponivel
from jarvis.navegador.busca import BUSCADORES, BuscaNoNavegador, resultados_da_pagina
from jarvis.navegador.cliente import ClienteDoNavegador, NavegadorIndisponivel
from jarvis.navegador.protocolo import PedidoDaPonte

BRAVE, DUCK = BUSCADORES

PAGINA_DO_BRAVE = {
    "links": [
        {"texto": "Brave Search", "href": "https://search.brave.com/"},  # o próprio buscador
        {"texto": "O Primo Rico - YouTube", "href": "https://www.youtube.com/@primorico"},
        {"texto": "O Primo Rico - YouTube", "href": "https://www.youtube.com/@primorico/"},
        {"texto": "ir", "href": "https://pt.wikipedia.org/wiki/Thiago_Nigro"},  # texto curto demais
        {"texto": "Thiago Nigro – Wikipédia", "href": "https://pt.wikipedia.org/wiki/Thiago_Nigro"},
        {"texto": "Privacidade", "href": "https://brave.com/privacy/"},
        {"texto": "javascript", "href": "javascript:void(0)"},
    ]
}


def test_da_pagina_de_resultados_saem_so_os_links_para_fora_sem_repetir() -> None:
    assert resultados_da_pagina(PAGINA_DO_BRAVE, BRAVE) == [
        {"titulo": "O Primo Rico - YouTube", "url": "https://www.youtube.com/@primorico"},
        {"titulo": "Thiago Nigro – Wikipédia", "url": "https://pt.wikipedia.org/wiki/Thiago_Nigro"},
    ]


def test_o_redirecionamento_do_duckduckgo_e_desfeito() -> None:
    pagina = {
        "links": [
            {
                "texto": "O Primo Rico",
                "href": "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.youtube.com%2F%40primorico&rut=x",
            },
            {"texto": "Configurações", "href": "https://duckduckgo.com/settings"},
        ]
    }
    assert resultados_da_pagina(pagina, DUCK) == [
        {"titulo": "O Primo Rico", "url": "https://www.youtube.com/@primorico"}
    ]


class ExtensaoFalsa:
    """O que a extensão responderia a `page.readUrl`, por buscador."""

    def __init__(self, paginas: dict[str, dict[str, Any] | str]) -> None:
        self.paginas = paginas
        self.urls: list[str] = []

    def chamar(self, pedido: PedidoDaPonte, navegador: str = "") -> dict[str, Any]:
        assert pedido.method == "page.readUrl", pedido.method
        url = str(pedido.params["url"])
        self.urls.append(url)
        for prefixo, resposta in self.paginas.items():
            if url.startswith(prefixo):
                if resposta == "fora":
                    raise NavegadorIndisponivel(
                        "nenhum navegador com a extensão do Jarvis está aberto"
                    )
                if isinstance(resposta, str):
                    erro = {"codigo": resposta, "mensagem": "falhou"}
                    return {"id": pedido.id, "ok": False, "error": erro}
                return {"id": pedido.id, "ok": True, "result": {"pagina": resposta}}
        raise AssertionError(url)


def test_o_primeiro_buscador_com_resultado_ganha_e_a_consulta_vai_codificada() -> None:
    extensao = ExtensaoFalsa({"https://search.brave.com/": PAGINA_DO_BRAVE})
    achado = BuscaNoNavegador(ClienteDoNavegador(extensao))("o primo rico")

    assert extensao.urls == ["https://search.brave.com/search?q=o+primo+rico&source=web"]
    assert achado["fonte"] == "Brave Search, pelo navegador do dono"
    assert achado["resultados"][0]["url"] == "https://www.youtube.com/@primorico"


def test_sem_resultado_ou_com_erro_no_brave_vale_o_duckduckgo() -> None:
    reserva = {
        "links": [{"texto": "Paris – Wikipédia", "href": "https://pt.wikipedia.org/wiki/Paris"}]
    }
    vazio = ExtensaoFalsa(
        {"https://search.brave.com/": {"links": []}, "https://html.duck": reserva}
    )
    com_erro = ExtensaoFalsa(
        {"https://search.brave.com/": "pagina_lenta", "https://html.duck": reserva}
    )

    for extensao in (vazio, com_erro):
        achado = BuscaNoNavegador(ClienteDoNavegador(extensao))("paris")
        assert achado["fonte"].startswith("DuckDuckGo") and len(extensao.urls) == 2


def test_sem_navegador_aberto_nenhum_buscador_e_tentado_de_novo() -> None:
    extensao = ExtensaoFalsa({"https://search.brave.com/": "fora"})
    with pytest.raises(BuscaIndisponivel, match="nenhum navegador"):
        BuscaNoNavegador(ClienteDoNavegador(extensao))("paris")
    assert len(extensao.urls) == 1


def test_nenhum_buscador_com_resultado_diz_o_que_cada_um_deu() -> None:
    extensao = ExtensaoFalsa({"https://search.brave.com/": {"links": []}, "https://html.duck": "x"})
    with pytest.raises(BuscaIndisponivel) as falha:
        BuscaNoNavegador(ClienteDoNavegador(extensao))("paris")
    assert "Brave Search: sem resultados" in str(falha.value) and "DuckDuckGo: x" in str(
        falha.value
    )
