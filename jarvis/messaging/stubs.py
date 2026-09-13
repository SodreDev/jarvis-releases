"""Compat shim — re-exporta os backends Chromium concretos.

Antes desta sprint, este arquivo continha stubs em-branco que retornavam
NotImplementedError. Agora ele simplesmente importa os backends reais
(que ainda podem precisar de login manual na primeira execução) — todos
em `jarvis.messaging.backends.*`.

NÃO USE APIS OFICIAIS aqui. Veja `web_base.py` para a regra.
"""
from __future__ import annotations

# Importar registra os backends via @register_backend
from .backends import whatsapp_web as _wa     # noqa: F401
from .backends import instagram_web as _ig    # noqa: F401
from .backends import discord_web as _dc      # noqa: F401
from .backends import telegram_web as _tg     # noqa: F401
from .backends import gmail_web as _gm        # noqa: F401

# Aliases p/ compat com código antigo que importava daqui
from .backends.whatsapp_web import WhatsAppWebJarvis as WhatsAppWebJarvisBackend  # noqa: F401
from .backends.whatsapp_web import WhatsAppWebUser as WhatsAppWebUserBackend      # noqa: F401
from .backends.instagram_web import InstagramJarvis as InstagramJarvisBackend     # noqa: F401
from .backends.instagram_web import InstagramUser as InstagramUserBackend         # noqa: F401
from .backends.discord_web import DiscordJarvis as DiscordBotBackend              # noqa: F401
from .backends.telegram_web import TelegramJarvis as TelegramBotBackend           # noqa: F401
from .backends.gmail_web import GmailUser as GmailUserBackend                     # noqa: F401
