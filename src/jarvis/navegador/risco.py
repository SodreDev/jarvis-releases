"""O que torna uma ação no navegador **perigosa** — decidido pelo código, nunca pela página.

O tier do manifesto é estático (`browser.click` é moderado); o risco de um clique depende do que
está sob ele. Antes do efeito o Jarvis inspeciona o alvo (`page.inspect`) e passa o que viu por
estas regras. O resultado é uma de três coisas: **segue** (moderado: roda, e o passo não é
narrado — o aviso fica na auditoria, ADR-0031), **confirma**
(perigoso: só o "sim" do dono na janela, uma vez por ação) ou **recusa** (senha, código e cartão
são do dono — handoff, nunca preenchidos pelo Jarvis).

O que a página diz de si mesma (texto de botão, `action` do formulário) é **dado de terceiro**: aqui
ele só pode **apertar** a regra, nunca afrouxá-la. A única coisa que solta uma ação é o "sim" do
dono, e esse não passa por este módulo.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from jarvis.politica.abertura import dominio, dominio_liberado, nome_de_app
from jarvis.politica.objetivo import Objetivo, dados_do_dono

ROTULO_DAS_CATEGORIAS: Final[dict[str, str]] = {
    "senha": "gerenciador de senhas",
    "banco": "banco ou corretora",
    "pagamento": "pagamento",
    "mensageiro": "mensageiro ou rede social",
    "email": "e-mail",
}
DOMINIOS_SENSIVEIS: Final[dict[str, tuple[str, ...]]] = {
    "senha": (
        "1password.com",
        "bitwarden.com",
        "lastpass.com",
        "dashlane.com",
        "keepersecurity.com",
        "nordpass.com",
        "pass.proton.me",
    ),
    "banco": (
        "nubank.com.br",
        "itau.com.br",
        "bradesco.com.br",
        "santander.com.br",
        "bb.com.br",
        "caixa.gov.br",
        "inter.co",
        "c6bank.com.br",
        "sicredi.com.br",
        "sicoob.com.br",
        "btgpactual.com",
        "interactivebrokers.com",
        "binance.com",
        "coinbase.com",
    ),
    "pagamento": (
        "paypal.com",
        "mercadopago.com.br",
        "pagseguro.uol.com.br",
        "picpay.com",
        "stripe.com",
        "pay.google.com",
        "wise.com",
    ),
    "mensageiro": (
        "web.whatsapp.com",
        "whatsapp.com",
        "instagram.com",
        "web.telegram.org",
        "discord.com",
        "messenger.com",
        "app.slack.com",
        "teams.microsoft.com",
    ),
    "email": (
        "mail.google.com",
        "outlook.live.com",
        "outlook.office.com",
        "outlook.office365.com",
        "mail.yahoo.com",
        "mail.proton.me",
    ),
}
"""Lista versionada do repositório (ADR-0027, regra 2); a do dono entra por cima, depois."""
SUBDOMINIOS_DE_PAGAMENTO: Final = frozenset(
    {"checkout", "pagamento", "pagamentos", "payment", "pay"}
)
CATEGORIAS_QUE_NAO_SE_LE_SEM_PERGUNTAR: Final = frozenset({"senha", "banco", "pagamento"})
CATEGORIAS_DE_CADA_ACAO: Final = frozenset({"senha", "banco", "pagamento"})
"""Onde todo clique e todo texto pedem o sim: credencial e dinheiro (dono, 2026-10-20: "só o muito
crítico"). Mensageiro e e-mail saíram daqui: abrir conversa e escrever não perguntam — enviar,
responder, publicar e postar continuam perguntando pelas palavras de risco e pelo envio."""
CATEGORIAS_EM_QUE_O_ICONE_ENVIA: Final = frozenset({"mensageiro", "email"})
"""Onde um clique sem nome acessível pede o sim: o botão de enviar costuma ser só um ícone, e sem
nome nenhuma palavra de risco o reconhece. Clicar num campo de texto (o compositor) não envia."""

PALAVRAS_DE_RISCO: Final[dict[str, tuple[str, ...]]] = {
    "envia uma mensagem ou publicação": (
        "enviar",
        "send",
        "publicar",
        "publish",
        "postar",
        "post",
        "responder",
        "reply",
        "tweetar",
        "encaminhar",
        "forward",
    ),
    "paga ou assina": (
        "pagar",
        "pay",
        "comprar",
        "buy",
        "purchase",
        "checkout",
        "finalizar compra",
        "finalizar pedido",
        "confirmar pedido",
        "place order",
        "assinar",
        "subscribe",
        "doar",
        "donate",
        "transferir",
        "transfer",
    ),
    "apaga algo": ("excluir", "deletar", "delete", "apagar"),
    "dá acesso a uma conta": (
        "entrar",
        "login",
        "log in",
        "sign in",
        "autorizar",
        "authorize",
        "conectar conta",
    ),
}
_PADROES_DE_RISCO: Final = tuple(
    (motivo, re.compile(r"\b(?:" + "|".join(re.escape(nome_de_app(p)) for p in palavras) + r")\b"))
    for motivo, palavras in PALAVRAS_DE_RISCO.items()
)
_ROTULO_SECRETO: Final = re.compile(
    r"\b(?:senha|password|passcode|cvv|cvc|cartao|card number|otp|token|captcha|2fa|"
    r"codigo de (?:verificacao|seguranca|acesso)|verification code|security code|pin)\b"
)


@dataclass(frozen=True, slots=True)
class Avaliacao:
    """`recusa` vence `confirmar`; os dois vazios = segue como moderado."""

    recusa: str = ""
    confirmar: str = ""
    causa: str = ""
    """O código do motivo (`jarvis.trilha.CAUSAS`): é o que a trilha grava — a frase cita o rótulo
    que a página dá ao elemento."""


SEGUE: Final = Avaliacao()


def categoria(url: str) -> str:
    """A categoria sensível do site, ou `""`."""
    host = dominio(url)
    if not host:
        return ""
    for nome, dominios in DOMINIOS_SENSIVEIS.items():
        if dominio_liberado(host, frozenset(dominios)):
            return nome
    if SUBDOMINIOS_DE_PAGAMENTO & set(host.split(".")[:-2]):
        return "pagamento"
    return ""


def _palavra_de_risco(*textos: str) -> str:
    dobrado = " ".join(nome_de_app(t) for t in textos if t)
    for motivo, padrao in _PADROES_DE_RISCO:
        if padrao.search(dobrado):
            return motivo
    return ""


def parece_cartao(texto: str) -> bool:
    digitos = re.sub(r"[ -]", "", texto.strip())
    if not (digitos.isdigit() and 13 <= len(digitos) <= 19):
        return False
    soma = 0
    for posicao, digito in enumerate(reversed(digitos)):
        n = int(digito)
        if posicao % 2:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        soma += n
    return soma % 10 == 0


def avaliar_leitura(url: str) -> Avaliacao:
    """Ler é livre; ler banco, senha ou pagamento leva a tela do dono ao modelo: só com o sim."""
    nome = categoria(url)
    if nome in CATEGORIAS_QUE_NAO_SE_LE_SEM_PERGUNTAR:
        return Avaliacao(
            confirmar=(
                f"{dominio(url)} é {ROTULO_DAS_CATEGORIAS[nome]}: ler a página manda o que "
                "está na tela para o modelo"
            ),
            causa="categoria_do_site",
        )
    return SEGUE


def _dado_para_fora(destino: str, objetivo: Objetivo | None) -> Avaliacao | None:
    levados = objetivo.leva_dado_do_dono(destino) if objetivo is not None else []
    if not levados:
        return None
    return Avaliacao(
        confirmar=(
            f"o endereço leva {', '.join(levados)} para {dominio(destino)}, que o dono não citou"
        ),
        causa="dado_do_dono_para_fora",
    )


def avaliar_navegacao(
    destino: str,
    *,
    contaminado: bool,
    liberados: frozenset[str],
    objetivo: Objetivo | None = None,
) -> Avaliacao:
    host = dominio(destino)
    para_fora = _dado_para_fora(destino, objetivo)
    if para_fora is not None:
        return para_fora
    if objetivo is not None and objetivo.dentro(destino):
        return SEGUE  # citado pelo dono ou alcançado pelo caminho do objetivo
    if contaminado and not dominio_liberado(host, liberados):
        return Avaliacao(
            confirmar=(
                f"o turno leu conteúdo de terceiros e {host} não é um site que o dono liberou: "
                "o endereço carrega o que estiver nele"
            ),
            causa="destino_externo",
        )
    return SEGUE


def _envio_de_formulario(dados: Mapping[str, Any]) -> str:
    if not dados.get("enviaFormulario"):
        return ""
    if dados.get("formularioSensivel"):
        return "envia um formulário com senha ou cartão (quem preenche é o dono)"
    if dados.get("metodoDoFormulario") == "get" and dados.get("formularioDeBusca"):
        return ""  # busca por GET não envia nada de que se precise voltar atrás
    return "envia um formulário"


def _sem_nome(dados: Mapping[str, Any]) -> bool:
    """O elemento não tem nome acessível (aria-label, alt, texto…) na inspeção da extensão. O texto
    que o modelo deu ao alvo não conta: quem nomeia o elemento é a página."""
    return not (str(dados.get("rotulo") or "").strip() or str(dados.get("texto") or "").strip())


def _causa_do_envio(dados: Mapping[str, Any]) -> str:
    return "formulario_sensivel" if dados.get("formularioSensivel") else "envia_formulario"


def avaliar_clique(
    url: str,
    dados: Mapping[str, Any],
    alvo: str,
    *,
    contaminado: bool,
    liberados: frozenset[str],
    objetivo: Objetivo | None = None,
) -> Avaliacao:
    nome = categoria(url)
    if nome in CATEGORIAS_DE_CADA_ACAO:
        return Avaliacao(
            confirmar=f"{dominio(url)} é {ROTULO_DAS_CATEGORIAS[nome]}: cada clique pede o seu sim",
            causa="categoria_do_site",
        )
    envio = _envio_de_formulario(dados)
    if envio:
        return Avaliacao(confirmar=f"clicar em «{alvo}» {envio}", causa=_causa_do_envio(dados))
    motivo = _palavra_de_risco(alvo, str(dados.get("texto", "")))
    if motivo:
        return Avaliacao(confirmar=f"clicar em «{alvo}» {motivo}", causa="palavra_de_risco")
    if nome in CATEGORIAS_EM_QUE_O_ICONE_ENVIA and _sem_nome(dados) and not dados.get("editavel"):
        # Nem o objetivo solta: o domínio citado é justamente onde a mensagem seria enviada.
        return Avaliacao(
            confirmar=(
                f"{dominio(url)} é {ROTULO_DAS_CATEGORIAS[nome]} e o elemento não tem nome: "
                "pode ser o botão de enviar"
            ),
            causa="elemento_sem_nome",
        )
    return _para_onde_leva(
        url,
        str(dados.get("destinoDoLink", "")),
        contaminado=contaminado,
        liberados=liberados,
        objetivo=objetivo,
    )


def _para_onde_leva(
    url: str,
    destino: str,
    *,
    contaminado: bool,
    liberados: frozenset[str],
    objetivo: Objetivo | None,
) -> Avaliacao:
    """O destino de um link ou de uma busca por GET: dado do dono para fora pergunta sempre;
    domínio de fora do objetivo pergunta depois de o turno ler conteúdo de terceiros."""
    if not destino:
        return SEGUE
    para_fora = _dado_para_fora(destino, objetivo)
    if para_fora is not None:
        return para_fora
    if contaminado and not (objetivo is not None and objetivo.dentro(destino)):
        host = dominio(destino)
        if host != dominio(url) and not dominio_liberado(host, liberados):
            return Avaliacao(
                confirmar=(
                    f"o turno leu conteúdo de terceiros e o link leva a {host}, que o dono não "
                    "liberou"
                ),
                causa="destino_externo",
            )
    return SEGUE


def avaliar_acionamento(
    url: str,
    dados: Mapping[str, Any],
    alvo: str,
    acao: str,
    *,
    tecla: str = "",
    contaminado: bool,
    liberados: frozenset[str],
    objetivo: Objetivo | None = None,
) -> Avaliacao:
    """Acionar a ação do elemento equivale a clicá-lo (dono, 2026-10-18; ADR-0032): o risco é o do
    clique, e o «enviar» e o Enter num campo contam como envio do formulário em que ele está.
    Focar, passar o mouse, escolher opção e as outras teclas não enviam nada."""
    nome = categoria(url)
    if nome in CATEGORIAS_DE_CADA_ACAO:
        return Avaliacao(
            confirmar=f"{dominio(url)} é {ROTULO_DAS_CATEGORIAS[nome]}: cada ação pede o seu sim",
            causa="categoria_do_site",
        )
    enter = acao == "tecla" and tecla == "Enter"
    if acao == "clicar" or (enter and not dados.get("editavel")):
        # Enter num botão ou link é o clique dele.
        return avaliar_clique(
            url, dados, alvo, contaminado=contaminado, liberados=liberados, objetivo=objetivo
        )
    if not (acao == "enviar" or enter):
        return SEGUE
    if not dados.get("noFormulario"):
        if enter and dados.get("campoDeBusca"):
            return SEGUE  # o código da página busca
        # Fora de formulário o Enter vai para o código da página: na caixa de um chat, envia.
        return Avaliacao(
            confirmar=f"apertar Enter em «{alvo}» pode enviar o que está escrito",
            causa="enter_envia",
        )
    envio = _envio_de_formulario({**dados, "enviaFormulario": True})
    if envio:
        verbo = "enviar" if acao == "enviar" else "apertar Enter em"
        return Avaliacao(confirmar=f"{verbo} «{alvo}» {envio}", causa=_causa_do_envio(dados))
    # Busca por GET: o formulário só navega; o destino passa pelas regras do link.
    return _para_onde_leva(
        url,
        str(dados.get("acaoDoFormulario", "")),
        contaminado=contaminado,
        liberados=liberados,
        objetivo=objetivo,
    )


def avaliar_digitacao(
    url: str,
    dados: Mapping[str, Any],
    alvo: str,
    texto: str,
    *,
    contaminado: bool,
    objetivo: Objetivo | None = None,
) -> Avaliacao:
    if dados.get("sensivel") or _ROTULO_SECRETO.search(nome_de_app(alvo)) or parece_cartao(texto):
        return Avaliacao(
            recusa=(
                "senha, código de verificação e cartão o dono digita; o Jarvis não preenche "
                "nem recebe esse dado — peça a ele para digitar e siga depois"
            ),
            causa="segredo_do_dono",
        )
    nome = categoria(url)
    if nome in CATEGORIAS_DE_CADA_ACAO:
        return Avaliacao(
            confirmar=f"{dominio(url)} é {ROTULO_DAS_CATEGORIAS[nome]}: cada texto pede o seu sim",
            causa="categoria_do_site",
        )
    if objetivo is not None:
        levados = [] if objetivo.citado(url) else dados_do_dono(texto)
        if levados:
            return Avaliacao(
                confirmar=(
                    f"o texto leva {', '.join(levados)} para {dominio(url)}, que o dono não citou"
                ),
                causa="dado_do_dono_para_fora",
            )
        if objetivo.dentro(url):
            return SEGUE  # a página é do objetivo: escrever nela é o que o dono pediu
    if contaminado:
        return Avaliacao(
            confirmar=(
                "o turno leu conteúdo de terceiros: digitar numa página pode estar sendo "
                "pedido por esse conteúdo"
            ),
            causa="turno_contaminado",
        )
    return SEGUE
