"""Motor de webview no Windows: WebView2 (Edge Chromium) via pywebview.

No Windows nada precisa ser preparado (o WEBVIEW2_ADDITIONAL_FLAGS continua
sendo definido no main.py); este backend é um no-op total, para o boot poder
montar _wv_start_kwargs de forma uniforme entre plataformas.
"""
from __future__ import annotations

from ..common.base import BackendBase


class EdgeChromiumEngine(BackendBase):
    name = "windows.webview2"

    def __init__(self, ctx=None):
        self.ctx = ctx

    def prepare_env(self, environ) -> None:
        # no-op: o WebView2 já funciona sem preparação de ambiente.
        return None

    def start_kwargs(self) -> dict:
        return {}

    def sandbox_state(self) -> str:
        return "n/a"
