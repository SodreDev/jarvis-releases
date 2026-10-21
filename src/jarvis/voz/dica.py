"""A dica do ASR: curta de propósito (ADR-0043).

O ASR aceita um texto que "vem antes" do áudio — o `initial_prompt` do whisper local, o `prompt`
da Groq (até 224 tokens) — e escreve melhor o que estiver nele: "Thiago Nigro" em vez de "Tiago
Negro". Mas é **o mesmo** texto que ele devolve quando o trecho não tem fala. Medido com áudio
sintético (`docs/medicoes/ruido-e-dica.md`): a lista de 31 apps instalados que ia como dica fez
**todo** ruído forçado no whisper virar texto ("Bazaar, Bazaar, Borderlands 2, Brave Web
Browser"), e sem dica nenhum virou; uma dica curta (a palavra de ativação e poucos termos do
dono) não fez nenhum ruído virar texto e ainda acertou o nome próprio. A mesma lista em
`hotwords` vazou mais do que em `initial_prompt` — por isso a dica vai só como texto inicial.

Os apps instalados **saíram** da dica: quem casa a fala com o app é o resolvedor fonético de
`jarvis.apps`, contra o catálogo, depois do ASR. O que entra é o que o dono escolheu ouvir certo
(o vocabulário dele, `jarvis.voz.vocabulario`) — e o filtro de ruído reconhece o eco dela.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from jarvis.voz.ruido import normalizar

LIMITE_DE_TERMOS: Final = 12
"""Termos na dica, contando a palavra de ativação. Poucos de propósito: dica longa é ruído que
vira texto."""
LIMITE_DE_CARACTERES: Final = 200
"""Bem abaixo dos 224 tokens que a Groq aceita: a dica nunca é cortada pelo serviço."""


def _com_inicial(termo: str) -> str:
    """O whisper ignora "jarvis" em minúsculas e acerta com "Jarvis" (medido em 2026-10-17):
    palavra toda em minúsculas ganha a inicial; "TeamSpeak" e "OBS" ficam como estão."""
    return " ".join(p[:1].upper() + p[1:] if p.islower() else p for p in termo.split())


def dica_do_asr(
    palavra: str,
    termos: Iterable[str] = (),
    *,
    limite_de_termos: int = LIMITE_DE_TERMOS,
    limite_de_caracteres: int = LIMITE_DE_CARACTERES,
) -> str:
    """ "Jarvis, Discord, Thiago Nigro." — a palavra de ativação primeiro, depois os termos, sem
    repetir o que só difere em caixa ou acento, até o orçamento. Vazio = sem dica."""
    escolhidos: list[str] = []
    vistos: set[str] = set()
    for bruto in (palavra, *termos):
        termo = _com_inicial(" ".join(str(bruto).split()))
        chave = normalizar(termo)
        if not chave or chave in vistos:
            continue
        if len(escolhidos) >= limite_de_termos:
            break
        if len(", ".join((*escolhidos, termo))) + 1 > limite_de_caracteres:
            break
        vistos.add(chave)
        escolhidos.append(termo)
    return f"{', '.join(escolhidos)}." if escolhidos else ""


__all__ = ["LIMITE_DE_CARACTERES", "LIMITE_DE_TERMOS", "dica_do_asr"]
