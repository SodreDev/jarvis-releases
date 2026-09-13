"""Agendamento com debounce do hot-reload da UI (webview).

Motivo: JarvisApi.reload_ui chamava _reload_with_theme de forma síncrona, e o
load_html/load_url destruía o contexto JS enquanto o pywebview ainda ia
entregar o retorno da MESMA chamada — daí o erro recorrente no crash.log
"window.pywebview._returnValuesCallbacks.reload_ui.<id> is not a function".

Aqui reload_ui só PEDE um reload: retorna na hora e o reload roda depois, fora
da chamada da ponte, uma única vez mesmo com F5/Ctrl+R repetidos (debounce).
"""
from __future__ import annotations

import threading
from typing import Callable

DEFAULT_DEBOUNCE_MS = 300


class UiReloadScheduler:
    """Coalesce pedidos de reload numa janela de debounce e dispara 1 vez.

    - ``reload_fn(theme)`` é o efeito real (ex.: app._reload_with_theme).
    - ``request(theme)`` retorna imediatamente; o reload ocorre depois.
    - Vários ``request`` dentro de ``debounce_ms`` viram um só, com o último tema.
    """

    def __init__(
        self,
        reload_fn: Callable[[str], None],
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        timer_factory: Callable[..., "threading.Timer"] = threading.Timer,
    ):
        self._reload_fn = reload_fn
        self._debounce = debounce_ms / 1000.0
        self._timer_factory = timer_factory
        self._timer = None
        self._pending_theme = None
        self._lock = threading.Lock()

    def request(self, theme: str) -> None:
        """Pede um reload; não executa o reload_fn dentro desta chamada."""
        with self._lock:
            self._pending_theme = theme
            if self._timer is not None:
                self._timer.cancel()
            timer = self._timer_factory(self._debounce, self._fire)
            try:
                timer.daemon = True
            except Exception:
                pass
            self._timer = timer
            timer.start()

    def _fire(self) -> None:
        with self._lock:
            theme = self._pending_theme
            self._timer = None
            self._pending_theme = None
        self._reload_fn(theme)
