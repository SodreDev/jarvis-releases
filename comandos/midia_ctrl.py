# comandos/midia_ctrl.py — J.A.R.V.I.S.
# Controle de mídia global (Windows Media Keys + Windows Media Session + extras)
# Sem dependências externas — usa apenas ctypes e win32api
# -*- coding: utf-8 -*-

from __future__ import annotations
import ctypes
import ctypes.wintypes
import subprocess
import os
import sys
import re
import time
import threading
from typing import Optional

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


def _press_key(vk: int) -> None:
    """Simula pressionar e soltar uma tecla virtual."""
    _user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.05)
    _user32.keybd_event(vk, 0, 0x0002, 0)  # KEYEVENTF_KEYUP


# ── Controles básicos ─────────────────────────────────────────────────────────

def play_pause() -> str:
    _press_key(VK_MEDIA_PLAY_PAUSE)
    return "Play/Pause enviado, senhor."


def parar() -> str:
    _press_key(VK_MEDIA_STOP)
    return "Mídia parada, senhor."


def proxima_faixa() -> str:
    _press_key(VK_MEDIA_NEXT_TRACK)
    return "Próxima faixa, senhor."


def faixa_anterior() -> str:
    _press_key(VK_MEDIA_PREV_TRACK)
    return "Faixa anterior, senhor."


def mutar() -> str:
    _press_key(VK_VOLUME_MUTE)
    return "Volume mutado/desmutado, senhor."


def volume_up(steps: int = 3) -> str:
    for _ in range(steps):
        _press_key(VK_VOLUME_UP)
        time.sleep(0.02)
    return f"Volume aumentado {steps} nível(is), senhor."


def volume_down(steps: int = 3) -> str:
    for _ in range(steps):
        _press_key(VK_VOLUME_DOWN)
        time.sleep(0.02)
    return f"Volume reduzido {steps} nível(is), senhor."


# ── Informação de mídia em execução (Windows Media Session) ──────────────────

