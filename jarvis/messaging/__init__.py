"""Mensageria abstrata — protocolo único acima de WhatsApp, Discord, IG, etc."""

from .base import (
    MessageBackend,
    Message,
    SendResult,
    Contact,
    Platform,
    Profile,
    register_backend,
    iter_backends,
    get_backend,
)
from .router import MessagingRouter, AmbiguityError, get_router

# Eager-import dos backends Chromium para registrá-los via decorator.
# (Telegram fica de fora — usuário não usa. Gmail usa API oficial.)
from . import backends  # noqa: F401

__all__ = [
    "MessageBackend",
    "Message",
    "SendResult",
    "Contact",
    "Platform",
    "Profile",
    "register_backend",
    "iter_backends",
    "get_backend",
    "MessagingRouter",
    "AmbiguityError",
    "get_router",
]
