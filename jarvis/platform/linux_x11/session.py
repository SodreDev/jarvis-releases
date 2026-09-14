"""Idle no X11 via extensão MIT-SCREEN-SAVER (F2-07).

``XssSession``: ``XScreenSaverQueryInfo(dpy, root, info).idle`` (ms) com ctypes em
``libXss.so.1`` + ``libX11.so.6``. Sonda: as libs carregam e o ``DISPLAY`` abre.
A conexão X fica aberta com o objeto (lock: Xlib não é thread-safe). locale e
fuso vêm de ``XdgSession``. O carregador de lib é injetável para os testes.
"""
from __future__ import annotations

import ctypes
import threading
from typing import Optional

from ..common.base import Probe
from ..linux.session import XdgSession


class _XScreenSaverInfo(ctypes.Structure):
    _fields_ = [
        ("window", ctypes.c_ulong),
        ("state", ctypes.c_int),
        ("kind", ctypes.c_int),
        ("til_or_since", ctypes.c_ulong),
        ("idle", ctypes.c_ulong),
        ("eventMask", ctypes.c_ulong),
    ]


class XssSession(XdgSession):
    name = "linux_x11.xss"

    _loader = None  # padrão: ctypes.CDLL

    def __init__(self, ctx=None, *, loader=None, **kwargs):
        super().__init__(ctx, **kwargs)
        self._load = loader or type(self)._loader or ctypes.CDLL
        self._lock = threading.Lock()
        self._x11 = self._xss = self._dpy = None

    @classmethod
    def probe(cls, ctx) -> Probe:
        inst = cls(ctx)
        try:
            with inst._lock:
                if inst._abrir_locked():
                    return Probe(True)
            return Probe(False, "XOpenDisplay falhou (DISPLAY)")
        except OSError as e:
            return Probe(False, f"libXss/libX11 indisponível: {e}")
        finally:
            inst.close()

    def _abrir_locked(self) -> bool:
        if self._dpy:
            return True
        x11 = self._load("libX11.so.6")
        xss = self._load("libXss.so.1")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XFree.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(_XScreenSaverInfo)
        xss.XScreenSaverQueryInfo.restype = ctypes.c_int
        xss.XScreenSaverQueryInfo.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_XScreenSaverInfo),
        ]
        dpy = x11.XOpenDisplay(None)
        if not dpy:
            return False
        self._x11, self._xss, self._dpy = x11, xss, dpy
        return True

    def idle_seconds(self) -> Optional[float]:
        with self._lock:
            try:
                if not self._abrir_locked():
                    return None
                info = self._xss.XScreenSaverAllocInfo()
                if not info:
                    return None
                try:
                    root = self._x11.XDefaultRootWindow(self._dpy)
                    if not self._xss.XScreenSaverQueryInfo(self._dpy, root, info):
                        return None
                    return info.contents.idle / 1000.0
                finally:
                    self._x11.XFree(info)
            except Exception:
                return None

    def close(self) -> None:
        with self._lock:
            if self._dpy and self._x11 is not None:
                try:
                    self._x11.XCloseDisplay(self._dpy)
                except Exception:
                    pass
            self._x11 = self._xss = self._dpy = None
