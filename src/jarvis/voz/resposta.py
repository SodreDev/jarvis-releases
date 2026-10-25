"""A resposta do dono a uma pergunta de confirmação, lida da fala (dono, 2026-10-25; ADR-0048).

O laço da trilha do dono (24/10): o Jarvis perguntou, o dono respondeu «Jarvis, sim» por cima da
pergunta, o corte derrubou a pergunta (não ouvida = não) e ela voltou — três vezes. E, sem a
palavra de ativação, o «sim» dito depois da pergunta era descartado no modo palavra, e o eco da
própria pergunta («…Posso?») podia virar "outro assunto" e cancelá-la.

Esta leitura é o que o laço de voz e a vigia usam quando há uma pergunta aberta:

- tira a palavra de ativação do começo («Jarvis, sim» → «sim»);
- tira o começo que é **eco da pergunta** (duas palavras ou mais seguidas que estão nela: o
  microfone pega o fim da fala do Jarvis junto com a do dono);
- o que sobra é `sim`, `nao` (o literal curto de `jarvis.s2.portao`, que pode vir seguido só
  de palavras da própria pergunta: «pode apagar» a «Posso apagar de vez?» — a ação que ele repete
  é a perguntada, e nenhuma outra), `eco` (nada sobrou, ou só palavras que a própria pergunta
  diz — uma resposta não pode ser só o eco dela) ou `outra` (outro pedido, outra conversa: quem
  decide é o fluxo de sempre).

Não autoriza nada sozinha: o "sim" lido aqui ainda vai pelo `ler_a_resposta` do cérebro, com a
pendência válida, e com os sinais do ASR que a ADR-0043 cobra.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from jarvis.s2.portao import RespostaDoDono, resposta_literal
from jarvis.voz.palavra import DetectorDePalavra


class TipoDaResposta(StrEnum):
    SIM = "sim"
    NAO = "nao"
    ECO = "eco"
    """Só a pergunta voltando pelo microfone: não é resposta nem outro assunto — ignora."""
    OUTRA = "outra"


@dataclass(frozen=True, slots=True)
class LeituraDaResposta:
    tipo: TipoDaResposta
    texto: str
    """O que vai ao cérebro: «sim»/«não» para uma resposta; a fala como veio para `outra`."""


def _palavras(texto: str) -> list[str]:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return re.findall(r"\w+", sem_acento.casefold())


def _sem_o_eco(palavras: list[str], pergunta: list[str]) -> list[str]:
    """Tira o prefixo de duas palavras ou mais que aparece, nessa ordem, na pergunta."""
    for tamanho in range(len(palavras), 1, -1):
        prefixo = palavras[:tamanho]
        if any(pergunta[i : i + tamanho] == prefixo for i in range(len(pergunta) - tamanho + 1)):
            return palavras[tamanho:]
    return palavras


def _literal_no_comeco(palavras: list[str], da_pergunta: set[str]) -> RespostaDoDono | None:
    """O literal mais longo do começo, se o que vem depois só repete palavras da pergunta."""
    for tamanho in range(len(palavras), 0, -1):
        literal = resposta_literal(" ".join(palavras[:tamanho]))
        if literal is not None and set(palavras[tamanho:]) <= da_pergunta:
            return literal
    return None


def ler_resposta(
    texto: str, pergunta: str, *, palavra: DetectorDePalavra | None = None
) -> LeituraDaResposta:
    """O que a fala é diante da pergunta aberta `pergunta` (o texto que o Jarvis falou)."""
    restante = texto
    if palavra is not None:
        achado = palavra.achar(texto)
        if achado is not None:
            if not achado.depois.strip():
                return LeituraDaResposta(TipoDaResposta.OUTRA, texto)  # só a chamada: arma a escuta
            restante = achado.depois  # o que vem antes da chamada é o eco do fim da fala dele
    palavras = _palavras(restante)
    da_pergunta = _palavras(pergunta)
    palavras = _sem_o_eco(palavras, da_pergunta)
    if not palavras or (da_pergunta and set(palavras) <= set(da_pergunta)):
        return LeituraDaResposta(TipoDaResposta.ECO, "")
    literal = _literal_no_comeco(palavras, set(da_pergunta))
    if literal is RespostaDoDono.SIM:
        return LeituraDaResposta(TipoDaResposta.SIM, "sim")
    if literal is RespostaDoDono.NAO:
        return LeituraDaResposta(TipoDaResposta.NAO, "não")
    return LeituraDaResposta(TipoDaResposta.OUTRA, texto)


__all__ = ["LeituraDaResposta", "TipoDaResposta", "ler_resposta"]
