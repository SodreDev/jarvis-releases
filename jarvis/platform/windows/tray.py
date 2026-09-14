"""Tray no Windows (F2-02): cópia literal do pystray do _criar_tray_icon do main.py.

W1/W2:
- ``setup`` monta ``pystray.Menu``/``MenuItem`` na ordem dos itens (``default=True`` só
  no item padrão, ``Menu.SEPARATOR`` no separador) e ``pystray.Icon("JARVIS", imagem,
  título, menu)``; inicia ``icon.run`` numa thread daemon e deixa o ícone oculto;
- ``set_visible`` = ``icon.visible``; ``stop`` = ``icon.stop()``.
A imagem vem do main.py (``make_image``); a interceptação do X também fica lá.
``pystray`` pode ser injetado para os testes.
"""
from __future__ import annotations

import threading
from typing import Callable, Sequence

from ..common.base import BackendBase, Probe


class PystrayTray(BackendBase):
    name = "pystray"

    def __init__(self, ctx=None, *, pystray_mod=None):
        self.ctx = ctx
        self._pystray_mod = pystray_mod
        self._icon = None

    @classmethod
    def probe(cls, ctx) -> Probe:
        try:
            import pystray  # noqa: F401
        except Exception as e:
            return Probe(False, f"pystray indisponível: {e}")
        return Probe(True)

    def _pystray(self):
        if self._pystray_mod is not None:
            return self._pystray_mod
        import pystray

        return pystray

    def setup(self, title: str, make_image: Callable, items: Sequence) -> bool:
        pystray = self._pystray()
        img = make_image()

        entradas = []
        for item in items:
            if item.separator:
                entradas.append(pystray.Menu.SEPARATOR)
            elif item.default:
                entradas.append(pystray.MenuItem(item.label, item.callback, default=True))
            else:
                entradas.append(pystray.MenuItem(item.label, item.callback))
        menu = pystray.Menu(*entradas)

        self._icon = pystray.Icon("JARVIS", img, title, menu)

        # Inicia o tray em background (não mostra até minimizar)
        threading.Thread(target=self._icon.run, daemon=True).start()
        # Começa oculto
        self._icon.visible = False
        return True

    def set_visible(self, visible: bool) -> None:
        if self._icon is not None:
            self._icon.visible = visible

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
