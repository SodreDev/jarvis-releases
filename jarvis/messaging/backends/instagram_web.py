"""Instagram DM (instagram.com/direct) — Chromium-only.

ATENÇÃO: NÃO usar instagrapi. Tudo via UI web simulando humano,
preservando sessão (cookies) na pasta do perfil.
"""
from __future__ import annotations

from typing import ClassVar

from ..base import MessageBackend, Platform, Profile, register_backend
from ..web_base import WebChatBackend


class _InstagramWebBase(WebChatBackend):
    platform: ClassVar[Platform] = "instagram"
    URL_HOME = "https://www.instagram.com/direct/inbox/"
    # IG não tem deep-link estável p/ DM por username sem 't/' (que precisa do ID).
    # Sprint 3+: implementar open_chat via busca interna.
    URL_CHAT_PATTERN = None
    SEL_COMPOSER = 'div[role="textbox"][contenteditable="true"]'
    SEL_SEND_BUTTON = 'div[role="button"]:has-text("Enviar"), div[role="button"]:has-text("Send")'
    SEL_LOGGED_IN = 'a[href="/direct/inbox/"]'
    SEL_LOGIN_HINT = 'input[name="username"]'
    LOGIN_TIMEOUT_S = 120
    # Unread scraping (Fase 2) — linhas com indicador de noão lida (bolinha azul)
    SEL_UNREAD_ROW = 'div[role="listitem"]:has(div[aria-label*="Unread" i]), div[role="listitem"]:has(div[aria-label*="Não lida" i])'
    SEL_UNREAD_NAME = 'span[dir="auto"]'
    SEL_UNREAD_PREVIEW = 'span:not([dir]):not([class*="icon"])'
    SEL_UNREAD_COUNT = None  # IG mostra só a bolinha, não número

    async def open_chat(self, page, dest: str) -> None:
        """Abre DM via busca por username dentro da UI."""
        from ..web_base import human_click, human_pause, human_type
        # Botão "Novo" da caixa de entrada
        await human_pause(400, 800)
        new_msg = page.locator('svg[aria-label="Nova mensagem"], svg[aria-label="New message"]').first
        await new_msg.wait_for(state="visible", timeout=10_000)
        await human_click(new_msg)
        # campo "Para:"
        to_input = page.locator('input[placeholder="Pesquisar..."], input[placeholder="Search..."]').first
        await to_input.wait_for(state="visible", timeout=8_000)
        await human_type(to_input, dest)
        # primeiro resultado
        await human_pause(800, 1400)
        first = page.locator('div[role="dialog"] div[role="button"]').first
        await human_click(first)
        # Chat / Conversar
        chat_btn = page.locator('button:has-text("Conversar"), button:has-text("Chat")').first
        await chat_btn.wait_for(state="visible", timeout=8_000)
        await human_click(chat_btn)
        await human_pause(800, 1500)


class InstagramJarvis(_InstagramWebBase, MessageBackend):  # type: ignore[misc]
    profile: ClassVar[Profile] = "jarvis"


class InstagramUser(_InstagramWebBase, MessageBackend):  # type: ignore[misc]
    profile: ClassVar[Profile] = "user"


@register_backend("instagram", "jarvis")
def _ig_j() -> MessageBackend: return InstagramJarvis()


@register_backend("instagram", "user")
def _ig_u() -> MessageBackend: return InstagramUser()
