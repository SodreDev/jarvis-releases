"""Fechar a janela ou encerrar o app? Pela fala do dono (dono, 2026-10-21; ADR-0042).

"Fecha o Discord" e "fecha a janela" são a **janela**, como o X dela. "Fecha o Discord todo",
"inteiro", "de vez", "completamente", "por completo", "mata o Discord", "encerra o Steam",
"finaliza o Steam", "força o fechamento" são o **app** inteiro. A decisão é do código, pela fala —
como o método do pedido (ADR-0035) —, e o roteador tira do turno a ferramenta do outro lado: o
modelo que ouviu "fecha o Discord" não encerra o app, e o que ouviu "mata o Discord" não só fecha a
janela. Aba e guia são do navegador, não daqui. Encerrar o próprio Jarvis é outro caso (ADR-0041),
que o roteador pega antes.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Final


class Fechamento(StrEnum):
    JANELA = "janela"
    """`window.close`: a janela, como o X dela."""
    APP = "app"
    """`apps.quit`: o aplicativo inteiro, os processos dele."""


# Padrões como texto (sem `re.compile`): o `re` guarda o compilado, e a varredura de «sem shell»
# vale para a política também.
_ENCERRAR: Final = (
    r"\b(?:encerr\w*|mat[ae]|matar|finaliz\w*|forc\w*\s+(?:o\s+)?fechamento|"
    r"fech\w*\s+(?:a|na)\s+forca)\b"
)
_FECHAR: Final = r"\bfech(?:a|ar|e|em|ando)\b"
_INTEIRO: Final = (
    r"\b(?:todo|toda|inteiro|inteira|de\s+vez|completamente|por\s+completo|"
    r"o\s+processo|os\s+processos|de\s+verdade)\b"
)
_ABA: Final = r"\b(?:aba|abas|guia|guias)\b"


def _dobrar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return " ".join(re.sub(r"[^\w\s]", " ", sem_acento.casefold()).split())


def fechamento(fala: str) -> Fechamento | None:
    """Janela, app, ou `None` quando a fala não pede para fechar nada (ou fala de aba)."""
    texto = _dobrar(fala)
    if re.search(_ABA, texto):
        return None
    if re.search(_ENCERRAR, texto):
        return Fechamento.APP
    if re.search(_FECHAR, texto):
        return Fechamento.APP if re.search(_INTEIRO, texto) else Fechamento.JANELA
    return None


__all__ = ["Fechamento", "fechamento"]