def _get_media_info_ps() -> dict:
    """Usa PowerShell para consultar a SMTC (System Media Transport Controls)."""
    ps_script = """
$sessions = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime]
$mgr = $sessions::RequestAsync().GetAwaiter().GetResult()
$session = $mgr.GetCurrentSession()
if ($null -eq $session) { Write-Output 'NULL'; exit }
$info = $session.TryGetMediaPropertiesAsync().GetAwaiter().GetResult()
$pb = $session.GetPlaybackInfo()
$app = $session.SourceAppUserModelId
Write-Output ("{0}|{1}|{2}|{3}" -f $info.Title, $info.Artist, $pb.PlaybackStatus, $app)
"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
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


def o_que_esta_tocando() -> str:
    """Retorna o que está tocando no sistema agora via SMTC."""
    info = _get_media_info_ps()
    if not info or not info.get("title"):
        return "Nenhuma mídia em reprodução detectada, senhor."
    titulo  = info.get("title", "?")
    artista = info.get("artist", "")
    status  = info.get("status", "")
    app     = info.get("app", "").split("!")[-1] or "reprodutor desconhecido"

    status_map = {
        "Playing": "tocando", "Paused": "pausado",
        "Stopped": "parado", "0": "parado", "1": "parado",
        "3": "tocando", "4": "pausado",
    }
    estado = status_map.get(status, status.lower())

    if artista:
        return f"Está {estado} '{titulo}' — {artista}, via {app}, senhor."
    return f"Está {estado} '{titulo}' via {app}, senhor."


# ── Controle de apps de mídia ─────────────────────────────────────────────────

_MEDIA_APPS = {
    "youtube":   ("chrome.exe", "https://www.youtube.com"),
    "netflix":   ("chrome.exe", "https://www.netflix.com"),
    "spotify":   ("Spotify.exe", None),
    "deezer":    ("chrome.exe", "https://www.deezer.com"),
    "soundcloud":("chrome.exe", "https://soundcloud.com"),
    "twitch":    ("chrome.exe", "https://www.twitch.tv"),
    "plex":      ("Plex.exe", None),
    "vlc":       ("vlc.exe", None),
    "winamp":    ("winamp.exe", None),
    "foobar":    ("foobar2000.exe", None),
}


def abrir_app_midia(nome: str) -> str:
    nome_l = nome.lower().strip()
    if nome_l in _MEDIA_APPS:
        exe, url = _MEDIA_APPS[nome_l]
        if url:
            import webbrowser
            webbrowser.open(url)
            return f"Abrindo {nome} no navegador, senhor."
        else:
            subprocess.Popen(["start", exe], shell=True)
            return f"Abrindo {nome}, senhor."
    return f"App de mídia '{nome}' não reconhecido, senhor."


# ── Timer de silêncio ─────────────────────────────────────────────────────────

_silence_timer: Optional[threading.Timer] = None


def silenciar_por(segundos: int, callback=None) -> str:
    """Muta o volume por `segundos` e depois desmuta."""
    global _silence_timer
    if _silence_timer:
        _silence_timer.cancel()
    mutar()
    def _restore():
        mutar()
        if callback:
            callback("Volume restaurado, senhor.")
    _silence_timer = threading.Timer(segundos, _restore)
    _silence_timer.daemon = True
    _silence_timer.start()
    m, s = divmod(segundos, 60)
    t_str = f"{m}min{s:02d}s" if m else f"{s}s"
    return f"Volume mutado por {t_str}, senhor."


# ── Fade de volume ────────────────────────────────────────────────────────────

def fade_out(duracao_s: int = 5) -> str:
    """Faz fade-out gradual do volume em `duracao_s` segundos."""
    passos = duracao_s * 2
    intervalo = duracao_s / passos
    def _run():
        for _ in range(passos):
            _press_key(VK_VOLUME_DOWN)
            time.sleep(intervalo)
    threading.Thread(target=_run, daemon=True).start()
    return f"Fade-out em {duracao_s}s iniciado, senhor."


def fade_in(duracao_s: int = 5) -> str:
    """Faz fade-in gradual do volume em `duracao_s` segundos."""
    passos = duracao_s * 2
    intervalo = duracao_s / passos
    def _run():
        for _ in range(passos):
            _press_key(VK_VOLUME_UP)
            time.sleep(intervalo)
    threading.Thread(target=_run, daemon=True).start()
    return f"Fade-in em {duracao_s}s iniciado, senhor."


# ── Shuffle / Repeat via teclado (app-specific workaround) ───────────────────
# Nota: shuffle/repeat global não existe via VK — funciona por atalho de app

def toggle_shuffle_spotify() -> str:
    """Envia Ctrl+Shift+S para o Spotify (atalho de shuffle)."""
    import ctypes
    VK_CONTROL = 0x11
    VK_SHIFT   = 0x10
    VK_S       = 0x53
    for vk in (VK_CONTROL, VK_SHIFT, VK_S):
        _user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.1)
    for vk in (VK_S, VK_SHIFT, VK_CONTROL):
        _user32.keybd_event(vk, 0, 0x0002, 0)
    return "Shuffle alternado no Spotify, senhor."


def toggle_repeat_spotify() -> str:
    """Envia Ctrl+Shift+R para o Spotify (atalho de repeat)."""
    VK_CONTROL = 0x11
    VK_SHIFT   = 0x10
    VK_R       = 0x52
    for vk in (VK_CONTROL, VK_SHIFT, VK_R):
        _user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.1)
    for vk in (VK_R, VK_SHIFT, VK_CONTROL):
        _user32.keybd_event(vk, 0, 0x0002, 0)
    return "Repeat alternado no Spotify, senhor."


# ── Detecção por texto ────────────────────────────────────────────────────────

def detectar_comando_midia(texto: str) -> Optional[tuple[str, str]]:
    """
    Detecta comando de mídia no texto.
    Retorna (acao, arg) ou None.
    """
    tl = texto.lower().strip()

    if re.search(r"\b(?:play|pause|toca|pausa|retoma?|continua?)\b", tl):
        return ("midia_play_pause", "")
    if re.search(r"\b(?:para[r]?|stop)\s+(?:a\s+)?m[uú]sica\b", tl):
        return ("midia_parar", "")
    if re.search(r"\b(?:pr[oó]xima|avan[çc]a|skip|next)\s+(?:m[uú]sica|faixa|track)?\b", tl):
        return ("midia_proxima", "")
    if re.search(r"\b(?:anterior|volta|back|prev)\s+(?:m[uú]sica|faixa|track)?\b", tl):
        return ("midia_anterior", "")
    if re.search(r"\b(?:o\s+que\s+(?:est[aá]\s+)?(?:tocando|tocand[oa]|rolando)|"
                 r"que\s+m[uú]sica\s+[eé]\s+essa|que\s+[eé]\s+(?:ess[ae]\s+)?m[uú]sica|"
                 r"nome\s+da\s+m[uú]sica)\b", tl):
        return ("midia_info", "")

    m = re.search(r"\b(?:silencia[r]?|muta[r]?|cala[r]?)\s+(?:por\s+)?(\d+)\s*(?:min(?:utos?)?|seg(?:undos?)?)?\b", tl)
    if m:
        raw = texto[m.start():m.end()]
        num_m = re.search(r"(\d+)\s*(min|seg)", raw, re.I)
        if num_m:
            secs = int(num_m.group(1)) * (60 if "min" in num_m.group(2) else 1)
            return ("midia_silenciar", str(secs))

    if re.search(r"\bfade[\s-]?out\b", tl):
        return ("midia_fade_out", "")
    if re.search(r"\bfade[\s-]?in\b", tl):
        return ("midia_fade_in", "")

    return None
