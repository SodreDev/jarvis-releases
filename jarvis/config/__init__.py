"""Configuração tipada do JARVIS.

API pública:

    from jarvis.config import settings, reload

    if settings.features.spotify:
        ...

`settings` é um singleton carregado lazy. A primeira leitura tenta:

1. `%APPDATA%/JARVIS/config.user.toml` (Windows) ou `~/.config/jarvis/config.user.toml`.
2. `./config.user.toml` na raiz do repo (override de dev).
3. Defaults internos (`jarvis.config.defaults`).

Para recarregar após alteração: `from jarvis.config import reload; reload()`.
"""
from __future__ import annotations

from .loader import get_settings, reload_settings

# objeto principal (lazy proxy via função para evitar import circular)
def _proxy_settings():  # pragma: no cover - simple shim
    return get_settings()


class _SettingsProxy:
    """Proxy que sempre delega para o singleton atual."""

    def __getattr__(self, name):
        return getattr(get_settings(), name)

    def __repr__(self) -> str:  # pragma: no cover
        return repr(get_settings())


settings = _SettingsProxy()
reload = reload_settings

__all__ = ["settings", "reload", "get_settings", "reload_settings"]
