"""Os PASSOS concretos de uma tarefa de navegador, montados pelo próprio Jarvis (ADR-0066; dono,
2026-11-14: «subagentes recebem a TAREFA concreta definida pelo Jarvis, não só um objetivo»).

A tarefa recebia só o pedido e o critério de pronto, e o motor improvisava o caminho — às vezes
parando em «quer que eu mande?» ou dizendo que abriu o contato sem ter aberto. Aqui o **código**
lê a fala do dono e escreve o roteiro: o que abrir, o que ler, o que digitar, como conferir e
quando está pronto, com as ferramentas `browser.*` que o catálogo de agora tem.

- **Envio direto** («abre o contato da minha mãe e diz eu te amo»): a rede, o contato e a
  mensagem saem da fala; o contato é conferido no cabeçalho da conversa antes de digitar — se o
  nome não bate, procura o certo. É pedido do dono: executa sem perguntar (as travas do envio
  autônomo da ADR-0060 — lista permitida, modo ausente, tetos — não se aplicam aqui).
- **Navegação em geral**: aba atual, site citado, ler, agir, ler de novo para conferir.

Nada aqui executa: é texto para as notas da rodada. Só a fala do dono entra (nunca o texto de uma
página), e a mensagem vai entre «» exatamente como ele disse.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

REDES: Final[dict[str, tuple[str, str]]] = {
    "whatsapp": ("WhatsApp Web", "https://web.whatsapp.com/"),
    "zap": ("WhatsApp Web", "https://web.whatsapp.com/"),
    "instagram": ("Instagram", "https://www.instagram.com/direct/inbox/"),
    "insta": ("Instagram", "https://www.instagram.com/direct/inbox/"),
    "telegram": ("Telegram Web", "https://web.telegram.org/"),
}
REDE_PADRAO: Final = "whatsapp"
"""Sem rede dita, o mensageiro do dono é o WhatsApp (o que o monitor da ADR-0060 acompanha)."""

_VERBO: Final = (
    r"(?:diz|diga|dizer|fala|fale|falar|manda|mande|mandar|envia|envie|enviar|escreve|escreva|"
    r"escrever|responde|responda|responder)"
)
_GERUNDIO: Final = r"(?:dizendo|falando|escrevendo|mandando|respondendo)"
_QUEM: Final = r"(?:(?:minha|meu|o|a)\s+)?[\wÀ-ÿ]+"
_REDE_NO_FIM: Final = re.compile(
    r"\s+(?:no|na|pelo|pela)\s+(?:whatsapp|zap|instagram|insta|telegram)\b", re.IGNORECASE
)
_CONTATO: Final = re.compile(
    r"\b(?:contato|conversa|chat)\s+(?:d[aoe]s?\s+)?(?P<contato>[^,;!?]+?)"
    r"(?=\s+e\s|\s*[,;!?]|$)",
    re.IGNORECASE,
)
_PARA: Final = re.compile(rf"\b(?:pra|para|pro|ao|à)\s+(?P<contato>{_QUEM})", re.IGNORECASE)
_MENSAGEM_DEPOIS_DO_GERUNDIO: Final = re.compile(
    rf"\b{_GERUNDIO}\s+(?:que\s+)?(?P<mensagem>.+)$", re.IGNORECASE
)
_MENSAGEM_DEPOIS_DO_VERBO: Final = re.compile(
    rf"\b{_VERBO}\b(?:\s+(?:uma\s+)?mensagem)?(?:\s+(?:pra|para|pro|ao|à)\s+{_QUEM})?"
    r"(?:\s+(?:que|assim)\b:?)?\s+(?P<mensagem>.+)$",
    re.IGNORECASE,
)
_POSSESSIVO: Final = re.compile(r"^(?:minha|meu|o|a)\s+", re.IGNORECASE)
_PALAVRAS_DE_ENVIO: Final = re.compile(rf"\b(?:{_VERBO}|{_GERUNDIO})\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Contato:
    """Um contato das memórias fixas: o nome e o que o dono escreveu sobre ele («minha mãe»)."""

    nome: str
    texto: str = ""


@dataclass(frozen=True, slots=True)
class PedidoDeEnvio:
    rede: str
    contato_dito: str
    contato: str
    """O nome a procurar: o das memórias quando «minha mãe» bate com uma, senão o dito."""
    mensagem: str


def _normal(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto.casefold())
    return " ".join("".join(c for c in base if not unicodedata.combining(c)).split())


def _rede(fala: str) -> str:
    normal = _normal(fala)
    for chave in REDES:
        if re.search(rf"\b{chave}\b", normal):
            return chave
    return REDE_PADRAO


def _resolver(dito: str, contatos: Iterable[Contato]) -> str:
    """«minha mãe» → o contato cujas notas dizem «mãe»; «Ana» → o contato Ana. Sem par, o dito."""
    alvo = _normal(_POSSESSIVO.sub("", dito.strip()))
    if not alvo:
        return dito.strip()
    lista = list(contatos)
    for contato in lista:
        if _normal(contato.nome) == alvo:
            return contato.nome
    for contato in lista:
        if re.search(rf"\b{re.escape(alvo)}\b", _normal(f"{contato.nome} {contato.texto}")):
            return contato.nome
    # Sem par nas memórias: o dito sem o possessivo («minha mãe» → «mãe», como o contato costuma
    # estar salvo no telefone).
    return _POSSESSIVO.sub("", dito.strip()) or dito.strip()


def pedido_de_envio(fala: str, contatos: Iterable[Contato] = ()) -> PedidoDeEnvio | None:
    """A fala do dono pede para mandar uma mensagem a alguém? Rede, contato e mensagem; `None`
    quando falta um dos dois (contato ou mensagem): aí o roteiro é o geral."""
    limpa = " ".join(fala.strip().split()).rstrip(".!")
    if not _PALAVRAS_DE_ENVIO.search(limpa):
        return None
    rede = _rede(limpa)
    sem_rede = _REDE_NO_FIM.sub("", limpa)
    achado = _CONTATO.search(sem_rede) or _PARA.search(sem_rede)
    mensagem_achada = _MENSAGEM_DEPOIS_DO_GERUNDIO.search(sem_rede) or (
        _MENSAGEM_DEPOIS_DO_VERBO.search(sem_rede)
    )
    if achado is None or mensagem_achada is None:
        return None
    dito = achado.group("contato").strip()
    mensagem = mensagem_achada.group("mensagem")
    # «diz eu te amo pra minha mãe»: o destinatário no fim sai da mensagem.
    if achado.start() >= mensagem_achada.start("mensagem"):
        mensagem = mensagem[: achado.start() - mensagem_achada.start("mensagem")]
    mensagem = mensagem.strip(" \"'«»“”:,")
    if not mensagem or not dito:
        return None
    return PedidoDeEnvio(
        rede=rede, contato_dito=dito, contato=_resolver(dito, contatos), mensagem=mensagem
    )


def _ferramentas(ids: Iterable[str]) -> list[str]:
    return sorted(i for i in ids if i.startswith("browser."))


def roteiro(fala: str, ids: Iterable[str], contatos: Sequence[Contato] = ()) -> str:
    """O roteiro para as notas da tarefa, ou vazio quando não há ferramenta de navegador."""
    disponiveis = _ferramentas(ids)
    if not disponiveis:
        return ""
    cabeca = f"Ferramentas do navegador disponíveis: {', '.join(disponiveis)}."
    envio = pedido_de_envio(fala, contatos)
    if envio is not None:
        return f"{cabeca}\n{_roteiro_do_envio(envio)}"
    return f"{cabeca}\n{_roteiro_geral()}"


def _roteiro_do_envio(envio: PedidoDeEnvio) -> str:
    site, url = REDES[envio.rede]
    outro_nome = (
        f" (o dono disse «{envio.contato_dito}»; nas memórias é «{envio.contato}»)"
        if _normal(envio.contato) != _normal(envio.contato_dito)
        else ""
    )
    return (
        f"ROTEIRO (montado pelo Jarvis; é pedido DIRETO do dono: execute sem perguntar e sem "
        f"exigir lista permitida nem modo ausente — isso é só da resposta autônoma):\n"
        f"1. browser.tabs: ache a aba do {site}. Sem ela, browser.navigate {url} (e espere "
        f"carregar com browser.read).\n"
        f"2. browser.read: confirme que a página está logada e ache a busca de conversas.\n"
        f"3. browser.type na busca: «{envio.contato}»{outro_nome}. browser.read: escolha o "
        f"resultado cujo nome bate com «{envio.contato}».\n"
        f"4. browser.click no resultado. browser.read no cabeçalho da conversa: o nome TEM de "
        f"bater com «{envio.contato}». Se não bater, volte ao passo 3 e procure o contato certo; "
        f"nunca digite na conversa errada.\n"
        f"5. browser.type na caixa de mensagem: «{envio.mensagem}» (exatamente isso), e envie com "
        f"browser.acionar (Enter ou o botão de enviar).\n"
        f"6. browser.read: confira que a última mensagem enviada na conversa de «{envio.contato}» "
        f"é «{envio.mensagem}».\n"
        f"Pronto quando: o passo 6 confirmou. Só então diga ao dono que mandou; se algo falhou, "
        f"diga o que falhou."
    )


def _roteiro_geral() -> str:
    return (
        "ROTEIRO (montado pelo Jarvis):\n"
        "1. browser.tabs: veja a aba atual (URL e título) antes de abrir outra.\n"
        "2. Se o site do pedido não está aberto, browser.navigate nele; senão, use a aba que já "
        "está.\n"
        "3. browser.read: leia a página antes de agir (o que clicar, onde digitar).\n"
        "4. Aja com browser.click / browser.type / browser.acionar, um passo por vez.\n"
        "5. browser.read de novo: confira que o efeito aconteceu na página.\n"
        "Pronto quando: a leitura do passo 5 mostra o que o dono pediu."
    )


__all__ = ["REDES", "Contato", "PedidoDeEnvio", "pedido_de_envio", "roteiro"]
