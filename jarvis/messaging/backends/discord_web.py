"""Discord (discord.com/app ou ptb.discord.com) — Chromium-only.

ATENÇÃO: NÃO usar discord.py nem qualquer API de bot. Tudo via UI web
simulando humano, preservando login na pasta do perfil. `dest` é o ID
do canal ou DM (formato: 'channels/@me/<id>' ou 'channels/<server>/<channel>').
"""
from __future__ import annotations

from typing import ClassVar

from ..base import MessageBackend, Platform, Profile, register_backend
from ..web_base import WebChatBackend


class _DiscordWebBase(WebChatBackend):
    platform: ClassVar[Platform] = "discord"
    URL_HOME = "https://discord.com/app"
    URL_CHAT_PATTERN = "https://discord.com/{dest}"  # dest = "channels/@me/<id>"
    SEL_COMPOSER = 'div[role="textbox"][data-slate-editor="true"]'
    SEL_SEND_BUTTON = None  # Discord envia com Enter
    SEL_LOGGED_IN = 'nav[aria-label="Servers sidebar"], nav[aria-label="Barra lateral de servidores"]'
    SEL_LOGIN_HINT = 'input[name="email"]'
    LOGIN_TIMEOUT_S = 120
    # Unread scraping: canais/DMs com badge de menes ou unread
    SEL_UNREAD_ROW = 'li[class*="channel"]:has([class*="unread"]), li[class*="privateChannels"]:has([class*="unread"])'
    SEL_UNREAD_NAME = 'a[aria-label], div[class*="name"]'
    SEL_UNREAD_PREVIEW = None
    SEL_UNREAD_COUNT = 'div[class*="numberBadge"]'


class DiscordJarvis(_DiscordWebBase, MessageBackend):  # type: ignore[misc]
    profile: ClassVar[Profile] = "jarvis"


class DiscordUser(_DiscordWebBase, MessageBackend):  # type: ignore[misc]
    profile: ClassVar[Profile] = "user"


@register_backend("discord", "jarvis")
def _dc_j() -> MessageBackend: return DiscordJarvis()


@register_backend("discord", "user")
def _dc_u() -> MessageBackend: return DiscordUser()
