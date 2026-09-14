"""Session no Windows (F2-07): cópia literal do que main.py e core/win_locale.py faziam.

W1/W2:
- ``idle_seconds`` = corpo literal do ``_idle_seconds`` do main.py
  (GetLastInputInfo − GetTickCount). Qualquer exceção devolve 0.0: no Windows
  nunca é None. ``ctypes`` pode ser injetado (``ctypes_mod``) para os testes.
- ``locale``/``timezone_name`` delegam para ``core.win_locale`` (ramo Windows literal).
"""
from __future__ import annotations

from ..common.base import BackendBase


class WindowsSession(BackendBase):
    name = "windows.session"

    def __init__(self, ctx=None, *, ctypes_mod=None):
        self.ctx = ctx
        self._ctypes_mod = ctypes_mod

    def idle_seconds(self) -> float:
        """
        Retorna quantos segundos o sistema está sem entrada de teclado ou mouse.
        Usa GetLastInputInfo (Win32) via ctypes puro — sem dependências extras.
        """
        try:
            ctypes = self._ctypes_mod
            if ctypes is None:
                import ctypes
                import ctypes.wintypes

            class _LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            lii = _LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(lii)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
            millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return max(0.0, millis / 1000.0)
        except Exception:
            return 0.0

    def locale(self) -> str:
        from core.win_locale import get_locale

        return get_locale()

    def timezone_name(self) -> str:
        from core.win_locale import get_timezone_name

        return get_timezone_name()
