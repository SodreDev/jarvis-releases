"""Clipboard no Windows (F2-04): o comportamento de hoje atrás de Cap.CLIPBOARD.

W1:
- ``get_text``/``set_text`` = corpo literal do ``get_clipboard``/``set_clipboard``
  de comandos/system_ctrl.py (pyperclip). O try/except e as mensagens continuam
  no call site: aqui a exceção PROPAGA.
- ``watch`` = loop literal do ``_monitor_loop`` (0,8 s), lendo pelo
  ``_get_clipboard_text`` de comandos/clipboard_hist_ctrl.py, que usa o WinDLL
  PRIVADO da F1-12 (nunca ctypes.windll). As regras do histórico (não repetir o
  último, mais de 1 caractere, limite) ficam no ``on_change`` de quem chama.
pyperclip, a leitura e o sleep podem ser injetados para os testes.
"""
from __future__ import annotations

import time

from ..common.base import BackendBase


class WindowsClipboard(BackendBase):
    name = "windows.clipboard"
    can_watch = True

    def __init__(self, ctx=None, *, pyperclip_mod=None, get_text_fn=None, sleep_fn=None):
        self.ctx = ctx
        self._pyperclip_mod = pyperclip_mod
        self._get_text_fn = get_text_fn
        self._sleep_fn = sleep_fn

    def _pyperclip(self):
        if self._pyperclip_mod is not None:
            return self._pyperclip_mod
        import pyperclip

        return pyperclip

    def get_text(self) -> str:
        return self._pyperclip().paste() or ""

    def set_text(self, text: str) -> bool:
        self._pyperclip().copy(text)
        return True

    def watch(self, on_change, stop) -> bool:
        get_text = self._get_text_fn
        if get_text is None:
            from comandos.clipboard_hist_ctrl import _get_clipboard_text as get_text
        sleep = self._sleep_fn or time.sleep
        while not stop.is_set():
            try:
                txt = get_text()
                if txt:
                    on_change(txt)
            except Exception:
                pass
            sleep(0.8)
        return True
