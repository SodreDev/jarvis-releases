"""Enumeração das capacidades de plataforma (superfície Windows a portar)."""
from __future__ import annotations

from enum import Enum


class Cap(str, Enum):
    """Capacidades resolvíveis pela camada de plataforma (valores em minúsculas)."""

    PATHS = "paths"
    OPEN_PATH = "open_path"
    PROCESSES = "processes"
    CLIPBOARD = "clipboard"
    NOTIFIER = "notifier"
    NOTIFICATION_READER = "notification_reader"
    VOLUME = "volume"
    HOTKEYS = "hotkeys"
    INPUT = "input"
    SCREEN_CAPTURE = "screen_capture"
    WINDOW_MANAGER = "window_manager"
    SESSION = "session"
    TRAY = "tray"
    MEDIA = "media"
    WEBVIEW_ENGINE = "webview_engine"
