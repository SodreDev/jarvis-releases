"""Domínio mensageria — detecta intent de envio/leitura em qualquer plataforma.

Importante: este detector apenas identifica QUE o usuário quer enviar/ler
mensagem em alguma plataforma. A escolha do backend (e do perfil
`jarvis`/`user`) é feita pelo `MessagingRouter`.

Payload retornado:
    {
        "platform": "whatsapp" | "instagram" | "discord" | "telegram" | "gmail",
        "action":   "send" | "read" | "open",
        "dest":     <quando capturável via regex> ou None,
        "content":  <conteúdo depois de "dizendo"/"falando"> ou None,
        "profile_hint": "jarvis" | "user" | None,
    }
"""
from __future__ import annotations

import re

from .registry import IntentMatch, IntentRegistry


DOMAIN = "mensageria"

# Plataformas suportadas e seus aliases
_PLATFORM_PATTERNS: dict[str, re.Pattern[str]] = {
    "whatsapp":  re.compile(r"\b(whats?\s*app|whats?|zap|wa)\b", re.I),
    "instagram": re.compile(r"\b(instagram|insta|ig|direct)\b", re.I),
    "discord":   re.compile(r"\b(discord|dc)\b", re.I),
    "telegram":  re.compile(r"\b(telegram|tg|telega)\b", re.I),
    "gmail":     re.compile(r"\b(gmail|e[\-]?mail|email|correio)\b", re.I),
}

# Verbo de envio
_SEND = re.compile(
    r"\b(mand[ae]r?|envi[ae]r?|escrev[ae]r?|manda|envia|escreve|diz[ae]?r?|fal[ae]r?|texta?[r]?)\b",
    re.I,
)

# Verbo de leitura
_READ = re.compile(
    r"\b(l[eê]r?|le|ver|checar?|abr[ae]r?\s+(?:a)?\s*caixa)\b.{0,30}\b(mensage(?:ns|m|ms|s)?|inbox|caixa|dms?)\b",
    re.I,
)

# Verbo de abrir (sem ação imediata)
_OPEN = re.compile(
    r"\b(abr[ae]r?|inicia[r]?|carreg[ae]r?)\b",
    re.I,
)

# Perfil hint: "do meu", "no meu", "pelo seu", "pelo jarvis"
_PROFILE_USER  = re.compile(r"\b(do|no|pelo|pela|com\s+o|com\s+a)\s+meu\b|\bmeu\s+(whats|insta|ig|gmail|telegram|discord)\b|pessoal", re.I)
_PROFILE_JARVIS = re.compile(r"\bpelo\s+seu|pelo\s+jarvis|conta\s+jarvis|seu\s+(whats|insta|ig|gmail|telegram|discord)\b", re.I)

# Destinatário pós-"para"/"pro"/"pra"
_DEST = re.compile(
    r"\bp(?:ara|ro|ra)\s+(?:o|a)?\s*([A-Za-zÀ-ÿ0-9_\.\-@\+]{2,40})",
    re.I,
)

# Conteúdo pós-"dizendo"/"falando"/"escrevendo"/"que diga"
_CONTENT = re.compile(
    r"\b(?:dizendo|falando|escrevendo|que\s+(?:diga|fale|escreva))\s+(?:que\s+)?(.+)$",
    re.I,
)


def _detect_platform(t: str) -> str | None:
    for plat, pat in _PLATFORM_PATTERNS.items():
        if pat.search(t):
            return plat
    return None


def detect(text: str) -> IntentMatch | None:
    t = text or ""
    plat = _detect_platform(t)
    if not plat:
        return None

    action: str | None = None
    if _SEND.search(t):
        action = "send"
    elif _READ.search(t):
        action = "read"
    elif _OPEN.search(t):
        action = "open"
    if not action:
        return None

    dest_m = _DEST.search(t)
    content_m = _CONTENT.search(t)

    profile_hint: str | None = None
    if _PROFILE_USER.search(t):
        profile_hint = "user"
    elif _PROFILE_JARVIS.search(t):
        profile_hint = "jarvis"

    return IntentMatch(
        name=f"mensageria.{action}",
        domain=DOMAIN,
        payload={
            "platform": plat,
            "action": action,
            "dest": dest_m.group(1).strip() if dest_m else None,
            "content": content_m.group(1).strip() if content_m else None,
            "profile_hint": profile_hint,
        },
    )


def register_into(reg: IntentRegistry) -> None:
    reg.register(DOMAIN, detect)


__all__ = ["DOMAIN", "detect", "register_into"]
