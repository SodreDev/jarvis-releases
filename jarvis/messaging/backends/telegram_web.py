"""Telegram Web (web.telegram.org/k/) — Chromium-only.

ATENÇÃO: NÃO usar bot API nem python-telegram-bot. Tudo via UI web.
`dest` pode ser '@username' ou número telefônico (formato +55…).
"""
from __future__ import annotations

from typing import ClassVar

from ..base import MessageBackend, Platform, Profile, register_backend
from ..web_base import WebChatBackend


class _TelegramWebBase(WebChatBackend):
    platform: ClassVar[Platform] = "telegram"
    URL_HOME = "https://web.telegram.org/k/"
    # https://web.telegram.org/k/#@username também funciona
    URL_CHAT_PATTERN = "https://web.telegram.org/k/#{dest}"
    SEL_COMPOSER = 'div.input-message-input[contenteditable="true"]'
    SEL_SEND_BUTTON = 'button.btn-send'
    SEL_LOGGED_IN = 'div.chatlist, div#chatlist'
    SEL_LOGIN_HINT = 'input.input-field-input'  # tela de telefone/código
    LOGIN_TIMEOUT_S = 180  # SMS pode demorar
    # Unread scraping
    SEL_UNREAD_ROW = 'ul.chatlist li.chat-list-item:has(.badge-unread), ul#chatlist li:has(.badge-unread)'
    SEL_UNREAD_NAME = '.user-title, .peer-title'
    SEL_UNREAD_PREVIEW = '.user-last-message, .last-message'
    SEL_UNREAD_COUNT = '.badge-unread'
    UNREAD_ID_ATTR = 'data-peer-id'


class TelegramJarvis(_TelegramWebBase, MessageBackend):  # type: ignore[misc]
    profile: ClassVar[Profile] = "jarvis"


class TelegramUser(_TelegramWebBase, MessageBackend):  # type: ignore[misc]
    profile: ClassVar[Profile] = "user"


@register_backend("telegram", "jarvis")
def _tg_j() -> MessageBackend: return TelegramJarvis()


@register_backend("telegram", "user")
def _tg_u() -> MessageBackend: return TelegramUser()
