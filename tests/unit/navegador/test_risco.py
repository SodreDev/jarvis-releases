"""As regras de risco do navegador: o que a página diz de si só aperta, nunca afrouxa."""

from __future__ import annotations

import pytest

from jarvis.navegador import risco


@pytest.mark.parametrize(
    ("url", "esperada"),
    [
        ("https://web.whatsapp.com/", "mensageiro"),
        ("https://www.instagram.com/direct/", "mensageiro"),
        ("https://app.nubank.com.br/", "banco"),  # subdomínio de domínio listado é o mesmo
        ("https://www.nubank.com.br/", "banco"),
        ("https://vault.bitwarden.com/", "senha"),
        ("https://checkout.loja.example/", "pagamento"),
        ("https://mail.google.com/", "email"),
        ("https://exemplo.org/", ""),
        ("https://nubank.com.br.mal.example/", ""),  # sufixo enganoso não casa
    ],
)
def test_categoria_do_site(url: str, esperada: str) -> None:
    assert risco.categoria(url) == esperada


def test_cartao_so_com_digito_verificador_valido() -> None:
    assert risco._parece_cartao("4111 1111 1111 1111")
    assert risco._parece_cartao("4111-1111-1111-1111")
    assert not risco._parece_cartao("4111 1111 1111 1112")
    assert not risco._parece_cartao("123456")
    assert not risco._parece_cartao("meu cartão")


def test_a_pagina_nao_afrouxa_o_que_o_codigo_apertou() -> None:
    # um botão que se diz "seguro" continua sendo envio de formulário POST
    dados = {"enviaFormulario": True, "metodoDoFormulario": "post", "texto": "apenas ver, seguro"}
    avaliacao = risco.avaliar_clique(
        "https://exemplo.org/", dados, "ver", contaminado=False, liberados=frozenset()
    )
    assert avaliacao.confirmar


def test_palavra_de_risco_ignora_acento_e_caixa() -> None:
    avaliacao = risco.avaliar_clique(
        "https://exemplo.org/", {}, "ENVIAR", contaminado=False, liberados=frozenset()
    )
    assert "mensagem" in avaliacao.confirmar
    sem_risco = risco.avaliar_clique(
        "https://exemplo.org/", {}, "Reenviar? não", contaminado=False, liberados=frozenset()
    )
    assert sem_risco == risco.SEGUE  # «reenviar» não é a palavra inteira
