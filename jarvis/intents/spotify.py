"""Domínio Spotify — primeiro extraído do `main.py` (Plano 01 Fase B).

Espelha os regex `_SP_*` do `main.py`. Por ora vive em paralelo; quando
você validar que detecta exatamente o mesmo, removemos do `main.py`.
"""
from __future__ import annotations

import re

from .registry import IntentMatch, IntentRegistry


DOMAIN = "spotify"

SP_TOCAR = re.compile(
    r"\b(toc[ae]r?|play|coloc[ae]r?|p[oõ]r?|inicia[r]?)\b.{0,40}\b(spotify|m[uú]sica|son[s]?|cant[ao]r?|artista|playlist|[aá]lbum|album|som)\b",
    re.I,
)
SP_PLAYLIST = re.compile(r"\bplaylist\b", re.I)
SP_ALBUM    = re.compile(r"\b(álbum|album)\b", re.I)
SP_ARTISTA  = re.compile(r"\b(artista|cantor[ae]?|band[ao]|música[s]?\s+d[eo])\b", re.I)
SP_PAUSAR   = re.compile(
    r"\b(paus[ae]r?|pause|para[r]?|pare|stop|interromp[ae]r?)\b.{0,40}\b(spotify|m[uú]sica|som|reprodu[cç][aã]o|player)\b"
    r"|\b(spotify|m[uú]sica|som|reprodu[cç][aã]o|player)\b.{0,40}\b(paus[ae]r?|pause|para[r]?|pare|stop|interromp[ae]r?)\b"
    r"|\bp[ae]ra\s+a\s+m[uú]sica\b"
    r"|\bp[ae]usa\s+a[ií]\b"
    r"|^(paus[ae]r?|pause|pausa\s+a[ií]?|pare|stop)$",
    re.I,
)
SP_RETOMAR  = re.compile(r"\b(continuar|retomar|resume|despaus[ae]r?|toca\s+de\s+novo)\b", re.I)
SP_PROXIMA  = re.compile(r"\b(pr[oó]xim[ao]|pular|skip|avan[cç]ar|passa)\b", re.I)
SP_ANTERIOR = re.compile(r"\b(anterior|volta|voltar|back|a\s+de\s+antes)\b", re.I)
SP_VOL_UP   = re.compile(r"\b(aument[ae]r?|sob[ae]r?|m[ae]is\s+alto|levant[ae]r?)\b.{0,20}\b(volume|som)\b", re.I)
SP_VOL_DOWN = re.compile(r"\b(diminu[ai]r?|abaix[ae]r?|m[ae]nos\s+alto|baixe?[ae]r?)\b.{0,20}\b(volume|som)\b", re.I)
SP_VOL_MUTE = re.compile(r"\b(mut[ae]r?|silenci[ae]r?|tir[ae]r?\s+o?\s*som)\b", re.I)
SP_VOL_UNMUTE = re.compile(r"\b(desmut[ae]r?|dessilenci[ae]r?|volt[ae]r?\s+o?\s*som)\b", re.I)
SP_ATUAL    = re.compile(r"\b(qual\s+(?:m[uú]sica|son[s]?|t[áa]?\s+tocando)|que\s+(?:m[uú]sica|son[s]?)\s+(?:[éeé]|t[áa]?)\s+tocando|m[uú]sica\s+atual|tocando\s+agora)\b", re.I)


def detect(text: str) -> IntentMatch | None:
    t = text or ""
    if SP_PAUSAR.search(t):
        return IntentMatch(name="spotify.pause", domain=DOMAIN)
    if SP_RETOMAR.search(t):
        return IntentMatch(name="spotify.resume", domain=DOMAIN)
    if SP_PROXIMA.search(t):
        return IntentMatch(name="spotify.next", domain=DOMAIN)
    if SP_ANTERIOR.search(t):
        return IntentMatch(name="spotify.previous", domain=DOMAIN)
    if SP_VOL_MUTE.search(t):
        return IntentMatch(name="spotify.mute", domain=DOMAIN)
    if SP_VOL_UNMUTE.search(t):
        return IntentMatch(name="spotify.unmute", domain=DOMAIN)
    if SP_VOL_UP.search(t):
        return IntentMatch(name="spotify.volume_up", domain=DOMAIN)
    if SP_VOL_DOWN.search(t):
        return IntentMatch(name="spotify.volume_down", domain=DOMAIN)
    if SP_ATUAL.search(t):
        return IntentMatch(name="spotify.now_playing", domain=DOMAIN)
    if SP_TOCAR.search(t):
        payload = {
            "kind": (
                "playlist" if SP_PLAYLIST.search(t)
                else "album" if SP_ALBUM.search(t)
                else "artist" if SP_ARTISTA.search(t)
                else "track"
            )
        }
        return IntentMatch(name="spotify.play", domain=DOMAIN, payload=payload)
    return None


def register_into(reg: IntentRegistry) -> None:
    reg.register(DOMAIN, detect)


__all__ = ["DOMAIN", "detect", "register_into"]
