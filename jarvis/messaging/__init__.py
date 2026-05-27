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
