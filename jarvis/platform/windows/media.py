"""Mídia no Windows (F2-08): cópia literal das teclas virtuais e da SMTC do midia_ctrl.

W1/W2 (D-F2-10: nada de COM agora):
- ``_LazyUser32``, as constantes ``VK_*`` e ``_press_key`` são literais: user32 só é
  ligado no primeiro uso, sem tocar ``ctypes.windll`` no import;
- ``now_playing`` = ``_get_media_info_ps`` literal (PowerShell + SMTC);
- ``toggle_mute``/``volume_step`` = teclas virtuais ``VK_VOLUME_MUTE``/``UP``/``DOWN``
  (com a pausa de 0,02 s entre os passos, como o ``volume_up``/``volume_down``).
user32, sleep e subprocess.run podem ser injetados para os testes.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time

from ..common.base import BackendBase

# ── Virtual Key Codes ─────────────────────────────────────────────────────────
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_STOP       = 0xB4
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_VOLUME_MUTE      = 0xAD
VK_VOLUME_DOWN      = 0xAE
VK_VOLUME_UP        = 0xAF


class _LazyUser32:
    """Adia ctypes.windll.user32 até o primeiro uso.

    No Windows o comportamento é idêntico (binda user32 no primeiro acesso).
    No Linux qualquer uso ergue NotImplementedError em vez de quebrar o import.
    """
    _real = None

    def __getattr__(self, name):
        if sys.platform != "win32":
            raise NotImplementedError(
                "controle de mídia via API do Windows não suportado no Linux ainda"
            )
        if _LazyUser32._real is None:
            _LazyUser32._real = ctypes.windll.user32
        return getattr(_LazyUser32._real, name)


_user32 = _LazyUser32()

_PS_SCRIPT = """
$sessions = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime]
$mgr = $sessions::RequestAsync().GetAwaiter().GetResult()
$session = $mgr.GetCurrentSession()
if ($null -eq $session) { Write-Output 'NULL'; exit }
$info = $session.TryGetMediaPropertiesAsync().GetAwaiter().GetResult()
$pb = $session.GetPlaybackInfo()
$app = $session.SourceAppUserModelId
Write-Output ("{0}|{1}|{2}|{3}" -f $info.Title, $info.Artist, $pb.PlaybackStatus, $app)
"""


class VirtualKeyMedia(BackendBase):
    name = "windows.virtual_keys"

    def __init__(self, ctx=None, *, user32=None, sleep_fn=None, run_fn=None):
        self.ctx = ctx
        self._user32 = user32 if user32 is not None else _user32
        self._sleep = sleep_fn or time.sleep
        self._run = run_fn or subprocess.run

    def _press_key(self, vk: int) -> None:
        """Simula pressionar e soltar uma tecla virtual."""
        self._user32.keybd_event(vk, 0, 0, 0)
        self._sleep(0.05)
        self._user32.keybd_event(vk, 0, 0x0002, 0)  # KEYEVENTF_KEYUP

    def play_pause(self) -> None:
        self._press_key(VK_MEDIA_PLAY_PAUSE)

    def stop(self) -> None:
        self._press_key(VK_MEDIA_STOP)

    def next(self) -> None:
        self._press_key(VK_MEDIA_NEXT_TRACK)

    def previous(self) -> None:
        self._press_key(VK_MEDIA_PREV_TRACK)

    def toggle_mute(self) -> None:
        self._press_key(VK_VOLUME_MUTE)

    def volume_step(self, steps: int) -> None:
        vk = VK_VOLUME_UP if steps > 0 else VK_VOLUME_DOWN
        for _ in range(abs(steps)):
            self._press_key(vk)
            self._sleep(0.02)

    def now_playing(self) -> dict:
        """Usa PowerShell para consultar a SMTC (System Media Transport Controls)."""
        try:
            r = self._run(
                ["powershell", "-NoProfile", "-Command", _PS_SCRIPT],
                capture_output=True, text=True, timeout=8
            )
            line = r.stdout.strip()
            if line and line != "NULL":
                parts = line.split("|", 3)
                return {
                    "title":  parts[0] if len(parts) > 0 else "",
                    "artist": parts[1] if len(parts) > 1 else "",
                    "status": parts[2] if len(parts) > 2 else "",
                    "app":    parts[3] if len(parts) > 3 else "",
                }
        except Exception:
            pass
        return {}
