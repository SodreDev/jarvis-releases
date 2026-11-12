"""As cinco redes que o Jarvis sabe monitorar (ADR-0060), com o endereço e os hosts de cada uma.

Os hosts são a fronteira: o content script `extensao/social.js` só observa página destes hosts,
e o host nativo só aceita evento `social` de uma destas redes. Os seletores do DOM ficam no
script, um bloco por rede; aqui fica só o que o Python precisa."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class Rede:
    id: str
    nome: str
    endereco: str
    """Onde a aba de monitoramento abre (a caixa de mensagens, quando a rede tem uma)."""
    hosts: tuple[str, ...]
    responde: bool = False
    """Só o WhatsApp tem envio (fatia D). As outras são só leitura."""


REDES: Final[tuple[Rede, ...]] = (
    Rede(
        "whatsapp",
        "WhatsApp",
        "https://web.whatsapp.com/",
        ("web.whatsapp.com",),
        responde=True,
    ),
    Rede(
        "instagram",
        "Instagram",
        "https://www.instagram.com/direct/inbox/",
        ("www.instagram.com", "instagram.com"),
    ),
    Rede(
        "facebook",
        "Facebook",
        "https://www.facebook.com/messages/",
        ("www.facebook.com", "facebook.com", "web.facebook.com"),
    ),
    Rede(
        "tiktok",
        "TikTok",
        "https://www.tiktok.com/messages",
        ("www.tiktok.com", "tiktok.com"),
    ),
    Rede(
        "discord",
        "Discord",
        "https://discord.com/channels/@me",
        ("discord.com", "ptb.discord.com", "canary.discord.com"),
    ),
)
IDS: Final[tuple[str, ...]] = tuple(r.id for r in REDES)
_POR_ID: Final = {r.id: r for r in REDES}


def rede(identificador: str) -> Rede:
    """A rede pelo id; `KeyError` com a lista das que existem."""
    try:
        return _POR_ID[identificador]
    except KeyError:
        raise KeyError(f"rede desconhecida {identificador!r}: só {', '.join(IDS)}") from None


def rede_da_url(url: str) -> Rede | None:
    """A rede de um endereço http(s), pelo host exato (sem subdomínio curinga)."""
    partes = urlsplit(url)
    if partes.scheme != "https":
        return None
    host = (partes.hostname or "").lower()
    return next((r for r in REDES if host in r.hosts), None)


__all__ = ["IDS", "REDES", "Rede", "rede", "rede_da_url"]
