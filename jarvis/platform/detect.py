"""Detecção pura da plataforma/sessão gráfica (Windows, Wayland, X11, headless).

`detect()` é uma função PURA: recebe sys_platform/environ/frozen (ou lê os
padrões do processo) e devolve um PlatformContext imutável. Sem side effects,
sem subprocess, sem imports pesados — só stdlib.
"""
from __future__ import annotations

import os
import sys
import warnings
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

_LINUX_KINDS = ("linux-wayland", "linux-x11", "linux-headless")


@dataclass(frozen=True)
class PlatformContext:
    """Fotografia imutável da plataforma corrente."""

    kind: str  # "win32"|"linux-wayland"|"linux-x11"|"linux-headless"|"unsupported"
    sys_platform: str
    desktops: Tuple[str, ...]
    xwayland: bool
    frozen: bool
    appimage: bool
    source: str  # como o kind foi decidido

    @property
    def is_windows(self) -> bool:
        return self.kind == "win32"

    @property
    def is_linux(self) -> bool:
        return self.kind.startswith("linux")


def detect(
    sys_platform: Optional[str] = None,
    environ: Optional[Mapping[str, str]] = None,
    frozen: Optional[bool] = None,
) -> PlatformContext:
    """Decide o PlatformContext. Ver a ordem do algoritmo no corpo."""
    if sys_platform is None:
        sys_platform = sys.platform
    if environ is None:
        environ = os.environ
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)

    appimage = "APPIMAGE" in environ
    desktops = tuple(
        d.strip().lower()
        for d in environ.get("XDG_CURRENT_DESKTOP", "").split(":")
        if d.strip()
    )

    def ctx(kind: str, source: str) -> PlatformContext:
        xwayland = kind == "linux-wayland" and bool(environ.get("DISPLAY"))
        return PlatformContext(
            kind=kind,
            sys_platform=sys_platform,
            desktops=desktops,
            xwayland=xwayland,
            frozen=frozen,
            appimage=appimage,
            source=source,
        )

    # 1. Windows / não-Linux
    if sys_platform == "win32":
        return ctx("win32", "os")
    if not sys_platform.startswith("linux"):
        return ctx("unsupported", "os")

    # 2. Override explícito JARVIS_PLATFORM
    override = environ.get("JARVIS_PLATFORM")
    if override:
        if override in _LINUX_KINDS:
            return ctx(override, "override")
        warnings.warn(f"JARVIS_PLATFORM inválido: {override!r} (ignorado)")

    # 3. QT_QPA_PLATFORM
    qt = environ.get("QT_QPA_PLATFORM", "")
    if qt.startswith("wayland"):
        return ctx("linux-wayland", "qt_qpa")
    if qt.startswith("xcb"):
        return ctx("linux-x11", "qt_qpa")
    if qt.startswith("offscreen") or qt.startswith("minimal"):
        return ctx("linux-headless", "qt_qpa")

    # 4. XDG_SESSION_TYPE + display correspondente
    session_type = environ.get("XDG_SESSION_TYPE")
    if session_type == "wayland" and environ.get("WAYLAND_DISPLAY"):
        return ctx("linux-wayland", "xdg_session")
    if session_type == "x11" and environ.get("DISPLAY"):
        return ctx("linux-x11", "xdg_session")

    # 5. Só um dos displays
    if environ.get("WAYLAND_DISPLAY"):
        return ctx("linux-wayland", "wayland_display")
    if environ.get("DISPLAY"):
        return ctx("linux-x11", "display")

    # 6. Nada: headless
    return ctx("linux-headless", "fallback")
