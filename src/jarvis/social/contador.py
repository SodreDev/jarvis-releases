"""A amostra do contador que o `social.js` não reconheceu (ADR-0060, emenda de 2026-11-13).

Quando um contador de não lidas vem num formato novo (ou a lista de conversas some), a extensão
manda uma `amostra` curta do texto bruto, para o dono mandar no diagnóstico e o seletor ser
ajustado. Ela já vem sanitizada pelo `social.js`; aqui ela é sanitizada **de novo**, antes de ir
à tela ou à trilha, com a mesma regra: palavra fora do vocabulário do contador vira «x», o que
parece telefone vira «###», e sobra só dígito, vocabulário e pontuação de número. Nome de quem
mandou, texto de mensagem e telefone não passam.

O vocabulário é o mesmo de `extensao/social-seletores.js` (`vocabularioDaAmostra`): o teste
confere que as duas listas são iguais."""

from __future__ import annotations

import re
import unicodedata
from typing import Final

LIMITE: Final = 60
VOCABULARIO: Final = frozenset(
    {
        "whatsapp",
        "instagram",
        "facebook",
        "messenger",
        "tiktok",
        "discord",
        "mensagem",
        "mensagens",
        "nao",
        "lida",
        "lidas",
        "lido",
        "lidos",
        "marcada",
        "como",
        "conversa",
        "conversas",
        "unread",
        "message",
        "messages",
        "marked",
        "as",
        "chat",
        "chats",
        "mensaje",
        "mensajes",
        "no",
        "leido",
        "leidos",
        "leida",
        "leidas",
        "sin",
        "leer",
        "mil",
        "k",
        "mais",
        "more",
        "mas",
        "de",
        "e",
        "y",
        "and",
    }
)
"""As únicas palavras que sobram numa amostra (sem acento, minúsculas)."""

_TELEFONE: Final = re.compile(r"\+?\d[\d ().-]{6,}\d")
_PALAVRA: Final = re.compile(r"[^\W\d_]+")
_FORA: Final = re.compile(r"[^a-z0-9#()+.,:|/ x-]")
_ESPACOS_DE_NUMERO: Final = re.compile("[    ]")


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c)).lower()


def _em_ascii(texto: str) -> str:
    """NFKC e os dígitos de outros alfabetos levados ao ASCII (`unicodedata.decimal`)."""
    normal = _ESPACOS_DE_NUMERO.sub(" ", unicodedata.normalize("NFKC", texto))
    return "".join(
        str(unicodedata.decimal(c)) if c.isdecimal() and not c.isascii() else c for c in normal
    )


def amostra_segura(texto: object) -> str:
    """A amostra pronta para a tela e para a trilha: sem dado de ninguém, até `LIMITE`."""
    bruto = "".join(" " if unicodedata.category(c)[0] == "C" else c for c in str(texto)[:200])
    normal = _TELEFONE.sub("###", _em_ascii(bruto))
    palavras = _PALAVRA.sub(
        lambda achado: (
            _sem_acento(achado.group(0)) if _sem_acento(achado.group(0)) in VOCABULARIO else "x"
        ),
        normal,
    )
    return " ".join(_FORA.sub(" ", palavras).split())[:LIMITE]


__all__ = ["LIMITE", "VOCABULARIO", "amostra_segura"]
