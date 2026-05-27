# comandos/clipboard_hist_ctrl.py — J.A.R.V.I.S.
# Histórico da área de transferência (monitor em background)
# -*- coding: utf-8 -*-

from __future__ import annotations
import threading, ctypes, time

_history: list[str] = []
_MAX = 50
_monitor_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _get_clipboard_text() -> str | None:
    CF_UNICODETEXT = 13
    user32   = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalLock.restype = ctypes.c_void_p

    if not user32.OpenClipboard(0):
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(ctypes.c_void_p(h))
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(ctypes.c_void_p(h))
    except Exception:
        return None
    finally:
        user32.CloseClipboard()


def _monitor_loop():
    last = None
    while not _stop_event.is_set():
        try:
            txt = _get_clipboard_text()
            if txt and txt != last and len(txt.strip()) > 1:
                last = txt
                if not _history or _history[-1] != txt:
                    _history.append(txt)
                    if len(_history) > _MAX:
                        _history.pop(0)
        except Exception:
            pass
        time.sleep(0.8)


def start_monitor():
    """Inicia o monitor de clipboard em background."""
    global _monitor_thread
    if _monitor_thread and _monitor_thread.is_alive():
        return
    _stop_event.clear()
    _monitor_thread = threading.Thread(
        target=_monitor_loop, daemon=True, name="clipboard-hist"
    )
    _monitor_thread.start()


def get_historico(n: int = 10) -> str:
    if not _history:
        return "Histórico do clipboard vazio, senhor."
    itens = _history[-n:][::-1]   # mais recentes primeiro
    linhas = [f"📋 Últimos {len(itens)} itens copiados:"]
    for i, item in enumerate(itens, 1):
        preview = item.replace("\n", " ").strip()
        if len(preview) > 90:
            preview = preview[:87] + "..."
        linhas.append(f"  [{i}] {preview}")
    return "\n".join(linhas)


def limpar_historico() -> str:
    _history.clear()
    return "Histórico do clipboard limpo, senhor."
