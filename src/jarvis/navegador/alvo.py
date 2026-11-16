"""O alvo de uma ação na página conferido contra o que está NELA (ADR-0071).

O caso do dono (2026-11-16): o Jarvis decidiu abrir a conversa «mãe salve para não esquecer
depois» e o subagente clicou num `ref` do mapa sem nada conferir se aquele elemento era o que o
Jarvis queria. A realidade é a página: antes de agir, o nome que o Jarvis quer (`esperado`, ou o
`alvo` por texto) é comparado com o rótulo do elemento de verdade. Não bateu: a ação **não**
acontece, e o modelo recebe o que a página tem de mais parecido — ele escolhe, procura de outro
jeito ou pergunta ao dono. O código não escolhe por ele.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any, Final

PARECIDOS: Final = 5
SEMELHANCA_MINIMA: Final = 0.45
LIMITE_DO_ROTULO: Final = 60


def normal(texto: object) -> str:
    base = unicodedata.normalize("NFKD", str(texto or "").casefold())
    sem_acento = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", sem_acento).split())


CAMPOS_DO_NOME: Final = ("rotulo", "nome", "texto")
"""Onde o nome do elemento pode estar na resposta da extensão (`dadosDoElemento` e o mapa do
`content.js`): o `rotulo` (aria-label, placeholder, label) costuma vir vazio numa linha de
conversa do WhatsApp, e o nome do contato está no `texto` visível."""


def _rotulos(elemento: Mapping[str, Any]) -> list[str]:
    return [str(elemento[c]) for c in CAMPOS_DO_NOME if elemento.get(c)]


def confere(esperado: str, elemento: Mapping[str, Any]) -> bool:
    """O elemento é o que o Jarvis quer: o rótulo (ou o nome) é o esperado, ou começa por ele —
    a conversa «Mãe · 10:32 · ok» é a da «Mãe»; a «Carla: falei com o Bruno» não é a do Bruno."""
    procurado = normal(esperado)
    if not procurado:
        return True
    for rotulo in _rotulos(elemento):
        texto = normal(rotulo)
        if texto == procurado or texto.startswith(procurado + " "):
            return True
    return False


def parecidos(procurado: str, elementos: Iterable[Mapping[str, Any]]) -> list[str]:
    """Os rótulos da página mais parecidos com o procurado (sem acento e sem caixa), do mais
    parecido ao menos, sem repetir — para o modelo escolher ou perguntar ao dono."""
    alvo = normal(procurado)
    if not alvo:
        return []
    notas: dict[str, float] = {}
    for elemento in elementos:
        for rotulo in _rotulos(elemento):
            curto = " ".join(rotulo.split())[:LIMITE_DO_ROTULO]
            texto = normal(curto)
            if not texto:
                continue
            comeco = texto[: len(alvo) + 8]
            nota = max(
                difflib.SequenceMatcher(None, alvo, comeco).ratio(),
                difflib.SequenceMatcher(None, alvo, texto).ratio(),
                1.0 if alvo in texto.split() or texto in alvo.split() else 0.0,
            )
            if nota >= SEMELHANCA_MINIMA and nota > notas.get(curto, 0.0):
                notas[curto] = nota
    return [r for r, _ in sorted(notas.items(), key=lambda par: -par[1])[:PARECIDOS]]


def explicar(procurado: str, achado: str, opcoes: list[str]) -> str:
    """A notificação ao modelo quando o alvo não confere: o que há, e o que ele pode fazer."""
    if achado:
        inicio = f"o elemento que você escolheu é «{achado}», não «{procurado}»"
    else:
        inicio = f"«{procurado}» não está nesta página (nenhum elemento com esse texto)"
    lista = (
        "; os mais parecidos que estão nela: " + ", ".join(f"«{o}»" for o in opcoes)
        if opcoes
        else "; nada parecido está nela"
    )
    return (
        f"{inicio}{lista}. A ação NÃO aconteceu. Se um deles é sem dúvida o que o dono quis, "
        "aja nele pelo ref do mapa; se não, procure de outro jeito (role, busque) ou pergunte ao "
        "dono qual é — nunca clique por palpite."
    )


class AlvoNaoConfere(ValueError):
    """O alvo pedido não é o que está na página: a ação não aconteceu (ADR-0071)."""
