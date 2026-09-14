# comandos/clipboard_hist_ctrl.py — J.A.R.V.I.S.
# Histórico da área de transferência (monitor em background)
# -*- coding: utf-8 -*-

from __future__ import annotations
import threading, ctypes

from jarvis.platform import Cap, get as _plat_get

_history: list[str] = []
_MAX = 50
_monitor_thread: threading.Thread | None = None
_stop_event = threading.Event()
_last: str | None = None
_aviso_sem_monitor = False

# Instâncias PRIVADAS de user32/kernel32 (F1-12): criadas uma vez, com protótipos
# próprios. Não usar ctypes.windll (compartilhado) — definir restype/argtypes nele
# vazaria para main.py e para o _LazyUser32 de comandos/notif_ctrl.
# Só carregam no Windows (lazy), para o import continuar funcionando no Linux.
_user32 = None
_kernel32 = None


def _win_libs():
    """Carrega e configura user32/kernel32 privados (uma vez). Só no Windows."""
    global _user32, _kernel32
    if _user32 is None or _kernel32 is None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        # Protótipos: HANDLE de 64 bits precisa de c_void_p (c_int trunca).
        u.OpenClipboard.argtypes = [ctypes.c_void_p]
        u.OpenClipboard.restype = ctypes.c_int
        u.GetClipboardData.argtypes = [ctypes.c_uint]
        u.GetClipboardData.restype = ctypes.c_void_p
        u.CloseClipboard.argtypes = []
        u.CloseClipboard.restype = ctypes.c_int
        k.GlobalLock.argtypes = [ctypes.c_void_p]
        k.GlobalLock.restype = ctypes.c_void_p
        k.GlobalUnlock.argtypes = [ctypes.c_void_p]
        k.GlobalUnlock.restype = ctypes.c_int
        k.GlobalSize.argtypes = [ctypes.c_void_p]
        k.GlobalSize.restype = ctypes.c_size_t
        _user32, _kernel32 = u, k
    return _user32, _kernel32


def _reset_win_libs() -> None:
    """Zera o cache das libs privadas (uso em testes)."""
    global _user32, _kernel32
    _user32 = _kernel32 = None


def _get_clipboard_text() -> str | None:
    CF_UNICODETEXT = 13
    user32, kernel32 = _win_libs()

    if not user32.OpenClipboard(None):
        return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            size = kernel32.GlobalSize(h)
            raw = ctypes.wstring_at(p, size // ctypes.sizeof(ctypes.c_wchar))
            nul = raw.find("\x00")
            return raw[:nul] if nul != -1 else raw
        finally:
            kernel32.GlobalUnlock(h)
    except Exception:
        return None
    finally:
        user32.CloseClipboard()


def _plat_get_clipboard():
    """Backend de clipboard da plataforma (Cap.CLIPBOARD)."""
    return _plat_get(Cap.CLIPBOARD)


def _on_change(txt):
    """Regras do histórico: não repete o último, ignora 1 caractere, limite _MAX."""
    global _last
    if txt and txt != _last and len(txt.strip()) > 1:
        _last = txt
        if not _history or _history[-1] != txt:
            _history.append(txt)
            if len(_history) > _MAX:
                _history.pop(0)


def _monitor_loop(backend):
    try:
        backend.watch(_on_change, _stop_event)
    except Exception as e:
        print(f"[CLIPBOARD] monitor de clipboard parou: {e}")


def start_monitor():
    """Inicia o monitor de clipboard em background (watch do backend numa thread).

    Sem backend que consiga monitorar, avisa UMA vez e não inicia nada (D-F2-8).
    """
    global _monitor_thread, _last, _aviso_sem_monitor
    if _monitor_thread and _monitor_thread.is_alive():
        return
    backend = _plat_get_clipboard()
    try:
        pode = bool(backend.can_watch)
    except Exception:
        pode = False
    if not pode:
        if not _aviso_sem_monitor:
            _aviso_sem_monitor = True
            print("[CLIPBOARD] monitor de clipboard desligado: nesta sessão nenhum backend "
                  "consegue acompanhar a área de transferência.")
        return
    _stop_event.clear()
    _last = None
    _monitor_thread = threading.Thread(
        target=_monitor_loop, args=(backend,), daemon=True, name="clipboard-hist"
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
