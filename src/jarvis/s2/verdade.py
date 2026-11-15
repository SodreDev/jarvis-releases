"""Relato verdadeiro: o Jarvis só afirma o que as ferramentas confirmaram (ADR-0066).

O bug do dono (2026-11-14): «abre o contato da minha mãe e diz eu te amo». O motor escreveu
«Abri o contato da sua mãe» **antes** da ferramenta (a narração do primeiro passo vai à voz) e,
em vez de mandar, perguntou «quer que eu mande?». Nada tinha sido aberto: a ferramenta ficou
esperando o sim e não rodou. A persona já dizia «só diga que fez se o resultado confirmou»; o
modelo não obedeceu, e nenhum código conferia.

Aqui o código confere, frase por frase, antes da voz e da tela:

- **afirmação de efeito** («abri», «enviei», «mandei», «a mensagem foi enviada», «está
  aberto»): só passa se um resultado deste pedido a confirma — abrir: uma ferramenta que abre,
  clica ou navega deu `ok`; enviar: um envio deu `ok` **e** foi conferido (o chat mostra a
  mensagem: `conferido` no resultado do `social.enviar`, ou uma leitura da página depois do envio);
- **pergunta de permissão** («quer que eu mande?», «posso enviar?»): desde a ADR-0070 **não é
  cortada** — perguntar é decisão do Jarvis, não afirmação a conferir. O código só a reconhece
  (`Afirmacao.PEDE_PERMISSAO`), para a trilha; a persona é quem diz que pedido direto é para
  executar.

A frase cortada vai para a lista `cortadas` (a trilha conta; nada é dito). Quem chama decide o que
fazer: o laço do turno e o da tarefa cobram o motor para seguir até o objetivo (ou dizer o que
falta), e o fim da tarefa troca o relato que não se confirma pela frase do código.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from jarvis.s2.entrega import frases

if TYPE_CHECKING:
    from jarvis.executor.ferramentas import ResultadoDeFerramenta


class Afirmacao(StrEnum):
    ABRIU = "abriu"
    ENVIOU = "enviou"
    PEDE_PERMISSAO = "pede_permissao"


def _normal(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto.casefold())
    return " ".join("".join(c for c in base if not unicodedata.combining(c)).split())


_ENVIOU: Final = re.compile(
    r"\b(?:enviei|mandei|ja enviei|ja mandei|disse a ela|disse a ele|falei pra|falei para|"
    r"mensagem (?:foi |ja foi |esta )?enviada|mensagem (?:foi |ja foi )?mandada|"
    r"(?:foi|ja foi) enviad[ao]|(?:foi|ja foi) mandad[ao])\b"
)
_ABRIU: Final = re.compile(
    r"\b(?:abri|ja abri|entrei n[ao]s?|cliquei|esta abert[ao]|ja esta abert[ao]|"
    r"deixei abert[ao]|ficou abert[ao]|(?:foi|ja foi) abert[ao])\b"
)
_PEDE: Final = re.compile(
    r"\b(?:quer que eu|posso|devo|deseja que eu|gostaria que eu|prefere que eu|"
    r"me autoriza a|permite que eu|tenho (?:a sua )?permissao)\b.{0,40}?"
    r"\b(?:mand\w*|envi\w*|rod\w*|execut\w*|segu\w*|continu\w*|abr\w*|clic\w*|digit\w*|"
    r"diz\w*|dig\w*|fal\w*|faz\w*|fazer)\b"
)

ABREM: Final[frozenset[str]] = frozenset(
    {
        "sites.open",
        "apps.launch",
        "browser.launch",
        "browser.navigate",
        "browser.click",
        "browser.acionar",
        "browser.gesto",
        "browser.avaliar",
        "window.focus_app",
        "social.enviar",
    }
)
"""O que pode ter aberto alguma coisa: uma delas com `ok` confirma «abri»."""
LEITURAS: Final[frozenset[str]] = frozenset(
    {"browser.read", "browser.tela", "browser.inspecionar", "browser.tabs"}
)
"""A leitura depois do envio é a conferência: o chat mostra a mensagem."""


def afirmacoes(frase: str) -> frozenset[Afirmacao]:
    texto = _normal(frase)
    achadas: set[Afirmacao] = set()
    if "?" in frase and _PEDE.search(texto):
        achadas.add(Afirmacao.PEDE_PERMISSAO)
        return frozenset(achadas)
    if _afirma(_ENVIOU, texto):
        achadas.add(Afirmacao.ENVIOU)
    if _afirma(_ABRIU, texto):
        achadas.add(Afirmacao.ABRIU)
    return frozenset(achadas)


_NEGACAO: Final = re.compile(r"\b(?:nao|nem|nunca|ainda nao)\s+(?:\w+\s+){0,2}$")


def _afirma(padrao: re.Pattern[str], texto: str) -> bool:
    """O padrão aparece sem negação logo antes («não está aberto» e «não enviei» são honestos)."""
    return any(not _NEGACAO.search(texto[: achado.start()]) for achado in padrao.finditer(texto))


def envio_conferido(resultados: Sequence[ResultadoDeFerramenta]) -> bool:
    """Um envio deu certo **e** foi conferido: o `social.enviar` que leu a mensagem no chat, ou um
    envio pelo navegador seguido de uma leitura da página."""
    enviado_em: int | None = None
    for indice, resultado in enumerate(resultados):
        if resultado.status != "ok":
            continue
        if resultado.dados.get("conferido") is True:
            return True
        if resultado.dados.get("enviado") is True:
            enviado_em = indice
        elif enviado_em is not None and resultado.tool_id in LEITURAS:
            return True
    return False


def confirmada(afirmacao: Afirmacao, resultados: Sequence[ResultadoDeFerramenta]) -> bool:
    if afirmacao is Afirmacao.PEDE_PERMISSAO:
        return True  # perguntar não afirma nada: quem decide perguntar é o Jarvis (ADR-0070)
    if afirmacao is Afirmacao.ENVIOU:
        return envio_conferido(resultados)
    return any(r.status == "ok" and r.tool_id in ABREM for r in resultados)


@dataclass(frozen=True, slots=True)
class Relato:
    texto: str
    cortadas: tuple[str, ...] = ()
    perguntou: bool = False
    """Uma das cortadas era pergunta de permissão sobre o próprio pedido."""


def conferir(texto: str, resultados: Sequence[ResultadoDeFerramenta]) -> Relato:
    """O texto inteiro de uma vez (o fim da tarefa)."""
    filtro = FiltroDaVerdade(lambda: resultados)
    saida = filtro.passar(texto) + filtro.fechar()
    return Relato(saida.strip(), tuple(filtro.cortadas), filtro.perguntou)


@dataclass(slots=True)
class FiltroDaVerdade:
    """O filtro em stream (como o `FiltroDoJaDito`): devolve as frases completas que não afirmam
    o que ninguém confirmou e guarda o resto. `resultados` é lido a cada frase: o que a ferramenta
    confirmou no meio do turno vale para a frase seguinte."""

    resultados: Callable[[], Sequence[ResultadoDeFerramenta]]
    cortadas: list[str] = field(default_factory=list)
    perguntou: bool = False
    _resto: str = ""

    def passar(self, delta: str) -> str:
        completas, self._resto = frases(self._resto + delta)
        return self._filtrar(completas)

    def fechar(self) -> str:
        resto, self._resto = self._resto, ""
        return self._filtrar([resto] if resto.strip() else [])

    def _filtrar(self, completas: Iterable[str]) -> str:
        saida: list[str] = []
        resultados = self.resultados()
        for frase in completas:
            achadas = afirmacoes(frase)
            if all(confirmada(a, resultados) for a in achadas):
                saida.append(frase)
                continue
            self.cortadas.append(" ".join(frase.split()))
            if Afirmacao.PEDE_PERMISSAO in achadas:
                self.perguntou = True
        return "".join(saida)


NOTA_DE_SEGUIR: Final = (
    "ATENÇÃO: a sua última resposta afirmava algo que nenhuma ferramenta confirmou. Pedido "
    "direto é para executar: continue com "
    "as ferramentas até o objetivo estar cumprido e conferido (no navegador: troque de aba, leia a "
    "página, clique e digite pelo ref; se um caminho travar, tente outro). Só diga que fez o que "
    "um resultado confirmou; se for impossível, diga o que faltou e por quê."
)
SEM_CONFIRMACAO: Final = "Não consegui confirmar que ficou feito."
FALTA_ENVIAR: Final = "A mensagem ainda não foi enviada: não consegui confirmar o envio no chat."


def frase_do_que_falta(relato: Relato) -> str:
    """O que o código diz no lugar do relato que não se confirmou."""
    if any(Afirmacao.ENVIOU in afirmacoes(f) for f in relato.cortadas) or relato.perguntou:
        return FALTA_ENVIAR if _fala_de_envio(relato.cortadas) else SEM_CONFIRMACAO
    return SEM_CONFIRMACAO


def _fala_de_envio(cortadas: Iterable[str]) -> bool:
    return any(re.search(r"\b(?:mand|envi|mensagem|diz|dig|fal)", _normal(f)) for f in cortadas)


__all__ = [
    "ABREM",
    "FALTA_ENVIAR",
    "LEITURAS",
    "NOTA_DE_SEGUIR",
    "SEM_CONFIRMACAO",
    "Afirmacao",
    "FiltroDaVerdade",
    "Relato",
    "afirmacoes",
    "conferir",
    "confirmada",
    "envio_conferido",
    "frase_do_que_falta",
]
