"""Backends Chromium concretos (sem APIs oficiais).

Cada arquivo encapsula seletores/URLs/hooks de UMA plataforma web.
Tudo aqui passa pelo `WebChatBackend` → `BrowserPool` → comportamento humano.

Importa cada backend para que os decoradores `@register_backend` rodem
e o roteador encontre-os. Telegram é stub (usuário não usa) e Gmail web
não é importado aqui — Gmail usa a API oficial em outro caminho.
"""
from __future__ import annotations as _annotations

# Importações eager — registram os backends no router.
# Falhas silenciosas: se o módulo da plataforma quebrar (selector inválido,
# import faltando), não impede o resto de carregar.
def _safe_import(modname: str) -> None:
    try:
        __import__(f"{__name__}.{modname}", fromlist=[modname])
    except Exception as _e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).debug(
            "backend %s não pôde ser registrado: %s", modname, _e
        )

for _m in ("whatsapp_web", "instagram_web", "discord_web"):
    _safe_import(_m)
del _safe_import, _m
