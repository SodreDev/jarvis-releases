"""A ORIENTAÇÃO de uma tarefa de navegador (ADR-0066; revista pela ADR-0070: não é roteiro).

Antes, o código escrevia um roteiro de passos numerados (abra isto, digite aquilo, clique ali)
e o subagente o seguia: era automação. Agora vai ao subagente só o que ele precisa para decidir —
como trabalhar numa página (ler antes de agir, escolher o alvo pelo que está nela, reler para
conferir, depurar no erro) e, num envio, os FATOS que o código resolveu (a rede e o endereço, o
contato das memórias, o que o dono quer dizer, se ditou literal) e as travas de segurança (conferir
o contato no cabeçalho antes de digitar, conferir o envio depois). O caminho é ele quem escolhe.

- **Envio direto** («abre o contato da minha mãe e diz eu te amo»): a rede, o contato e a
  mensagem saem da fala; o contato é conferido no cabeçalho da conversa antes de digitar — se o
  nome não bate, procura o certo. É pedido do dono: executa sem perguntar (as travas do envio
  autônomo da ADR-0060 — lista permitida, modo ausente, tetos — não se aplicam aqui).
- **Navegação em geral**: aba atual, site citado, ler, agir, ler de novo para conferir.

Desde a ADR-0071 (2026-11-16) o que a regex tira da fala (o contato, a mensagem) é só DICA,
rotulada como palpite: quem decide os parâmetros é o Jarvis, no plano que vira o objetivo da
tarefa; as travas do envio continuam valendo sempre.

Nada aqui executa: é texto para as notas da rodada. Só a fala do dono entra (nunca o texto de uma
página). A mensagem é **redigida** pelo Jarvis, no tom do dono com aquela pessoa (ADR-0069 §3: ele
é assistente, não repetidor); só vai palavra por palavra quando o dono ditou o texto — entre aspas,
ou com «exatamente», «literalmente», «palavra por palavra».
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
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
TENTATIVAS_POR_PASSO: Final = 3
"""Quantas vezes o roteiro manda reler e tentar o mesmo passo antes de dizer que falhou."""

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
_ENTRE_ASPAS: Final = re.compile(r"[«\"“”]([^«»\"“”]{1,1000})[»\"“”]")
_LITERAL: Final = re.compile(
    r"\b(?:exatamente|literalmente|palavra por palavra|ao p[eé] da letra|com essas palavras|"
    r"sem mudar nada)\b",
    re.IGNORECASE,
)
_SOBRA_DO_LITERAL: Final = re.compile(
    r"(?:^|(?<=[\s,]))(?:exatamente|literalmente|palavra por palavra|ao p[eé] da letra|"
    r"com essas palavras|sem mudar nada)(?:\s+(?:isso|assim))?\s*:?",
    re.IGNORECASE,
)
_POSSESSIVO: Final = re.compile(r"^(?:minha|meu|o|a)\s+", re.IGNORECASE)
_PALAVRAS_DE_ENVIO: Final = re.compile(rf"\b(?:{_VERBO}|{_GERUNDIO})\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Contato:
    """Uma memória fixa útil ao envio: o contato (nome e o que o dono escreveu sobre ele, «minha
    mãe») ou uma instrução de tom (`tipo="instrucao"`: como o dono escreve)."""

    nome: str
    texto: str = ""
    tipo: str = "contato"


@dataclass(frozen=True, slots=True)
class PedidoDeEnvio:
    rede: str
    contato_dito: str
    contato: str
    """O nome a procurar: o das memórias quando «minha mãe» bate com uma, senão o dito."""
    mensagem: str
    """O que o dono quer dizer. Redigido pelo Jarvis, salvo quando `literal` (ADR-0069 §3)."""
    literal: bool = False
    """O dono ditou o texto: entre aspas, ou «diga exatamente», «literalmente», «palavra por
    palavra». Só aí a mensagem vai como ele disse."""
    nota: str = ""
    """O que o dono escreveu sobre esse contato nas memórias fixas (o tom com essa pessoa)."""


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
    literal = bool(_LITERAL.search(limpa))
    aspas = _ENTRE_ASPAS.search(limpa)
    if aspas is not None:
        # O texto ditado entre aspas é a mensagem, palavra por palavra (ADR-0069 §3).
        mensagem, literal = aspas.group(1), True
    elif literal:
        mensagem = " ".join(_SOBRA_DO_LITERAL.sub(" ", mensagem).split())
    mensagem = mensagem.strip(" \"'«»“”:,")
    if not mensagem or not dito:
        return None
    lista = [c for c in contatos if c.tipo == "contato"]
    contato = _resolver(dito, lista)
    nota = next((c.texto for c in lista if c.nome == contato), "")
    return PedidoDeEnvio(
        rede=rede,
        contato_dito=dito,
        contato=contato,
        mensagem=mensagem,
        literal=literal,
        nota=nota,
    )


def _ferramentas(ids: Iterable[str]) -> list[str]:
    return sorted(i for i in ids if i.startswith("browser."))


def roteiro(fala: str, ids: Iterable[str], contatos: Sequence[Contato] = ()) -> str:
    """A orientação para as notas da tarefa, ou vazio quando não há ferramenta de navegador."""
    disponiveis = _ferramentas(ids)
    if not disponiveis:
        return ""
    envio = pedido_de_envio(fala, contatos)
    if envio is not None:
        tom = tuple(c.texto or c.nome for c in contatos if c.tipo == "instrucao")
        return f"{ORIENTACAO}\n{_fatos_do_envio(envio, tom)}"
    return ORIENTACAO


def _fatos_do_envio(envio: PedidoDeEnvio, tom: Sequence[str] = ()) -> str:
    """A DICA do envio (ADR-0071): o que uma regra de texto acha na fala — palpite rotulado, que
    nunca vence o objetivo que o Jarvis formulou — e as travas do envio, que valem sempre."""
    site, url = REDES[envio.rede]
    outro_nome = (
        f" (o dono disse «{envio.contato_dito}»; nas memórias fixas é «{envio.contato}»)"
        if _normal(envio.contato) != _normal(envio.contato_dito)
        else ""
    )
    return (
        f"{CABECALHO_DA_DICA} parece um envio direto pelo {site} ({url}) para «{envio.contato}»"
        f"{outro_nome}. {_mensagem(envio, tom)} Se for mesmo um envio, é pedido do dono: execute "
        "sem perguntar (lista permitida e modo ausente são só da resposta autônoma). TRAVAS DO "
        "ENVIO (valem sempre): antes de digitar, o cabeçalho da conversa aberta TEM de mostrar o "
        "contato do objetivo — nunca digite na conversa errada; depois de enviar, leia a conversa "
        "e só diga que mandou se a última mensagem for a sua."
    )


CABECALHO_DA_DICA: Final = (
    "DICA DO CÓDIGO (palpite de uma regra de texto sobre a fala do dono, pode estar errado; vale "
    "o objetivo que o Jarvis formulou e, se os dois divergem, siga o objetivo):"
)


def _mensagem(envio: PedidoDeEnvio, tom: Sequence[str]) -> str:
    """O texto ditado vai como está; o pedido («manda pra X que …») é redigido pelo Jarvis, no tom
    do dono com essa pessoa (ADR-0069 §3) — dito como palpite (ADR-0071)."""
    if envio.literal:
        return f"Se for isso, a mensagem vai EXATAMENTE como o dono ditou: «{envio.mensagem}»."
    sobre = (
        f" O que ele anotou sobre «{envio.contato}»: «{_curto(envio.nota)}»." if envio.nota else ""
    )
    jeito = (
        " O jeito dele escrever, das memórias: "
        + "; ".join(f"«{_curto(t)}»" for t in tom[:TONS_NO_ROTEIRO])
        + "."
        if tom
        else ""
    )
    return (
        f"O que ele parece querer dizer: «{envio.mensagem}». A mensagem, REDIJA: você é o "
        "assistente pessoal dele, não um repetidor — em primeira pessoa, em nome dele, no tom "
        "dele com essa pessoa, curta, sem citar o Jarvis, sem inventar fato, horário ou promessa "
        f"e sem copiar a fala dele palavra por palavra.{sobre}{jeito}"
    )


def _curto(texto: str, limite: int = 200) -> str:
    texto = " ".join(texto.split())
    return texto if len(texto) <= limite else texto[:limite] + "…"


def copia_da_mensagem(
    tool_id: str, args: Mapping[str, object], envio: PedidoDeEnvio | None
) -> bool:
    """O `browser.type` de um envio que não é literal leva a fala do dono copiada (a mensagem que
    ele pediu, sem redigir)? É o que a tarefa e o turno cobram uma vez (ADR-0069 §3)."""
    if envio is None or envio.literal or tool_id != "browser.type":
        return False
    digitado = _sem_pontuacao(str(args.get("texto", "")))
    return bool(digitado) and digitado == _sem_pontuacao(envio.mensagem)


def _sem_pontuacao(texto: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", _normal(texto)).split())


NOTA_DE_REDIGIR: Final = (
    "REDIJA A MENSAGEM: o texto que você ia digitar é a fala do dono copiada. Ele pediu para você "
    "dizer isso à pessoa, não para repetir as palavras dele: escreva a mensagem com as suas "
    "palavras, como ele escreveria para essa pessoa, e digite essa."
)
TONS_NO_ROTEIRO: Final = 3
"""Quantas instruções de tom das memórias fixas vão no passo da mensagem."""


ORIENTACAO: Final = (
    "COMO TRABALHAR NO NAVEGADOR (orientação, não roteiro: o caminho é você quem escolhe): veja "
    "as abas antes de abrir outra; LEIA A PÁGINA antes de agir (browser.inspecionar dá o mapa dos "
    "elementos, com papel, rótulo, estado e `ref`) e escolha o alvo pelo que está nela, nunca por "
    "palpite; aja pelo `ref`, um passo por vez, e releia depois de uma ação que muda a página; se "
    "um passo falhar, releia e depure (outro rótulo, outro `ref`, rolar, fechar o aviso por cima) "
    f"antes de tentar de novo — até {TENTATIVAS_POR_PASSO} vezes por passo; só diga que ficou "
    "feito quando uma leitura confirmar."
)
