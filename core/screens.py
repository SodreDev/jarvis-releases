# -*- coding: utf-8 -*-
"""
core.screens — Detecção e controle de múltiplos monitores no Windows.

API:
    list_monitors()          → list[Monitor]  (id, name, x, y, width, height, primary, scale)
    get_primary()            → Monitor
    move_window(hwnd, mon_id, *, fullscreen=False, ratio=1.0)
    move_window_by_title(title_substring, mon_id, **kw)
    list_windows()           → list[(hwnd, title)]  janelas top-level visíveis
    set_window_ratio(hwnd, ratio_w, ratio_h)  posiciona ocupando fração do monitor

Backends:
    • screeninfo (cross-platform) para enumerar monitores quando disponível.
    • Win32 (user32) para mover/redimensionar janelas e detectar HWND por título.
    • Fallback: tenta `EnumDisplayMonitors` puro via ctypes se screeninfo ausente.

Tudo é tolerante a falha — chamadas retornam estruturas vazias quando o SO
não suporta ou módulos não estão instalados.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, asdict
from typing import Callable, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Monitor:
    id: int
    name: str
    x: int
    y: int
    width: int
    height: int
    primary: bool
    scale: float = 1.0

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Enumeração de monitores
# ─────────────────────────────────────────────────────────────────────────────
def _list_via_screeninfo() -> List[Monitor]:
    try:
        from screeninfo import get_monitors  # type: ignore
    except Exception:
        return []
    out: List[Monitor] = []
    mons = get_monitors() or []
    for i, m in enumerate(mons):
        out.append(
            Monitor(
                id=i,
                name=getattr(m, "name", f"DISPLAY{i + 1}") or f"DISPLAY{i + 1}",
                x=int(m.x),
                y=int(m.y),
                width=int(m.width),
                height=int(m.height),
                primary=bool(getattr(m, "is_primary", i == 0)),
                scale=1.0,
            )
        )
    return out


def _list_via_win32() -> List[Monitor]:
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return []

    user32 = ctypes.windll.user32
    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    monitors: List[Monitor] = []

    class _MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    def _cb(hmon, hdc, rect, lparam):
        mi = _MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            return 1
        idx = len(monitors)
        monitors.append(
            Monitor(
                id=idx,
                name=str(mi.szDevice) or f"DISPLAY{idx + 1}",
                x=int(mi.rcMonitor.left),
                y=int(mi.rcMonitor.top),
                width=int(mi.rcMonitor.right - mi.rcMonitor.left),
                height=int(mi.rcMonitor.bottom - mi.rcMonitor.top),
                primary=bool(mi.dwFlags & 1),
                scale=1.0,
            )
        )
        return 1

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_cb), 0)
    return monitors


def list_monitors() -> List[Monitor]:
    """Enumera monitores (cache 5s)."""
    global _CACHE, _CACHE_TS
    import time

    now = time.time()
    if _CACHE and (now - _CACHE_TS) < 5.0:
        return _CACHE
    mons = _list_via_screeninfo() or _list_via_win32()
    if not mons:
        mons = [Monitor(0, "FALLBACK", 0, 0, 1920, 1080, True, 1.0)]
    _CACHE = mons
    _CACHE_TS = now
    return mons


_CACHE: List[Monitor] = []
_CACHE_TS: float = 0.0


def get_primary() -> Monitor:
    for m in list_monitors():
        if m.primary:
            return m
    return list_monitors()[0]


def get_monitor(mon_id: int) -> Optional[Monitor]:
    for m in list_monitors():
        if m.id == mon_id:
            return m
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Manipulação de janelas (Win32)
# ─────────────────────────────────────────────────────────────────────────────
def _win32() -> Optional[Tuple[object, object]]:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes  # noqa
        return ctypes.windll.user32, ctypes
    except Exception:
        return None


def list_windows() -> List[Tuple[int, str]]:
    """Lista (hwnd, título) de janelas top-level visíveis."""
    pair = _win32()
    if not pair:
        return []
    user32, ctypes = pair
    from ctypes import wintypes

    EnumWindowsProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool, wintypes.HWND, wintypes.LPARAM
    )
    out: List[Tuple[int, str]] = []

    def _cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if title:
            out.append((int(hwnd), title))
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return out


def find_window(title_substring: str) -> Optional[int]:
    needle = (title_substring or "").lower().strip()
    if not needle:
        return None
    for hwnd, title in list_windows():
        if needle in title.lower():
            return hwnd
    return None


def move_window(
    hwnd: int,
    mon_id: int,
    *,
    fullscreen: bool = False,
    ratio: float = 1.0,
    align: str = "center",
) -> bool:
    """Move/redimensiona uma janela para o monitor `mon_id`.

    - `fullscreen=True` → ocupa todo o monitor (sem maximizar via WS_MAXIMIZE).
    - `ratio` ∈ (0,1] → fração da área do monitor (largura E altura).
    - `align`: "center", "left", "right", "top", "bottom".
    """
    pair = _win32()
    if not pair:
        return False
    user32, _ctypes = pair
    mon = get_monitor(mon_id)
    if not mon:
        return False

    if fullscreen:
        w, h = mon.width, mon.height
        x, y = mon.x, mon.y
    else:
        ratio = max(0.1, min(1.0, float(ratio)))
        w = int(mon.width * ratio)
        h = int(mon.height * ratio)
        if align == "left":
            x, y = mon.x, mon.y + (mon.height - h) // 2
        elif align == "right":
            x, y = mon.right - w, mon.y + (mon.height - h) // 2
        elif align == "top":
            x, y = mon.x + (mon.width - w) // 2, mon.y
        elif align == "bottom":
            x, y = mon.x + (mon.width - w) // 2, mon.bottom - h
        else:
            x = mon.x + (mon.width - w) // 2
            y = mon.y + (mon.height - h) // 2

    # SW_RESTORE primeiro para tirar de maximizado.
    try:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        return bool(user32.MoveWindow(hwnd, x, y, w, h, True))
    except Exception:
        return False


def move_window_by_title(title_substring: str, mon_id: int, **kw) -> bool:
    hwnd = find_window(title_substring)
    if not hwnd:
        return False
    return move_window(hwnd, mon_id, **kw)


def set_window_ratio(
    hwnd: int, ratio_w: float, ratio_h: float, *, mon_id: Optional[int] = None
) -> bool:
    pair = _win32()
    if not pair:
        return False
    user32, _ctypes = pair
    mon = get_monitor(mon_id) if mon_id is not None else get_primary()
    if not mon:
        return False
    w = int(mon.width * max(0.1, min(1.0, ratio_w)))
    h = int(mon.height * max(0.1, min(1.0, ratio_h)))
    x = mon.x + (mon.width - w) // 2
    y = mon.y + (mon.height - h) // 2
    try:
        user32.ShowWindow(hwnd, 9)
        return bool(user32.MoveWindow(hwnd, x, y, w, h, True))
    except Exception:
        return False


__all__ = [
    "Monitor",
    "list_monitors",
    "get_primary",
    "get_monitor",
    "list_windows",
    "find_window",
    "move_window",
    "move_window_by_title",
    "set_window_ratio",
]
