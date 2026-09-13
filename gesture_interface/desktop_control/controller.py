"""
Desktop controller — mapeia GestureType para ações no Windows (redesign v3, sem cursor).

Gestos suportados:
    SWIPE_LEFT / SWIPE_RIGHT          → Win+Ctrl+←/→ (trocar desktop virtual)
    WINDOW_SWITCHER_OPEN              → Win+Tab (abrir seletor)
    WINDOW_SWITCHER_NAV_LEFT/RIGHT/DOWN → setas de navegação no seletor
    WINDOW_SWITCHER_CONFIRM           → Enter (confirmar janela)
    WINDOW_SWITCHER_CANCEL            → Esc (fechar seletor)
    MINIMIZE_WINDOW                   → Win+↓ x2 (minimizar janela ativa)
    MINIMIZE_ALL                      → Win+D (mostrar área de trabalho)
    ALT_F4                            → Alt+F4 (fechar app ativo)
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

try:
    import pyautogui
except Exception:
    pyautogui = None

from gesture_interface.config import (
    DESKTOP_DANGEROUS_COOLDOWN,
    GESTURE_GLOBAL_COOLDOWN,
)
from gesture_interface.gesture_engine.recognizer import GestureEvent, GestureType

if TYPE_CHECKING:
    from gesture_interface.mouse_calibration import MouseCalibration

if pyautogui is not None:
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.02


class DesktopController:
    """Executa ações no Windows com base em GestureEvent."""

    def __init__(self, calibration: "MouseCalibration | None" = None) -> None:
        # calibration param kept for signature compatibility — not used
        self._last_action: dict[str, float] = {}
        self._switcher_open: bool = False

    # ── Entry point ──────────────────────────────────────────────────────

    def handle_gesture(self, event: GestureEvent) -> None:
        handler = {
            GestureType.SWIPE_LEFT:               self._desktop_left,
            GestureType.SWIPE_RIGHT:              self._desktop_right,
            GestureType.WINDOW_SWITCHER_OPEN:     self._switcher_open_action,
            GestureType.WINDOW_SWITCHER_NAV_LEFT: self._nav_left,
            GestureType.WINDOW_SWITCHER_NAV_RIGHT:self._nav_right,
            GestureType.WINDOW_SWITCHER_NAV_DOWN: self._nav_down,
            GestureType.WINDOW_SWITCHER_CONFIRM:  self._switcher_confirm,
            GestureType.WINDOW_SWITCHER_CANCEL:   self._switcher_cancel,
            GestureType.MINIMIZE_WINDOW:          self._minimize_window,
            GestureType.MINIMIZE_ALL:             self._minimize_all,
            GestureType.ALT_F4:                   self._alt_f4,
        }.get(event.gesture)
        if handler:
            handler(event)

    # ── Cooldown helper ──────────────────────────────────────────────────

    def _cooldown(self, key: str, seconds: float) -> bool:
        """Returns True if the action can proceed (cooldown elapsed)."""
        now = time.perf_counter()
        if now - self._last_action.get(key, 0.0) < seconds:
            return False
        self._last_action[key] = now
        return True

    # ── Desktop switching ────────────────────────────────────────────────

    def _desktop_left(self, event: GestureEvent) -> None:
        if self._cooldown("desktop", 0.7):
            pyautogui.hotkey("ctrl", "win", "left")

    def _desktop_right(self, event: GestureEvent) -> None:
        if self._cooldown("desktop", 0.7):
            pyautogui.hotkey("ctrl", "win", "right")

    # ── Window switcher (Win+Tab) ────────────────────────────────────────

    def _switcher_open_action(self, event: GestureEvent) -> None:
        if self._cooldown("switcher_open", 1.0):
            pyautogui.hotkey("win", "tab")
            self._switcher_open = True

    def _nav_left(self, event: GestureEvent) -> None:
        if self._switcher_open and self._cooldown("switcher_nav", 0.25):
            pyautogui.press("left")

    def _nav_right(self, event: GestureEvent) -> None:
        if self._switcher_open and self._cooldown("switcher_nav", 0.25):
            pyautogui.press("right")

    def _nav_down(self, event: GestureEvent) -> None:
        if self._switcher_open and self._cooldown("switcher_nav", 0.25):
            pyautogui.press("down")

    def _switcher_confirm(self, event: GestureEvent) -> None:
        if self._cooldown("switcher_confirm", 0.5):
            pyautogui.press("enter")
            self._switcher_open = False

    def _switcher_cancel(self, event: GestureEvent) -> None:
        if self._cooldown("switcher_cancel", 0.5):
            pyautogui.press("escape")
            self._switcher_open = False

    # ── Window management ────────────────────────────────────────────────

    def _minimize_window(self, event: GestureEvent) -> None:
        """Win+↓ twice: maximized→normal→minimized."""
        if self._cooldown("minimize_window", DESKTOP_DANGEROUS_COOLDOWN):
            pyautogui.hotkey("win", "down")
            time.sleep(0.05)
            pyautogui.hotkey("win", "down")

    def _minimize_all(self, event: GestureEvent) -> None:
        if self._cooldown("minimize_all", DESKTOP_DANGEROUS_COOLDOWN):
            pyautogui.hotkey("win", "d")

    def _alt_f4(self, event: GestureEvent) -> None:
        if self._cooldown("alt_f4", DESKTOP_DANGEROUS_COOLDOWN):
            pyautogui.hotkey("alt", "F4")
