"""Domínio sistema — comandos de janela, volume do sistema, encerrar, screenshot, etc.

Regex extraídos do `main.py`. Os patterns aqui são uma extração defensiva:
qualquer match é só uma SUGESTÃO de intent — quem decide o handler final
ainda é o `main.py` legado, até a Sprint 3+ migrar os executores.
"""
from __future__ import annotations

import re

from .registry import IntentMatch, IntentRegistry


DOMAIN = "sistema"

# encerrar / desligar JARVIS (NÃO o computador)
SYS_ENCERRAR = re.compile(
    r"^\s*(encerrar?|finaliz[ae]r?|deslig[ae]r?\s+(jarvis|voc[eê])|sair|tchau|adeus|bye|goodbye)\s*[!.?]?\s*$",
    re.I,
)

# volume do sistema (Windows mixer) — distinto do Spotify
SYS_VOL_UP = re.compile(
    r"\b(aument[ae]r?|sob[ae]r?|m[ae]is\s+alto)\b.{0,30}\bvolume\s+(do\s+)?(sistema|windows|computador|pc)\b",
    re.I,
)
SYS_VOL_DOWN = re.compile(
    r"\b(diminu[ai]r?|abaix[ae]r?|m[ae]nos\s+alto)\b.{0,30}\bvolume\s+(do\s+)?(sistema|windows|computador|pc)\b",
    re.I,
)
SYS_MUTE = re.compile(
    r"\bmut[ae]r?\s+(o\s+)?(sistema|windows|computador|pc|tudo)\b",
    re.I,
)

# screenshot / print
SYS_SCREENSHOT = re.compile(
    r"\b(tira[r]?|fa[zç][ae][r]?|capturar?)\b.{0,15}\b(screenshot|print|captura\s+de\s+tela|prtsc)\b",
    re.I,
)

# janelas
SYS_MINIMIZE = re.compile(r"\bminimiz[ae]r?\b.{0,20}\bjanela|tudo\b", re.I)
SYS_MAXIMIZE = re.compile(r"\b(maximiz[ae]r?|tela\s+cheia)\b.{0,20}\bjanela\b", re.I)
SYS_CLOSE_WINDOW = re.compile(r"\bfech[ae]r?\b.{0,20}\bjanela\b", re.I)

# bloqueio / lock
SYS_LOCK = re.compile(r"\b(bloqu(?:e[ai]ar?|ear)|lock)\b.{0,15}\b(tela|computador|sistema|pc)\b", re.I)

# pesquisa "abre" alguma coisa — fica como sugestão de intent
SYS_ABRIR_APP = re.compile(
    r"\b(abr[ae]r?|inicia[r]?|execut[ae]r?|run|launch)\b.{0,40}\b(app|aplicativo|programa|software|browser|navegador|chrome|edge|firefox|spotify|discord|whatsapp|telegram|notion|vscode|code|notepad|calculator|calculadora)\b",
    re.I,
)


_RULES: list[tuple[re.Pattern[str], str]] = [
    (SYS_ENCERRAR,    "sistema.encerrar"),
    (SYS_VOL_UP,      "sistema.volume_up"),
    (SYS_VOL_DOWN,    "sistema.volume_down"),
    (SYS_MUTE,        "sistema.mute"),
    (SYS_SCREENSHOT,  "sistema.screenshot"),
    (SYS_MINIMIZE,    "sistema.minimizar_janela"),
    (SYS_MAXIMIZE,    "sistema.maximizar_janela"),
    (SYS_CLOSE_WINDOW,"sistema.fechar_janela"),
    (SYS_LOCK,        "sistema.bloquear_tela"),
    (SYS_ABRIR_APP,   "sistema.abrir_app"),
]


def detect(text: str) -> IntentMatch | None:
    t = text or ""
    for pat, name in _RULES:
        if pat.search(t):
            return IntentMatch(name=name, domain=DOMAIN)
    return None


def register_into(reg: IntentRegistry) -> None:
    reg.register(DOMAIN, detect)


__all__ = ["DOMAIN", "detect", "register_into"]
