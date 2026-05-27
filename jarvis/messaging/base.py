"""Contratos comuns para todos os backends de mensageria."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable, Literal, Protocol, runtime_checkable

Platform = Literal["whatsapp", "instagram", "discord", "telegram", "gmail"]
Profile = Literal["jarvis", "user"]


@dataclass
class Contact:
    id: str
    name: str
    platform: Platform
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    id: str
    platform: Platform
    profile: Profile
    sender: str
    content: str
    timestamp: datetime
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SendResult:
    ok: bool
    platform: Platform
    profile: Profile
    dest: str
    message_id: str | None = None
    error: str | None = None
    sent_at: datetime | None = None


@runtime_checkable
class MessageBackend(Protocol):
    """Protocolo único para enviar/ler/contatos em qualquer plataforma."""

    platform: Platform
    profile: Profile

    def send(self, dest: str, content: str) -> SendResult: ...
    def read_inbox(self, since: datetime | None = None) -> list[Message]: ...
    def list_contacts(self) -> list[Contact]: ...
    def reply(self, msg_id: str, content: str) -> SendResult: ...
    def is_available(self) -> bool: ...


# -------- registry de backends --------

_BACKENDS: dict[tuple[Platform, Profile], Callable[[], MessageBackend]] = {}


def register_backend(platform: Platform, profile: Profile):
    """Decorator: registra uma fábrica de backend para (plataforma, perfil).

    A fábrica é chamada sob demanda — `import` pesado fica lazy.
    """

    def deco(factory: Callable[[], MessageBackend]):
        _BACKENDS[(platform, profile)] = factory
        return factory

    return deco


def iter_backends() -> Iterable[tuple[Platform, Profile]]:
    return list(_BACKENDS.keys())


def get_backend(platform: Platform, profile: Profile) -> MessageBackend | None:
    factory = _BACKENDS.get((platform, profile))
    return factory() if factory else None


__all__ = [
    "Platform",
    "Profile",
    "Contact",
    "Message",
    "SendResult",
    "MessageBackend",
    "register_backend",
    "iter_backends",
    "get_backend",
]
