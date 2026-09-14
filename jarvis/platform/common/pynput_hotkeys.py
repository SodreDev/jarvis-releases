"""Hotkeys com pynput (win32 e linux-x11), F2-01: cópia literal do que o main.py fazia.

- ``listen_keys`` = ``keyboard.Listener(on_press=..., on_release=...)`` + ``.start()``
  e devolve True; o Shift+G continua sendo detectado em ``_on_key_press``/
  ``_on_key_release`` do main.py.
- ``bind`` = ``GlobalHotKeys({combo: handler})``, parando o registro anterior, com o
  mesmo ``info``/``warn`` do logger "JARVIS". O aviso de ação desconhecida continua
  no main.py.
- Sonda: ``pynput.keyboard`` e ``GlobalHotKeys`` importam.
``keyboard_mod``, ``global_hotkeys_cls`` e ``log`` podem ser injetados nos testes.
"""
from __future__ import annotations

from typing import Dict, Sequence

from .base import BackendBase, Probe


class PynputHotkeys(BackendBase):
    name = "pynput"

    def __init__(self, ctx=None, *, keyboard_mod=None, global_hotkeys_cls=None, log=None):
        self.ctx = ctx
        self._keyboard = keyboard_mod
        self._global_hotkeys_cls = global_hotkeys_cls
        self._log = log
        self._listener = None
        self._hotkeys_listener = None

    @classmethod
    def probe(cls, ctx) -> Probe:
        try:
            from pynput import keyboard  # noqa: F401
            from pynput.keyboard import GlobalHotKeys  # noqa: F401
        except Exception as e:
            return Probe(False, f"pynput indisponível: {e}")
        return Probe(True)

    def _logger(self):
        if self._log is None:
            from comandos.logger_ctrl import get_logger

            self._log = get_logger("JARVIS")
        return self._log

    def listen_keys(self, on_press, on_release) -> bool:
        keyboard = self._keyboard
        if keyboard is None:
            from pynput import keyboard
        self._listener = keyboard.Listener(
            on_press=on_press,
            on_release=on_release,
        )
        self._listener.start()
        return True

    def bind(self, bindings: Sequence) -> Dict[str, str]:
        GlobalHotKeys = self._global_hotkeys_cls
        if GlobalHotKeys is None:
            from pynput.keyboard import GlobalHotKeys
        handlers = {b.trigger: b.on_press for b in bindings}
        try:
            # Para listener anterior se existir
            old = self._hotkeys_listener
            if old is not None:
                try: old.stop()
                except Exception: pass
            self._hotkeys_listener = GlobalHotKeys(handlers)
            self._hotkeys_listener.start()
            self._logger().info(f"HOTKEYS: {len(handlers)} atalho(s) registrado(s): {', '.join(handlers)}")
        except Exception as e:
            self._logger().warn(f"HOTKEYS: Falha ao registrar atalhos: {e}", exc_info=e)
        return {b.id: b.trigger for b in bindings}

    def stop(self) -> None:
        for listener in (self._listener, self._hotkeys_listener):
            if listener is not None:
                try:
                    listener.stop()
                except Exception:
                    pass
        self._listener = self._hotkeys_listener = None
