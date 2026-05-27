"""Gmail (mail.google.com) — Chromium-only.

ATENÇÃO: NÃO usar Gmail API. Tudo via UI web. `dest` é o email destino.
Para `content`, formato esperado:
    "Assunto: <subj>\\n\\n<body>"
ou apenas o body (subject vazio).
"""
from __future__ import annotations

from typing import ClassVar

from ..base import MessageBackend, Platform, Profile, register_backend
from ..web_base import WebChatBackend


class _GmailWebBase(WebChatBackend):
    platform: ClassVar[Platform] = "gmail"
    URL_HOME = "https://mail.google.com/mail/u/0/#inbox"
    URL_CHAT_PATTERN = None  # composição é via botão "Escrever", não URL
    SEL_COMPOSER = 'div[aria-label="Corpo da mensagem"], div[aria-label="Message Body"]'
    SEL_SEND_BUTTON = 'div[aria-label^="Enviar"], div[aria-label^="Send"]'
    SEL_LOGGED_IN = 'div[role="navigation"] a[href*="#inbox"]'
    SEL_LOGIN_HINT = 'input[type="email"]'
    LOGIN_TIMEOUT_S = 180
    # Unread scraping: linhas "zE" são não-lidas na lista da inbox
    SEL_UNREAD_ROW = 'tr.zE'
    SEL_UNREAD_NAME = 'span.zF, span[email]'
    SEL_UNREAD_PREVIEW = 'span.y2, span.bog'
    SEL_UNREAD_COUNT = None

    async def open_chat(self, page, dest: str) -> None:
        from ..web_base import human_click, human_pause, human_type
        # Botão "Escrever"
        compose = page.locator('div[role="button"]:has-text("Escrever"), div[role="button"]:has-text("Compose")').first
        await compose.wait_for(state="visible", timeout=10_000)
        await human_click(compose)
        # Destinatário
        to_field = page.locator('input[aria-label^="Destinatário"], input[aria-label^="To"]').first
        await to_field.wait_for(state="visible", timeout=8_000)
        await human_type(to_field, dest)
        await page.keyboard.press("Tab")
        await human_pause(200, 500)

    async def _async_send(self, dest: str, content: str) -> "SendResult":  # type: ignore[override]
        # Extrai "Assunto: …\n\n…" se presente
        subject, body = "", content
        if content.lower().startswith("assunto:"):
            head, _, rest = content.partition("\n\n")
            subject = head.split(":", 1)[1].strip()
            body = rest

        await self._pool.start()
        ctx = await self._pool.get_context(self.platform, profile=self.profile)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        ok_login = await self._ensure_logged_in(page)
        from datetime import datetime
        from ..base import SendResult
        if not ok_login:
            return SendResult(
                ok=False, platform=self.platform, profile=self.profile,
                dest=dest, error="login_required",
            )

        await self.open_chat(page, dest)

        # Assunto
        if subject:
            from ..web_base import human_type
            subj = page.locator('input[aria-label="Assunto"], input[name="subjectbox"]').first
            await subj.wait_for(state="visible", timeout=5_000)
            await human_type(subj, subject)

        # Corpo
        from ..web_base import human_click, human_pause, human_type
        body_el = page.locator(self.SEL_COMPOSER).first
        await body_el.wait_for(state="visible", timeout=8_000)
        await human_click(body_el)
        await human_type(body_el, body)
        await human_pause(200, 500)

        # Enviar
        btn = page.locator(self.SEL_SEND_BUTTON).first
        await human_click(btn)
        ok_after = await self.post_send_check(page)
        return SendResult(
            ok=ok_after, platform=self.platform, profile=self.profile,
            dest=dest, sent_at=datetime.utcnow(),
            error=None if ok_after else "send_unverified",
        )


class GmailJarvis(_GmailWebBase, MessageBackend):  # type: ignore[misc]
    profile: ClassVar[Profile] = "jarvis"


class GmailUser(_GmailWebBase, MessageBackend):  # type: ignore[misc]
    profile: ClassVar[Profile] = "user"


@register_backend("gmail", "jarvis")
def _gm_j() -> MessageBackend: return GmailJarvis()


@register_backend("gmail", "user")
def _gm_u() -> MessageBackend: return GmailUser()
