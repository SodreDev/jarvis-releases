"""A nota do dono para um turno: 👍 ou 👎, pelo botão da janela ou por uma frase (ADR-0063).

Sem um sinal de qualidade, não dá para comparar presets por acerto (backlog B5) nem montar um
banco de casos do próprio dono (B12). Aqui só se **grava** a nota na trilha, ligada ao turno
anterior: nada é treinado, nada muda no prompt, e a frase continua indo ao cérebro como sempre.

A leitura da fala é do **código**, conservadora: a frase de nota tem de estar no começo da fala
(`PALAVRAS_DO_COMECO`), a fala não pode ter as duas notas, e «não ficou ruim» não vale nada
(negação de nota é ambígua). Errar para o lado de não anotar é barato; anotar errado polui a
medida. «Valeu» e «isso mesmo» ficam de fora: são agradecimento e confirmação, não nota.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

from jarvis.s2.portao import normalizar


class Nota(StrEnum):
    BOA = "boa"
    RUIM = "ruim"


PALAVRAS_DO_COMECO: Final = 6
"""A frase de nota tem de começar nas primeiras palavras da fala."""
VALE_POR_S: Final = 600.0
"""A nota dita vale para o turno anterior só se ele acabou há menos que isto."""

FRASES: Final[dict[Nota, tuple[str, ...]]] = {
    Nota.BOA: (
        "ficou otimo",
        "ficou bom",
        "ficou muito bom",
        "ficou perfeito",
        "ficou excelente",
        "mandou bem",
        "boa jarvis",
        "muito bem jarvis",
        "perfeito jarvis",
        "excelente jarvis",
        "otima resposta",
        "boa resposta",
        "gostei da resposta",
    ),
    Nota.RUIM: (
        "ficou ruim",
        "ficou pessimo",
        "ficou horrivel",
        "ficou errado",
        "nao era isso",
        "nao foi isso que eu pedi",
        "nao foi isso",
        "voce errou",
        "errou jarvis",
        "resposta ruim",
        "pessima resposta",
        "ta errado",
        "esta errado",
        "nao gostei",
    ),
}
"""Sem acento e em minúsculas (como `normalizar` deixa a fala)."""

_NEGACOES: Final = frozenset({"nao", "nem", "nunca", "jamais"})


def _palavras(texto: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", normalizar(texto)).split()


def _acha(palavras: list[str], frase: str) -> int | None:
    """Onde a frase começa, se começar nas primeiras palavras."""
    alvo = frase.split()
    for inicio in range(min(PALAVRAS_DO_COMECO, len(palavras))):
        if palavras[inicio : inicio + len(alvo)] == alvo:
            return inicio
    return None


def nota_na_fala(fala: str) -> Nota | None:
    """A nota que a fala dá ao turno anterior; `None` = não é nota (ou é ambígua)."""
    palavras = _palavras(fala)
    if not palavras:
        return None
    achadas: set[Nota] = set()
    for nota, frases in FRASES.items():
        for frase in frases:
            inicio = _acha(palavras, frase)
            if inicio is None:
                continue
            if (
                frase.split()[0] not in _NEGACOES
                and inicio > 0
                and palavras[inicio - 1] in _NEGACOES
            ):
                return None  # «não ficou ruim», «nem ficou bom»: negação de nota não vale
            achadas.add(nota)
    if len(achadas) != 1:
        return None
    return achadas.pop()


def nota_do_botao(boa: bool) -> Nota:
    return Nota.BOA if boa else Nota.RUIM


__all__ = ["FRASES", "PALAVRAS_DO_COMECO", "VALE_POR_S", "Nota", "nota_do_botao", "nota_na_fala"]
