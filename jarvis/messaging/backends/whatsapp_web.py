"""WhatsApp Web (web.whatsapp.com) — Chromium-only.

Login: QR code persiste na pasta do perfil (BrowserPool).
Envio por deep-link `wa.me`-style: https://web.whatsapp.com/send?phone=<E.164>
"""
from __future__ import annotations

from typing import ClassVar

from ..base import MessageBackend, Platform, Profile, register_backend
from ..web_base import WebChatBackend


class _WhatsAppWebBase(WebChatBackend):
    platform: ClassVar[Platform] = "whatsapp"
    URL_HOME = "https://web.whatsapp.com/"
    URL_CHAT_PATTERN = "https://web.whatsapp.com/send?phone={dest}"
    # composer principal (div contenteditable). Pode variar — fallback no SEL_ALT.
    SEL_COMPOSER = 'div[contenteditable="true"][data-tab="10"]'
    SEL_SEND_BUTTON = 'button[aria-label="Enviar"], button[aria-label="Send"]'
    # presença da barra de chats indica que está logado
    SEL_LOGGED_IN = 'div[aria-label="Lista de conversas"], div[aria-label="Chat list"]'
    SEL_LOGIN_HINT = 'canvas[aria-label="Scan me!"], canvas[aria-label="Scan this QR code"]'
    LOGIN_TIMEOUT_S = 120  # tempo p/ escanear QR
    # Unread scraping (Fase 2)
    SEL_UNREAD_ROW = 'div[role="listitem"]:has(span[aria-label*="unread" i]), div[role="listitem"]:has(span[aria-label*="não lida" i])'
    SEL_UNREAD_NAME = 'span[dir="auto"][title], span[dir="auto"]'
    SEL_UNREAD_PREVIEW = 'span[dir="ltr"], span[dir="auto"]:nth-of-type(2)'
    SEL_UNREAD_COUNT = 'span[aria-label*="unread" i], span[aria-label*="não lida" i]'


class WhatsAppWebJarvis(_WhatsAppWebBase, MessageBackend):  # type: ignore[misc]
    profile: ClassVar[Profile] = "jarvis"


class WhatsAppWebUser(_WhatsAppWebBase, MessageBackend):  # type: ignore[misc]
    profile: ClassVar[Profile] = "user"


@register_backend("whatsapp", "jarvis")
def _wa_j() -> MessageBackend: return WhatsAppWebJarvis()


@register_backend("whatsapp", "user")
def _wa_u() -> MessageBackend: return WhatsAppWebUser()
