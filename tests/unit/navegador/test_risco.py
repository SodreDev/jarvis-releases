"""As regras de risco do navegador: o que a página diz de si só aperta, nunca afrouxa."""

from __future__ import annotations

import pytest

from jarvis.navegador import risco
from jarvis.politica.objetivo import Objetivo


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
    assert risco.parece_cartao("4111 1111 1111 1111")
    assert risco.parece_cartao("4111-1111-1111-1111")
    assert not risco.parece_cartao("4111 1111 1111 1112")
    assert not risco.parece_cartao("123456")
    assert not risco.parece_cartao("meu cartão")


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


SO_ICONE = {"tag": "button", "papel": "button", "rotulo": "", "texto": "", "editavel": False}
COMPOSITOR_SEM_NOME = SO_ICONE | {"tag": "div", "papel": "textbox", "editavel": True}
DISCORD = "https://discord.com/channels/1/2"
GMAIL = "https://mail.google.com/mail/u/0/"


@pytest.mark.parametrize(
    ("url", "dados", "pergunta"),
    [
        # o achado da auditoria: o botão de enviar só com ícone não casa palavra de risco nenhuma
        (DISCORD, SO_ICONE, True),
        (GMAIL, SO_ICONE, True),
        (DISCORD, SO_ICONE | {"rotulo": None, "texto": "  "}, True),
        # com nome, segue: abrir a conversa não pergunta
        (DISCORD, SO_ICONE | {"rotulo": "Pedro", "texto": "Pedro"}, False),
        (GMAIL, SO_ICONE | {"rotulo": "Caixa de entrada"}, False),
        # clicar no compositor sem nome só põe o foco nele
        (DISCORD, COMPOSITOR_SEM_NOME, False),
        # fora de mensageiro e e-mail o ícone sem nome segue como antes
        ("https://exemplo.org/", SO_ICONE, False),
    ],
)
def test_em_mensageiro_e_email_o_clique_sem_nome_pede_o_sim_mesmo_dentro_do_objetivo(
    url: str, dados: dict[str, object], pergunta: bool
) -> None:
    objetivo = Objetivo.do_pedido("mande um oi para o Pedro no discord e no google mail")
    assert objetivo.dentro(url) or not risco.categoria(url)  # o dono citou o site
    clique = risco.avaliar_clique(
        url, dados, "o elemento", contaminado=True, liberados=frozenset(), objetivo=objetivo
    )
    enter = risco.avaliar_acionamento(
        url, dados, "o elemento", "tecla", tecla="Enter", contaminado=True,
        liberados=frozenset(), objetivo=objetivo,
    )  # fmt: skip
    assert bool(clique.confirmar) is pergunta, clique
    if not dados["editavel"]:  # Enter num botão é o clique dele
        assert enter == clique


# --- acionar a ação do elemento (ADR-0032): equivale a clicar ------------------------------------
CAMPO_DE_BUSCA_GET = {
    "editavel": True,
    "campo": True,
    "noFormulario": True,
    "metodoDoFormulario": "get",
    "formularioDeBusca": True,
    "acaoDoFormulario": "https://www.youtube.com/results",
    "campoDeBusca": True,
}
CAMPO_DE_COMENTARIO_POST = {
    "editavel": True,
    "campo": True,
    "noFormulario": True,
    "metodoDoFormulario": "post",
    "acaoDoFormulario": "https://forum.example/enviar",
}
CAIXA_DE_CHAT = {"editavel": True, "campo": False, "noFormulario": False}
BUSCA_SOLTA = {"editavel": True, "campo": True, "noFormulario": False, "campoDeBusca": True}
BOTAO_ENVIAR = {"editavel": False, "texto": "Enviar", "noFormulario": False}


@pytest.mark.parametrize(
    ("url", "dados", "alvo", "acao", "tecla", "pergunta"),
    [
        # o caso do dono: Enter no campo de busca do YouTube busca, sem pergunta
        ("https://www.youtube.com/", CAMPO_DE_BUSCA_GET, "Pesquisar", "tecla", "Enter", False),
        ("https://www.youtube.com/", CAMPO_DE_BUSCA_GET, "Pesquisar", "enviar", "", False),
        # formulário que envia (POST): Enter e «enviar» perguntam, como o clique no botão
        ("https://forum.example/", CAMPO_DE_COMENTARIO_POST, "Comentário", "tecla", "Enter", True),
        ("https://forum.example/", CAMPO_DE_COMENTARIO_POST, "Comentário", "enviar", "", True),
        # Enter na caixa de um chat (fora de formulário) envia a mensagem: pergunta
        ("https://web.whatsapp.com/", CAIXA_DE_CHAT, "Mensagem", "tecla", "Enter", True),
        ("https://exemplo.org/", CAIXA_DE_CHAT, "Mensagem", "tecla", "Enter", True),
        # Enter num campo de busca solto: o código da página busca
        ("https://exemplo.org/", BUSCA_SOLTA, "Buscar", "tecla", "Enter", False),
        # Enter num botão é o clique dele: a palavra de risco vale
        ("https://exemplo.org/", BOTAO_ENVIAR, "Enviar", "tecla", "Enter", True),
        ("https://exemplo.org/", BOTAO_ENVIAR, "Enviar", "clicar", "", True),
        # focar, passar o mouse, outras teclas e escolher opção não enviam nada
        ("https://exemplo.org/", BOTAO_ENVIAR, "Enviar", "passar_o_mouse", "", False),
        ("https://exemplo.org/", CAIXA_DE_CHAT, "Mensagem", "focar", "", False),
        ("https://exemplo.org/", CAIXA_DE_CHAT, "Mensagem", "tecla", "Escape", False),
        ("https://exemplo.org/", {"editavel": False}, "Parcelas", "selecionar", "", False),
        # banco, pagamento e senha: cada ação pede o sim
        ("https://www.nubank.com.br/", BOTAO_ENVIAR, "Menu", "passar_o_mouse", "", True),
    ],
)
def test_acionar_tem_o_risco_do_clique_e_enter_conta_como_envio(
    url: str, dados: dict[str, object], alvo: str, acao: str, tecla: str, pergunta: bool
) -> None:
    avaliacao = risco.avaliar_acionamento(
        url, dados, alvo, acao, tecla=tecla, contaminado=False, liberados=frozenset()
    )
    assert bool(avaliacao.confirmar) is pergunta, avaliacao


def test_busca_por_get_de_outro_dominio_num_turno_contaminado_pergunta() -> None:
    """A busca só navega, e o destino passa pelas regras do link (injeção não escolhe o site)."""
    dados = CAMPO_DE_BUSCA_GET | {"acaoDoFormulario": "https://mal.example/busca"}
    avaliacao = risco.avaliar_acionamento(
        "https://exemplo.org/", dados, "Busca", "tecla", tecla="Enter", contaminado=True,
        liberados=frozenset(),
    )  # fmt: skip
    assert "mal.example" in avaliacao.confirmar
