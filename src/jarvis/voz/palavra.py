"""Palavra de ativação: casamento **fonético** sobre a transcrição (ADR-0021).

**Por que não um modelo de wake word.** openWakeWord, Porcupine e companhia são modelos
pré-treinados com termos próprios — e termo não verificado não entra (ADR-0011, ADR-0012). O
caminho daqui não acrescenta dependência nenhuma: o ASR **local** já transcreve o trecho que o
VAD abriu, e a pergunta "ele me chamou?" vira comparação fonética entre o que foi transcrito e
a palavra que o dono escolheu.

**Por que fonética e não igualdade de texto.** O ASR não escreve "jarvis" todas as vezes:
escreve "járvis", "jarvas", "djarvis", "jarves", "jarvis," — e, em frase longa, separa
("jar vis"). Comparar texto cru erraria em todas essas, e comparar por "contém" erraria para o
outro lado. O que se compara aqui é a **forma sonora**: a palavra vira símbolos e a distância
de edição entre os dois diz o quanto se parecem, de 0 a 1.

**Dois fonemizadores, e o padrão é o que roda em qualquer lugar.** `fonetica_simples` é uma
redução pt-BR escrita aqui, sem dependência, que roda em qualquer lugar; quem tiver o `epitran`
(MIT, o mesmo do TTS, grupo `voz`) passa `FonemizadorEpitran()` e ganha o IPA de verdade. **Os
dois foram medidos sobre texto** (corpus sintético, vizinhos e grafias escritos à mão) e
escolheram o mesmo limiar; a medição e o que ela não cobre estão na ADR-0021.

**O que este módulo não faz:** não ouve, não abre dispositivo, não transcreve e não fala com
a rede. Ele recebe texto e devolve "era comigo, e o pedido é este". Quem garante que o ASR só
roda sob VAD — isto é, que silêncio não vira transcrição — é o laço (`jarvis.voz.app`).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

PALAVRA_PADRAO: Final = "jarvis"
LIMIAR_PADRAO: Final = 0.75
"""**Medido** (`tools/harness_palavra.py`, `docs/medicoes/palavra-de-ativacao.csv`): com
`jarvis`, as grafias de ASR dão 0,833 ou mais e os vizinhos (`jarbas`, `marvin`, `davis`,
`jardim`, "já vi") dão 0,667 ou menos, nos dois fonemizadores; nenhuma das 340 frases do corpus
passa de 0,50. Como cada edição custa 1/6 de um alvo de seis símbolos, 0,75 quer dizer "no
máximo uma edição" — o meio do degrau, longe das duas bordas. É medição sobre **texto**: o
quanto o ASR erra o nome na voz do dono não foi medido (ADR-0021)."""
LIMIAR_MINIMO: Final = 0.50
LIMIAR_MAXIMO: Final = 1.0
JANELA_MAXIMA: Final = 2
"""Quantas palavras seguidas da transcrição podem formar **uma** candidata. Duas, porque o
ASR parte nome próprio em dois ("jar vis") e não costuma partir em três."""
LIMITE_DE_PALAVRAS: Final = 64
"""Teto de palavras examinadas por trecho: o que o VAD entrega é uma fala, não um texto."""

_NAO_PALAVRA: Final = re.compile(r"[^0-9a-zà-öø-ÿ]+", re.IGNORECASE)


class PalavraInvalida(ValueError):
    """A palavra de ativação escolhida não serve. A frase diz por quê."""


def exigir_palavra(bruta: str) -> str:
    """A palavra que o dono escolheu, ou a recusa dizendo o que falta.

    Uma letra não serve: "a" casaria com metade do português. Duas palavras também não
    ("ô jarvis"), porque a janela de comparação é de duas palavras e a sobra viraria comando.
    """
    limpa = bruta.strip().lower()
    if not limpa:
        raise PalavraInvalida("a palavra de ativação não pode ser vazia")
    if _NAO_PALAVRA.sub("", limpa) != limpa.replace(" ", ""):
        raise PalavraInvalida(f"{bruta!r} tem pontuação ou símbolo: use só letras")
    if len(limpa.split()) > 1:
        raise PalavraInvalida(
            f"{bruta!r} tem mais de uma palavra; escolha uma só (a comparação é por palavra)"
        )
    if len(limpa) < 3:
        raise PalavraInvalida(
            f"{bruta!r} é curta demais para servir de chamada: com menos de três letras ela "
            "casa com pedaço de palavra comum e o microfone abre sozinho"
        )
    return limpa


def exigir_limiar(bruto: float) -> float:
    """O limiar é do dono, mas tem piso: abaixo de 0,50 qualquer coisa vira chamada."""
    try:
        valor = float(bruto)
    except (TypeError, ValueError):
        raise PalavraInvalida(f"limiar {bruto!r} não é número") from None
    if not LIMIAR_MINIMO <= valor <= LIMIAR_MAXIMO:
        raise PalavraInvalida(
            f"limiar {valor} fora da faixa: use de {LIMIAR_MINIMO} a {LIMIAR_MAXIMO:.1f}"
        )
    return valor


def sem_acento(texto: str) -> str:
    """Tira marca combinante (NFD) e devolve o resto. `járvis` e `jarvis` soam igual."""
    decomposto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def palavras_de(texto: str) -> list[str]:
    """As palavras da transcrição, sem pontuação e em minúsculas."""
    return [p for p in _NAO_PALAVRA.split(texto.lower()) if p][:LIMITE_DE_PALAVRAS]


# --- a redução fonética que não depende de nada --------------------------------------------
#
# Não é IPA e não quer ser: é um alfabeto de **classes de som** do pt-BR, grosso o bastante
# para que grafias diferentes do mesmo som caiam no mesmo símbolo. Cada regra abaixo existe
# por uma confusão concreta de ASR, e a ordem importa — dígrafo antes de letra solta.
_DIGRAFOS: Final[tuple[tuple[str, str], ...]] = (
    ("lh", "L"),
    ("nh", "N"),
    ("ch", "S"),
    ("rr", "R"),
    ("ss", "s"),
    ("sc", "s"),
    ("sh", "S"),
    ("qu", "k"),
    ("gu", "g"),
    ("dj", "J"),  # "djarvis" é a grafia mais comum do ASR para o ataque de "jarvis"
    ("tch", "S"),
    ("ph", "f"),
)
_SIMPLES: Final[dict[str, str]] = {
    "a": "a",
    "á": "a",
    "b": "b",
    "c": "k",
    "ç": "s",
    "d": "d",
    "e": "e",
    "f": "f",
    "g": "g",
    "h": "",  # mudo em português
    "i": "i",
    "j": "J",
    "k": "k",
    "l": "l",
    "m": "m",
    "n": "n",
    "o": "o",
    "p": "p",
    "q": "k",
    "r": "r",
    "s": "s",
    "t": "t",
    "u": "u",
    "v": "v",
    "w": "v",
    "x": "S",
    "y": "i",
    "z": "z",
}
_VOGAIS: Final[frozenset[str]] = frozenset("aeiou")


def fonetica_simples(texto: str) -> str:
    """A palavra reduzida a classes de som do pt-BR. Sem dependência, determinística.

    O que ela resolve, e é o que a medição cobra: `j`, `g` antes de `e`/`i` e `dj` dão o mesmo
    símbolo (`J`), `c`/`qu`/`k` dão `k`, `x`/`ch` dão `S`, o `h` some, vogal átona final
    fecha (`e`→`i`, `o`→`u`, como se fala no Brasil) e letra repetida vira uma só.
    """
    bruto = sem_acento(texto.lower())
    saida: list[str] = []
    indice = 0
    while indice < len(bruto):
        for grafia, simbolo in _DIGRAFOS:
            # `gu`/`qu` só perdem o `u` antes de `e`/`i` (`guerra`, mas `água`): fora disso
            # não são dígrafo, e a letra segue pelo caminho de letra solta. Um `break` aqui
            # pulava o avanço do índice e prendia `quando` e `água` num laço sem fim.
            if bruto.startswith(grafia, indice) and (
                grafia not in {"gu", "qu"} or bruto[indice + 2 : indice + 3] in {"e", "i"}
            ):
                saida.append(simbolo)
                indice += len(grafia)
                break
        else:
            letra = bruto[indice]
            seguinte = bruto[indice + 1 : indice + 2]
            if letra == "g" and seguinte in {"e", "i"}:
                saida.append("J")
            elif letra == "c" and seguinte in {"e", "i"}:
                saida.append("s")
            elif letra == "s" and saida and saida[-1] in _VOGAIS and seguinte in _VOGAIS:
                saida.append("z")  # `casa` soa `caza`
            else:
                saida.append(_SIMPLES.get(letra, letra))
            indice += 1
    simbolos = "".join(saida)
    if simbolos.endswith("e"):
        simbolos = simbolos[:-1] + "i"
    elif simbolos.endswith("o"):
        simbolos = simbolos[:-1] + "u"
    elif simbolos.endswith(("es", "eS")):
        simbolos = simbolos[:-2] + "i" + simbolos[-1]
    elif simbolos.endswith(("os", "oS")):
        simbolos = simbolos[:-2] + "u" + simbolos[-1]
    return _sem_repeticao(simbolos)


def _sem_repeticao(simbolos: str) -> str:
    saida: list[str] = []
    for simbolo in simbolos:
        if not saida or saida[-1] != simbolo:
            saida.append(simbolo)
    return "".join(saida)


# --- distância ------------------------------------------------------------------------------
def distancia(a: str, b: str) -> int:
    """Distância de edição (Levenshtein) entre duas sequências de símbolos.

    Quinze linhas e nenhuma dependência nova. O caso que importa aqui é curto — nome próprio
    contra nome próprio —, então o custo não aparece ao lado do ASR.
    """
    if a == b:
        return 0
    if not a or not b:
        return len(a) or len(b)
    anterior = list(range(len(b) + 1))
    for i, letra_a in enumerate(a, start=1):
        atual = [i]
        for j, letra_b in enumerate(b, start=1):
            atual.append(
                min(
                    anterior[j] + 1,  # remoção
                    atual[j - 1] + 1,  # inserção
                    anterior[j - 1] + (letra_a != letra_b),  # troca
                )
            )
        anterior = atual
    return anterior[-1]


def similaridade(a: str, b: str) -> float:
    """De 0 a 1: 1 é a mesma forma sonora, 0 é nada em comum."""
    if not a and not b:
        return 1.0
    maior = max(len(a), len(b))
    return 1.0 - distancia(a, b) / maior if maior else 1.0


# --- o detector -------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Achado:
    """O que o detector ouviu: a chamada, o quanto se parece e o que sobrou para o Jarvis."""

    ouvido: str
    """As palavras da transcrição que casaram — é o que a tela mostra ("ouvi: 'járvis'")."""
    similaridade: float
    antes: str
    depois: str

    @property
    def comando(self) -> str:
        """O pedido do dono: o que vem **depois** da chamada ou, se nada vier, o que vem antes.

        "jarvis, que horas são" e "que horas são, jarvis" são a mesma frase para quem fala.
        Aceitar só a primeira obrigaria o dono a aprender a ordem que o código prefere.
        """
        return self.depois or self.antes

    @property
    def so_o_nome(self) -> bool:
        """Ele só chamou. O laço arma a escuta e espera o pedido no trecho seguinte."""
        return not self.comando


@dataclass(slots=True)
class DetectorDePalavra:
    """ "Ele me chamou?" — sobre a transcrição, sem ouvir nada por conta própria."""

    palavra: str = PALAVRA_PADRAO
    limiar: float = LIMIAR_PADRAO
    fonetica: Callable[[str], str] = fonetica_simples
    _alvo: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        self.palavra = exigir_palavra(self.palavra)
        self.limiar = exigir_limiar(self.limiar)
        self._alvo = self.fonetica(self.palavra)

    @property
    def alvo(self) -> str:
        """A forma sonora da palavra escolhida. Pública porque a tela e o harness a mostram."""
        return self._alvo

    def parecenca(self, candidata: str) -> float:
        """O quanto uma palavra solta se parece com a chamada. É o que o harness varre."""
        return similaridade(self.fonetica(candidata), self._alvo)

    def achar(self, texto: str) -> Achado | None:
        """A melhor chamada do trecho, ou `None` quando não era com ele.

        Varre janelas de uma e duas palavras e fica com a de maior parecença — a janela de
        duas existe porque o ASR escreve nome próprio partido, e sem ela "jar vis" nunca
        chamaria. Empate fica com a janela menor: "jarvis abre" não deve engolir o verbo.
        """
        palavras = palavras_de(texto)
        if not palavras:
            return None
        melhor: tuple[float, int, int] | None = None
        for tamanho in range(1, JANELA_MAXIMA + 1):
            for inicio in range(len(palavras) - tamanho + 1):
                candidata = "".join(palavras[inicio : inicio + tamanho])
                nota = similaridade(self.fonetica(candidata), self._alvo)
                if nota >= self.limiar and (melhor is None or nota > melhor[0]):
                    melhor = (nota, inicio, tamanho)
        if melhor is None:
            return None
        nota, inicio, tamanho = melhor
        return Achado(
            ouvido=" ".join(palavras[inicio : inicio + tamanho]),
            similaridade=nota,
            antes=" ".join(palavras[:inicio]),
            depois=" ".join(palavras[inicio + tamanho :]),
        )
