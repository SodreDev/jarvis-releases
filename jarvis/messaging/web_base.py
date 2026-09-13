"""WebChatBackend — base 100% Chromium para qualquer mensageiro web.

Regra de ouro do projeto (ver planning/roadmap/PRINCIPIOS.md):
  • NUNCA usar APIs oficiais nem libs do tipo `instagrapi`, `discord.py`,
    `python-telegram-bot`, `pywhatkit`, etc.
  • Tudo via Chromium (Playwright) simulando humano para evitar ban e detecção
    de automação.
  • Janela off-screen e operações via API do Playwright (page.click/fill/keyboard),
    NUNCA via mouse/teclado do SO (pyautogui), porque o usuário pode estar
    digitando ao mesmo tempo.

Cada subclasse define:
  - URL_HOME           : URL inicial (ex.: https://web.whatsapp.com).
  - URL_CHAT_PATTERN   : URL deeplink p/ um chat específico (formato {dest}),
                         ou None se a navegação for via UI.
  - SEL_COMPOSER       : seletor do campo de digitação.
  - SEL_SEND_BUTTON    : seletor do botão de enviar (None se basta Enter).
  - SEL_LOGGED_IN      : seletor presente apenas quando há sessão ativa.
  - SEL_LOGIN_HINT     : seletor que indica "precisa logar" (QR, formulário…).

E pode sobrescrever os hooks:
  - async def open_chat(page, dest): navega até o chat (default usa URL_CHAT_PATTERN).
  - async def post_send_check(page): valida que a msg saiu.
  - async def login_flow(page): orienta o usuário a logar (default: timeout).
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, ClassVar

from ..browser import get_pool
from ..browser.human import human_click, human_pause, human_type
from .base import Contact, Message, MessageBackend, Platform, Profile, SendResult


class WebChatBackend(MessageBackend):
    """Base abstrata para backends de mensageria web (Chromium-only)."""

    # --- Subclasses preenchem ---
    platform: ClassVar[Platform]  # type: ignore[misc]
    profile: ClassVar[Profile]    # type: ignore[misc]

    URL_HOME: ClassVar[str] = ""
    URL_CHAT_PATTERN: ClassVar[str | None] = None  # ex.: "https://web.whatsapp.com/send?phone={dest}"
    SEL_COMPOSER: ClassVar[str] = ""
    SEL_SEND_BUTTON: ClassVar[str | None] = None
    SEL_LOGGED_IN: ClassVar[str | None] = None
    SEL_LOGIN_HINT: ClassVar[str | None] = None

    # --- Scraping de unreads (Fase 2). Subclasses sobrescrevem. ---
    # Seletor que retorna TODAS as linhas de chat com mensagens não lidas.
    SEL_UNREAD_ROW: ClassVar[str | None] = None
    # Dentro da row: nome do chat (texto).
    SEL_UNREAD_NAME: ClassVar[str | None] = None
    # Dentro da row: preview da última mensagem.
    SEL_UNREAD_PREVIEW: ClassVar[str | None] = None
    # Dentro da row: badge com número de mensagens não lidas (texto -> int).
    SEL_UNREAD_COUNT: ClassVar[str | None] = None
    # Identificador estável da row (atributo). Se None, usa o nome.
    UNREAD_ID_ATTR: ClassVar[str | None] = None

    LOGIN_TIMEOUT_S: ClassVar[int] = 90  # tempo p/ usuário escanear QR / fazer login

    # ---------- Lifecycle ----------
    def __init__(self) -> None:
        self._pool = get_pool()

    def is_available(self) -> bool:
        """Disponível se já existe pasta de perfil com sessão (não força login)."""
        from ..browser.profiles import profile_dir
        d = profile_dir(self.profile, self.platform)
        # sessão "minimamente" salva: existe arquivo Cookies em algum dos
        # caminhos conhecidos (Chromium 96+ usa Default/Network/Cookies).
        return (
            (d / "Default" / "Network" / "Cookies").exists()
            or (d / "Default" / "Cookies").exists()
            or (d / "Cookies").exists()
        )

    # ---------- API síncrona (router) ----------
    def send(self, dest: str, content: str) -> SendResult:
        from ..browser.pool import run_sync as _run_sync
        try:
            return _run_sync(self._async_send(dest, content))
        except Exception as e:                                       # noqa: BLE001
            return SendResult(
                ok=False, platform=self.platform, profile=self.profile,
                dest=dest, error=f"{type(e).__name__}: {e}",
            )

    def read_inbox(self, since: datetime | None = None) -> list[Message]:
        """Scraping (síncrono) das conversas com mensagens não lidas.

        Cada linha vira um Message sintético: id = "<platform>:<profile>:<chat_id>"
        e raw inclui `unread_count`. Subclasses costumam apenas definir os SEL_*.
        """
        from ..browser.pool import run_sync as _run_sync
        try:
            return _run_sync(self._async_read_unread())
        except Exception as e:                                       # noqa: BLE001
            import logging
            logging.getLogger(__name__).debug(
                "read_inbox falhou %s/%s: %s", self.platform, self.profile, e
            )
            return []

    def list_contacts(self) -> list[Contact]:
        # Sprint 3+: scraping da agenda.
        return []

    def reply(self, msg_id: str, content: str) -> SendResult:
        # Sprint 3+: requer mapeamento msg_id→chat.
        return SendResult(
            ok=False, platform=self.platform, profile=self.profile,
            dest=msg_id, error="reply ainda não implementado",
        )

    # ---------- Núcleo async ----------
    async def _async_send(self, dest: str, content: str) -> SendResult:
        await self._pool.start()
        ctx = await self._pool.get_context(self.platform, profile=self.profile)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # 1) Garantir login
        ok_login = await self._ensure_logged_in(page)
        if not ok_login:
            return SendResult(
                ok=False, platform=self.platform, profile=self.profile,
                dest=dest, error="login_required",
            )

        # 2) Abrir o chat
        await self.open_chat(page, dest)

        # 3) Localizar composer e enviar
        await human_pause(200, 500)
        composer = page.locator(self.SEL_COMPOSER).first
        await composer.wait_for(state="visible", timeout=15_000)
        await human_click(composer)
        await human_type(composer, content)

        if self.SEL_SEND_BUTTON:
            btn = page.locator(self.SEL_SEND_BUTTON).first
            await human_pause(120, 320)
            await human_click(btn)
        else:
            await human_pause(120, 320)
            await page.keyboard.press("Enter")

        # 4) Pós-validação
        ok_after = await self.post_send_check(page)
        return SendResult(
            ok=ok_after, platform=self.platform, profile=self.profile,
            dest=dest, sent_at=datetime.utcnow(),
            error=None if ok_after else "send_unverified",
        )

    async def _ensure_logged_in(self, page) -> bool:
        if not page.url.startswith(self.URL_HOME):
            await page.goto(self.URL_HOME, wait_until="domcontentloaded")
        await human_pause(800, 1400)

        if self.SEL_LOGGED_IN:
            try:
                await page.locator(self.SEL_LOGGED_IN).first.wait_for(
                    state="visible", timeout=5_000
                )
                return True
            except Exception:                                      # noqa: BLE001
                pass

        # precisa logar: roda hook de login (subclasse pode customizar)
        return await self.login_flow(page)

    # ---------- Hooks customizáveis ----------
    async def open_chat(self, page, dest: str) -> None:
        """Default: usa URL_CHAT_PATTERN se houver, senão tenta busca interna."""
        if self.URL_CHAT_PATTERN:
            url = self.URL_CHAT_PATTERN.format(dest=dest)
            await page.goto(url, wait_until="domcontentloaded")
            await human_pause(900, 1600)
            return
        raise NotImplementedError(
            f"{type(self).__name__}: open_chat() não implementado "
            "(defina URL_CHAT_PATTERN ou sobrescreva o método)."
        )

    async def login_flow(self, page) -> bool:  # noqa: ARG002
        """Default: aguarda manualmente o usuário logar (escanear QR, digitar senha)."""
        if not self.SEL_LOGGED_IN:
            return False
        try:
            await page.locator(self.SEL_LOGGED_IN).first.wait_for(
                state="visible", timeout=self.LOGIN_TIMEOUT_S * 1000
            )
            return True
        except Exception:                                          # noqa: BLE001
            return False

    async def post_send_check(self, page) -> bool:  # noqa: ARG002
        """Default: pequena pausa após o envio. Subclasses podem checar 'check-mark'."""
        await human_pause(400, 900)
        return True

    # ---------- Scraping de unreads (Fase 2 / Inbox Watcher) ----------
    async def _async_read_unread(self) -> list[Message]:
        """Implementação default: vai pro URL_HOME, lê linhas via SEL_UNREAD_ROW.

        Subclasses costumam apenas declarar os SEL_UNREAD_* — só sobrescrevem este
        método se a estrutura da página exigir lógica especial.
        """
        if not self.SEL_UNREAD_ROW:
            return []
        await self._pool.start()
        ctx = await self._pool.get_context(self.platform, profile=self.profile)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        try:
            if not page.url.startswith(self.URL_HOME):
                await page.goto(self.URL_HOME, wait_until="domcontentloaded", timeout=20_000)
        except Exception:
            return []

        await human_pause(400, 900)
        if self.SEL_LOGGED_IN:
            try:
                await page.locator(self.SEL_LOGGED_IN).first.wait_for(
                    state="visible", timeout=4_000
                )
            except Exception:
                return []

        try:
            rows = await page.locator(self.SEL_UNREAD_ROW).all()
        except Exception:
            return []

        out: list[Message] = []
        now = datetime.utcnow()
        for idx, row in enumerate(rows[:50]):
            try:
                name = ""
                if self.SEL_UNREAD_NAME:
                    try:
                        name = (await row.locator(self.SEL_UNREAD_NAME).first.text_content(timeout=1_500)) or ""
                    except Exception:
                        name = ""
                name = (name or "").strip()

                preview = ""
                if self.SEL_UNREAD_PREVIEW:
                    try:
                        preview = (await row.locator(self.SEL_UNREAD_PREVIEW).first.text_content(timeout=1_500)) or ""
                    except Exception:
                        preview = ""
                preview = (preview or "").strip()

                count = 1
                if self.SEL_UNREAD_COUNT:
                    try:
                        ctxt = (await row.locator(self.SEL_UNREAD_COUNT).first.text_content(timeout=800)) or ""
                        ctxt = ctxt.strip()
                        if ctxt.isdigit():
                            count = int(ctxt)
                    except Exception:
                        pass

                chat_id = ""
                if self.UNREAD_ID_ATTR:
                    try:
                        chat_id = (await row.get_attribute(self.UNREAD_ID_ATTR, timeout=800)) or ""
                    except Exception:
                        chat_id = ""
                if not chat_id:
                    chat_id = name or f"row{idx}"

                if not name and not preview:
                    continue

                msg_id = f"{self.platform}:{self.profile}:{chat_id}"
                out.append(Message(
                    id=msg_id,
                    platform=self.platform,
                    profile=self.profile,
                    sender=name or chat_id,
                    content=preview,
                    timestamp=now,
                    raw={"unread_count": count, "chat_id": chat_id},
                ))
            except Exception:
                continue
        return out


__all__ = ["WebChatBackend"]
