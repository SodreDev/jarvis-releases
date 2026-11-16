"""O argumento de NOME que é um trecho da fala do dono copiado (ADR-0071).

O caso do dono (2026-11-16): «o contato da minha mãe é literalmente mãe salve para não esquecer
depois» virou o nome da conversa a abrir, «mãe salve para não esquecer depois». O esquema confere
o tipo; isto confere o **sentido** de um argumento marcado `x-nome: true` no manifesto (o rótulo
de um elemento, o nome de um app, de uma pessoa): um nome não é uma frase da fala.

Não decide nada pelo modelo: o que acha volta a ele como resultado (`causa="argumento_copiado"`),
com o porquê, e ele escolhe o valor. Se o nome é mesmo aquele, a mesma proposta de novo passa:
o código avisa uma vez por valor, nunca trava o pedido.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Final

PALAVRAS_MINIMAS: Final = 4
"""Abaixo disso o trecho cabe num nome de verdade («Mãe», «Bruno Lima», «Política de
Privacidade»); a partir daí, um trecho igual ao da fala é a fala copiada."""
MARCA_DE_NOME: Final = "x-nome"
CAUSA: Final = "argumento_copiado"


def _normal(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto.casefold())
    sem_acento = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", sem_acento).split())


def trecho_da_fala(valor: str, fala: str) -> bool:
    """`valor` tem ao menos `PALAVRAS_MINIMAS` palavras e aparece inteiro, na ordem, na fala."""
    normal = _normal(valor)
    if len(normal.split()) < PALAVRAS_MINIMAS:
        return False
    return f" {normal} " in f" {_normal(fala)} "


def copiado(
    esquema: Mapping[str, object], argumentos: Mapping[str, object], fala: str
) -> tuple[str, str] | None:
    """O primeiro argumento de nome (`x-nome`) que copia um trecho da fala: (nome, valor)."""
    if not fala.strip():
        return None
    propriedades = esquema.get("properties")
    if not isinstance(propriedades, Mapping):
        return None
    for nome, propriedade in propriedades.items():
        if not isinstance(propriedade, Mapping) or propriedade.get(MARCA_DE_NOME) is not True:
            continue
        valor = argumentos.get(nome)
        if isinstance(valor, str) and trecho_da_fala(valor, fala):
            return str(nome), valor
    return None


def motivo(nome: str, valor: str) -> str:
    """A notificação ao modelo: o que está errado e o que ele pode fazer — quem decide é ele."""
    return (
        f"o argumento `{nome}` recebeu «{valor}», que é um trecho da fala do dono, não um nome: "
        "decida você o valor — o nome como está na página, na lista ou na memória, curto. Se a "
        "fala trazia outro pedido (guardar, avisar, mandar), ele é outra ação. Se esse é mesmo o "
        "nome exato, proponha de novo igual e o sistema segue."
    )
