"""
PyWebView application — cria e gerencia a janela principal da interface gestual.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import webview

from gesture_interface.config import UI_BG_COLOR, UI_HEIGHT, UI_TITLE, UI_WIDTH
from gesture_interface.ui.api import GestureAPI

if TYPE_CHECKING:
    from gesture_interface.main import GestureSystem

_TEMPLATES = Path(__file__).resolve().parent / "templates"


class GestureUI:
    """Encapsula a janela PyWebView."""

    def __init__(self, api: GestureAPI) -> None:
        self._api = api
        self._window: webview.Window | None = None

    def start(self, system: GestureSystem) -> None:
        """Inicia a janela PyWebView (blocking — chamar em thread ou como último passo)."""
        self._api.bind(system)
        index_path = str(_TEMPLATES / "index.html")

        self._window = webview.create_window(
            UI_TITLE,
            url=index_path,
            js_api=self._api,
            width=UI_WIDTH,
            height=UI_HEIGHT,
            background_color=UI_BG_COLOR,
            resizable=True,
            min_size=(800, 600),
        )
        webview.start(debug=False)

    def start_threaded(self, system: GestureSystem) -> threading.Thread:
        """Inicia a UI em thread separada."""
        t = threading.Thread(target=self.start, args=(system,), daemon=True, name="gesture-ui")
        t.start()
        return t

    def evaluate_js(self, script: str) -> None:
        if self._window:
            try:
                self._window.evaluate_js(script)
            except Exception:
                pass

    @property
    def window(self) -> webview.Window | None:
        return self._window
