"""O que já foi dito não se diz de novo: a entrega silenciosa (dono, 2026-10-25).

O dono ouvia o Jarvis responder duas vezes ao mesmo pedido: a frase do turno (ou o aviso de uma
ferramenta) e, quando a tarefa acabava, outra frase dizendo a mesma coisa. A regra é do **código**,
não do modelo: uma frase só vai à voz se traz algo que o dono ainda não ouviu deste pedido — um
resultado novo, um número, um nome, uma falha, uma pergunta. O resto fica na tela (e no card).

Comparação de palavras, sem modelo e sem rede, barata o bastante para rodar em cada frase:

- a frase vira **palavras de conteúdo**: sem artigo, preposição, pronome, verbo de ligação e sem o
  vocabulário de "deu certo" (pronto, abri, fechei, feito, aberto…), cada uma reduzida a um radical
  curto (o fim de verbo e de plural sai: "vídeos" e "vídeo" são a mesma palavra);
- o que já foi dito passa pelo mesmo crivo — e só ele: o pedido do dono não conta, porque "abri o
  vídeo mais recente" é a notícia de que o pedido ficou pronto, mesmo repetindo as palavras dele;
- é novo o radical que não está lá. Frase com **dois** radicais novos, ou com metade ou mais do
  conteúdo novo, ou com um número ou um nome próprio novo, traz algo ("Apaguei." depois de "Vou
  apagar."); com menos, é a repetição de sempre ("Pronto, o Discord está aberto na sua tela"
  depois de "Abrindo o Discord");
- falha ("não consegui", "nenhum", "erro") e pergunta só se calam quando repetem o que já foi dito
  palavra por palavra.

Antes de nada ser dito, tudo passa: a regra cala a **repetição**, nunca a primeira resposta.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from jarvis.s2.orcamento_da_fala import ABREVIACOES, FECHAMENTOS, FIM_DE_FRASE

PALAVRAS_DE_LIGACAO: Final = frozenset(
    {
        "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das", "em",
        "no", "na", "nos", "nas", "num", "numa", "por", "pelo", "pela", "pelos", "pelas", "para",
        "pra", "pro", "pras", "pros", "com", "sem", "sob", "sobre", "entre", "ate", "apos", "e",
        "ou", "mas", "nem", "que", "se", "como", "quando", "onde", "porque", "pois", "entao",
        "tambem", "ja", "ainda", "so", "mais", "menos", "muito", "muita", "bem", "aqui", "ali",
        "la", "ai", "agora", "hoje", "isso", "isto", "esse", "essa", "este", "esta", "esses",
        "essas", "estes", "estas", "aquele", "aquela", "ele", "ela", "eles", "elas", "eu", "voce",
        "voces", "me", "te", "lhe", "seu", "sua", "seus", "suas", "meu", "minha", "meus", "minhas",
        "dele", "dela", "ser", "sou", "era", "foi", "sao", "estar", "estou", "estava", "estao",
        "ficou", "fica", "ter", "tem", "tinha", "teve", "vai", "vou", "vamos", "ha", "havia",
        "sim", "ok", "certo", "tudo", "nele", "nela", "disso", "deste", "desta", "neste", "nesta",
    }
)  # fmt: skip
"""O que não carrega conteúdo numa frase falada (sem acento, minúsculas)."""
PALAVRAS_DE_RESULTADO: Final = frozenset(
    {
        "pronto", "prontinho", "feito", "feita", "beleza", "perfeito", "otimo", "abri", "abrir",
        "abrindo", "aberto", "aberta", "abertos", "abertas", "abre", "abra", "fechei", "fechar",
        "fechando", "fechado", "fechada", "fecha", "feche", "encerrei", "encerrar", "encerrando",
        "encerrado", "encerrada", "encerra", "encerre", "terminei", "terminar", "terminado",
        "terminada", "conclui", "concluido", "concluida", "fiz", "fazer", "coloquei", "pus",
        "botei", "deixei", "mostrei", "trouxe", "troquei", "foquei", "focado", "focada", "frente",
        "tela", "janela", "pedido", "pediu", "pedia", "solicitado", "cuido", "cuidar", "tarefa",
        "deu", "certinho", "consegui", "acabei", "acabou", "rodando", "rodou", "agorinha",
    }
)  # fmt: skip
"""O vocabulário de "deu certo": sozinho, não é novidade para quem já ouviu o que foi feito."""
MARCAS_DE_FALHA: Final = frozenset(
    {"nao", "nenhum", "nenhuma", "nunca", "nada", "erro", "falhou", "falha", "impossivel"}
)
NUMEROS: Final = frozenset(
    {
        "dois", "duas", "tres", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze",
        "doze", "treze", "catorze", "quatorze", "quinze", "dezesseis", "dezessete", "dezoito",
        "dezenove", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta",
        "noventa", "cem", "cento", "mil", "meia", "meio", "metade", "primeiro", "primeira",
    }
)  # fmt: skip
SUFIXOS: Final = (
    "amentos", "imentos", "amento", "imento", "mente", "acoes", "coes", "acao", "cao", "ando",
    "endo", "indo", "aram", "eram", "iram", "avam", "ados", "adas", "idos", "idas", "ado", "ada",
    "ido", "ida", "ava", "ias", "ia", "ar", "er", "ir", "ou", "ei", "as", "os", "es", "a", "o",
    "e", "s",
)  # fmt: skip
"""Do mais longo para o mais curto: um só sai, e o radical fica com 3 letras ou mais."""
RADICAIS_NOVOS: Final = 2
"""Quantos radicais novos fazem de uma frase comum uma novidade."""


def _dobrar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return sem_acento.casefold()


def radical(palavra: str) -> str:
    """A palavra sem o fim de verbo ou de plural (o primeiro sufixo que cabe)."""
    for sufixo in SUFIXOS:
        if palavra.endswith(sufixo) and len(palavra) - len(sufixo) >= 3:
            return palavra[: -len(sufixo)]
    return palavra


@dataclass(frozen=True, slots=True)
class _Palavra:
    dobrada: str
    nome_proprio: bool


def _palavras(texto: str) -> list[_Palavra]:
    """As palavras de conteúdo, com a marca de nome próprio (maiúscula fora do começo da frase)."""
    achadas: list[_Palavra] = []
    comeco = True
    for achado in re.finditer(r"\w+|[.!?…]", texto):
        bruta = achado.group(0)
        if bruta in FIM_DE_FRASE:
            comeco = True
            continue
        dobrada = _dobrar(bruta)
        proprio = bruta[:1].isupper() and not comeco
        comeco = False
        if dobrada in PALAVRAS_DE_LIGACAO or dobrada in PALAVRAS_DE_RESULTADO:
            continue
        if len(dobrada) < 3 and not dobrada.isdigit():
            continue
        achadas.append(_Palavra(dobrada, proprio))
    return achadas


def _radicais(textos: Iterable[str]) -> set[str]:
    return {radical(p.dobrada) for texto in textos for p in _palavras(texto)}


def traz_algo_novo(frase: str, ditos: Iterable[str]) -> bool:
    """A frase diz algo que o dono ainda não ouviu deste pedido?"""
    ditos = list(ditos)
    ja = _radicais(ditos)
    palavras = _palavras(frase)
    radicais = {radical(p.dobrada) for p in palavras}
    novos = [p for p in palavras if radical(p.dobrada) not in ja]
    dobrada = set(re.findall(r"\w+", _dobrar(frase)))
    if dobrada & MARCAS_DE_FALHA or frase.rstrip().rstrip(FECHAMENTOS).endswith("?"):
        # Falha e pergunta: só a repetição exata se cala (o dono precisa ouvir o erro uma vez).
        return not radicais <= ja or not radicais
    radicais_novos = {radical(p.dobrada) for p in novos}
    if len(radicais_novos) >= RADICAIS_NOVOS:
        return True
    if radicais_novos and len(radicais_novos) * 2 >= len(radicais):
        return True  # frase curta, quase toda nova: «Apaguei.» depois de «Vou apagar.»
    return any(p.dobrada.isdigit() or p.dobrada in NUMEROS or p.nome_proprio for p in novos)


def frases(texto: str) -> tuple[list[str], str]:
    """As frases completas do texto (cada uma com o espaço que vem depois) e o resto, sem fim."""
    completas: list[str] = []
    inicio = 0
    for achado in re.finditer(r"\S+(\s+)", texto):
        palavra = achado.group(0).rstrip()
        nua = palavra.rstrip(FECHAMENTOS)
        if not nua.endswith(FIM_DE_FRASE) or nua.casefold() in ABREVIACOES:
            continue
        if len(nua) == 2 and nua[0].isalpha():
            continue  # inicial de nome ("J. R. R. Tolkien")
        completas.append(texto[inicio : achado.end()])
        inicio = achado.end()
    return completas, texto[inicio:]


def so_o_novo(texto: str, ditos: Iterable[str]) -> str:
    """As frases do texto que trazem algo novo; sem nada dito antes, o texto inteiro."""
    filtro = FiltroDoJaDito(ditos=[d for d in ditos if d.strip()])
    if not filtro.ditos:
        return " ".join(texto.split())
    return " ".join((filtro.passar(texto) + filtro.fechar()).split())


def cita_ferramenta(frase: str, ids: Iterable[str]) -> bool:
    """A frase cita uma ferramenta pelo id ("usei files.read_text") ou traz argumento em JSON: é
    etapa interna, não fala (ADR-0038)."""
    if "{" in frase:
        return True
    return any(re.search(rf"(?<![\w.]){re.escape(i)}(?![\w])", frase) for i in ids)


@dataclass(slots=True)
class FiltroDoJaDito:
    """O filtro em stream: devolve as frases completas que trazem algo novo e guarda o resto.

    Cada frase que passa entra no que já foi dito: o modelo que repete a si mesmo na mesma resposta
    ("Abri o Discord. O Discord está aberto.") também é calado na segunda. Sem nada dito antes, só a
    frase de etapa interna (a que cita uma ferramenta de `ids`) fica de fora."""

    ditos: list[str]
    ids: frozenset[str] = frozenset()
    caladas: list[str] = field(default_factory=list)
    """As frases que não foram à voz (ficam na tela)."""
    _resto: str = ""

    def passar(self, delta: str) -> str:
        completas, self._resto = frases(self._resto + delta)
        return self._filtrar(completas)

    def fechar(self) -> str:
        resto, self._resto = self._resto, ""
        return self._filtrar([resto] if resto.strip() else [])

    def _filtrar(self, completas: list[str]) -> str:
        saida: list[str] = []
        for frase in completas:
            interna = cita_ferramenta(frase, self.ids)
            if not interna and (not self.ditos or traz_algo_novo(frase, self.ditos)):
                saida.append(frase)
                self.ditos.append(frase)
            else:
                self.caladas.append(" ".join(frase.split()))
        return "".join(saida)


__all__ = [
    "FiltroDoJaDito",
    "cita_ferramenta",
    "frases",
    "radical",
    "so_o_novo",
    "traz_algo_novo",
]
