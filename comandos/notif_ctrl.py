# comandos/notif_ctrl.py  J.A.R.V.I.S.
# Monitor de notificações do Windows (WhatsApp, Discord, Instagram)
# via SetWinEventHook + UIAutomation  funciona com Python não-empacotado.
# -*- coding: utf-8 -*-

import ctypes
import ctypes.wintypes as wt
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable

#  Win32 constants 
_WINEVENT_OUTOFCONTEXT = 0x0000
_EVENT_OBJECT_SHOW     = 0x8002
_OBJID_WINDOW          = 0          # idObject value for window-level events

_user32 = ctypes.windll.user32

# CFUNCTYPE kept alive at module level so GC does not free the trampoline
_WinEventProc = ctypes.CFUNCTYPE(
    None,
    wt.HANDLE,  # hWinEventHook
    wt.DWORD,   # event
    wt.HWND,    # hwnd
    wt.LONG,    # idObject
    wt.LONG,    # idChild
    wt.DWORD,   # dwEventThread
    wt.DWORD,   # dwmsEventTime
)

#  Class names for toast host windows 
# Windows 10/11: ShellExperienceHost -> Windows.UI.Core.CoreWindow
# Windows 11 24H2+ may use ToastContentHost or similar
_TOAST_CLASS_FRAGMENTS = ("CoreWindow", "ToastContent", "ToastNotif", "Messagetips")

#  App keyword -> internal key 
_APP_KEYWORDS: list[tuple[str, str]] = [
    ("whatsapp",  "whatsapp"),
    ("discord",   "discord"),
    ("instagram", "instagram"),
]

_DEBOUNCE_SEC       = 5    # segundos aguardando mais msgs do mesmo remetente
_COOLDOWN_SEC       = 180  # segundos sem re-notificar o mesmo remetente (3 min)
_CONVO_DEBOUNCE_SEC = 60   # 1 min aguardando mais msgs em modo conversa
_CONVO_DURATION_SEC = 900  # 15 minutos de leitura automática por remetente

# Discord: sender com '#' ou '|' = canal de servidor (mensagem em guild)
# Inclui variantes com chars Unicode direcionais (U+2068/U+2069)
_RX_DISCORD_SERVER = re.compile(r"[\u2068\u2069]*#|\s\|\s")

# Discord: menções em massa que o JARVIS deve IGNORAR no modo away
_RX_DISCORD_MASS_MENTION = re.compile(r"@(everyone|here)\b", re.I)

#  regex: audio message detection 
_RX_AUDIO = re.compile(
    r"\b([Áá]udio|[Aa]udio(\s+message)?|voice(\s+note)?)\b",
    re.I | re.UNICODE,
)


# 
# helpers
# 

def _get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


# 
# BUFFER DE DEBOUNCE
# 

class _DebounceBuffer:
    """
    Accumulates messages per (app, sender) and fires callback after debounce.

    Normal mode  : _DEBOUNCE_SEC (5 s) wait -> ask user -> _COOLDOWN_SEC silence.
    Convo mode   : _CONVO_DEBOUNCE_SEC (60 s) sliding wait -> auto-read, no cooldown.
    Convo mode ends automatically after _CONVO_DURATION_SEC (15 min).
    """

    def __init__(self, callback):
        self._callback = callback
        self._lock = threading.Lock()
        self._buffers: dict = {}
        self._cooldown: dict = {}       # (app, sender) -> expiry
        self._active_convo: dict = {}   # (app, sender) -> expiry
        self._recent: dict = {}         # (app, sender) -> list[dict] — unread accumulator

    # ── conversation mode ────────────────────────────────────────────────────

    def activate_convo(self, app_key: str, sender: str,
                       duration: float = _CONVO_DURATION_SEC):
        """Enter conversation mode: auto-read, 1-min debounce, no cooldown."""
        key = (app_key, sender)
        with self._lock:
            self._active_convo[key] = time.time() + duration
            self._cooldown.pop(key, None)
        print(f"[NOTIF] Modo conversa ativado para {sender} ({int(duration // 60)} min).")

    def deactivate_convo(self, app_key: str, sender: str):
        key = (app_key, sender)
        with self._lock:
            self._active_convo.pop(key, None)

    def is_convo_active(self, app_key: str, sender: str) -> bool:
        key = (app_key, sender)
        with self._lock:
            exp = self._active_convo.get(key)
            if exp is None:
                return False
            if time.time() > exp:
                del self._active_convo[key]
                return False
            return True

    # ── cooldown ─────────────────────────────────────────────────────────────

    def reset_sender(self, app_key: str, sender: str):
        """Release cooldown for this sender (call when user acknowledges)."""
        key = (app_key, sender)
        with self._lock:
            self._cooldown.pop(key, None)

    # ── add / fire ───────────────────────────────────────────────────────────

    def add(self, app_key: str, sender: str, msg_type: str, content: str):
        # Filtro: ignora mensagens que o PRÓPRIO usuário enviou de outro
        # device (parecem "novas" porque o desktop só vê o eco). Mapeia
        # app_key→platform e consulta person_registry.is_self_account.
        try:
            _PLAT = {"whatsapp": "whatsapp", "discord": "discord",
                     "instagram": "instagram", "telegram": "telegram"}
            plat = _PLAT.get((app_key or "").lower())
            if plat:
                from core.person_registry import is_self_account as _iss
                if _iss(plat, sender or ""):
                    print(f"[NOTIF] ignorando msg do próprio usuário ({plat}:{sender})")
                    return
        except Exception:
            pass
        key = (app_key, sender)
        with self._lock:
            convo_exp = self._active_convo.get(key)
            in_convo  = convo_exp is not None and time.time() < convo_exp
            if convo_exp is not None and not in_convo:
                del self._active_convo[key]  # limpeza de expirado

            # Cooldown bloqueia apenas fora do modo conversa
            if not in_convo:
                if key in self._cooldown and time.time() < self._cooldown[key]:
                    return

            debounce = _CONVO_DEBOUNCE_SEC if in_convo else _DEBOUNCE_SEC

            if key not in self._buffers:
                self._buffers[key] = {"msgs": [], "timer": None, "in_convo": in_convo}
            buf = self._buffers[key]
            _now_iso = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
            buf["msgs"].append({"type": msg_type, "content": content, "ts": _now_iso})
            buf["in_convo"] = in_convo

            if buf["timer"] is not None:
                buf["timer"].cancel()
            t = threading.Timer(debounce, self._fire, args=(key,))
            t.daemon = True
            buf["timer"] = t
            t.start()

    def get_unread(self, app_key: str | None = None) -> dict[tuple, list[dict]]:
        """Return and clear accumulated unread messages. Filter by app if given."""
        with self._lock:
            if app_key:
                out = {k: v for k, v in self._recent.items() if k[0] == app_key}
                for k in out:
                    del self._recent[k]
                    self._cooldown.pop(k, None)
            else:
                out = dict(self._recent)
                for k in out:
                    self._cooldown.pop(k, None)
                self._recent.clear()
            return out

    def _fire(self, key: tuple):
        with self._lock:
            buf = self._buffers.pop(key, None)
            in_convo = buf.get("in_convo", False) if buf else False
            if buf and buf["msgs"]:
                # Acumula em _recent para leitura sob demanda
                self._recent.setdefault(key, []).extend(buf["msgs"])
            if buf and buf["msgs"] and not in_convo:
                self._cooldown[key] = time.time() + _COOLDOWN_SEC
        if buf and buf["msgs"]:
            app_key, sender = key
            auto_read = in_convo

            def _run():
                try:
                    self._callback(app_key, sender, buf["msgs"], auto_read)
                except Exception as e:
                    print(f"[NOTIF] Erro no callback ({app_key}/{sender}): {e}")

            threading.Thread(target=_run, daemon=True).start()

    def clear(self):
        with self._lock:
            for b in self._buffers.values():
                if b["timer"]:
                    b["timer"].cancel()
            self._buffers.clear()


# 
# MONITOR PRINCIPAL
# 
class NotificationMonitor:
    """
    Intercepts Windows toast notifications using SetWinEventHook (EVENT_OBJECT_SHOW).
    Reads toast text via UIAutomation (uiautomation package).
    Works for unpackaged Python processes  no UWP access required.

    Calls callback(app_key, sender, msgs) after 15-second debounce.
    msgs = list of {"type": "text"|"audio", "content": str}
    """

    def __init__(self, callback: Callable[[str, str, list[dict]], None]):
        self._callback   = callback
        self._buffer     = _DebounceBuffer(callback)
        self._running    = False
        self._pump_thread = None
        self._proc_ref   = None           # keep WinEvent callback alive
        self._seen: dict[int, float] = {}
        self._seen_lock = threading.Lock()

    #  public 

    def start(self) -> bool:
        self._running = True
        self._pump_thread = threading.Thread(
            target=self._message_pump,
            daemon=True,
            name="jarvis-notif-pump",
        )
        self._pump_thread.start()
        print("[NOTIF] Monitor ativo (SetWinEventHook + UIAutomation).")
        return True

    def stop(self):
        self._running = False
        if self._pump_thread:
            _user32.PostThreadMessageW(self._pump_thread.ident, 0x0012, 0, 0)
        self._buffer.clear()
        print("[NOTIF] Monitor parado.")

    def reset_sender(self, app_key: str, sender: str):
        """Free cooldown for a sender after the user acknowledges the notification."""
        self._buffer.reset_sender(app_key, sender)

    def activate_convo(self, app_key: str, sender: str):
        """Ativa modo conversa (leitura automática por 15 min) para este remetente."""
        self._buffer.activate_convo(app_key, sender)

    def deactivate_convo(self, app_key: str, sender: str):
        self._buffer.deactivate_convo(app_key, sender)

    def is_convo_active(self, app_key: str, sender: str) -> bool:
        return self._buffer.is_convo_active(app_key, sender)

    def get_unread(self, app_key: str | None = None) -> dict[tuple, list[dict]]:
        """Return and clear accumulated recent messages."""
        return self._buffer.get_unread(app_key)

    #  message pump 

    def _message_pump(self):
        proc = _WinEventProc(self._on_win_event)
        self._proc_ref = proc

        hook = _user32.SetWinEventHook(
            _EVENT_OBJECT_SHOW, _EVENT_OBJECT_SHOW,
            None, proc, 0, 0, _WINEVENT_OUTOFCONTEXT,
        )
        if not hook:
            print("[NOTIF] ERRO: SetWinEventHook falhou.")
            return

        msg = wt.MSG()
        while self._running:
            ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

        _user32.UnhookWinEvent(hook)

    #  WinEvent callback 

    def _on_win_event(self, hHook, event, hwnd, idObj, idChild, thread, time_ms):
        if not hwnd:
            return
        try:
            cn = _get_class_name(hwnd)
        except Exception:
            return
        if not any(frag in cn for frag in _TOAST_CLASS_FRAGMENTS):
            return

        now = time.time()
        with self._seen_lock:
            if hwnd in self._seen and now < self._seen[hwnd]:
                return
            self._seen[hwnd] = now + 30
            expired = [h for h, t in self._seen.items() if now > t]
            for h in expired:
                del self._seen[h]

        threading.Thread(
            target=self._read_toast,
            args=(hwnd,),
            daemon=True,
        ).start()

    #  toast reader 

    def _read_toast(self, hwnd: int):
        time.sleep(0.45)
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx.restype = ctypes.HRESULT
        try:
            hr = ole32.CoInitializeEx(None, 0x2)
        except OSError:
            hr = -1
        com_owned = hr >= 0
        try:
            import uiautomation as auto
            ctrl = auto.ControlFromHandle(hwnd)
            if ctrl is None:
                print(f"[NOTIF] hwnd={hwnd}: ctrl=None")
                return

            texts = _collect_texts(ctrl)
            if not texts:
                print(f"[NOTIF] hwnd={hwnd}: sem textos")
                return

            app_key, sender, content = _parse_notif_texts(texts)
            print(f"[NOTIF] parse: app={app_key!r} sender={sender!r} content={content[:50]!r}")
            if not app_key:
                return

            is_audio = bool(_RX_AUDIO.search(content))
            msg_type = "audio" if is_audio else "text"

            print(f"[NOTIF] {app_key.upper()} | {sender}: {content[:80]} [{msg_type}]")
            self._buffer.add(app_key, sender, msg_type, content)

        except Exception as e:
            print(f"[NOTIF] Erro ao ler toast hwnd={hwnd}: {e}")
        finally:
            if com_owned:
                ole32.CoUninitialize()


# 
# Helper: recursively collect all text from a UIAutomation control tree
# 

def _collect_texts(ctrl, depth: int = 0) -> list[str]:
    if depth > 14:
        return []
    results: list[str] = []
    try:
        name = ctrl.Name
        if name and name.strip():
            results.append(name.strip())
    except Exception:
        pass
    try:
        for child in ctrl.GetChildren():
            results.extend(_collect_texts(child, depth + 1))
    except Exception:
        pass
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Parse Windows 11 toast notification texts into (app_key, sender, content)
# ─────────────────────────────────────────────────────────────────────────────

# "Nova notificacao de WhatsApp, Mae, Kkkkk.." or English variant
_RX_NOTIF_SUMMARY = re.compile(
    r"(?:nova notifica[c\u00e7][a\u00e3]o de|new notification from)\s+"
    r"(?P<app>\S+?)[,;]\s*(?P<rest>.+)",
    re.I,
)
# Trailing counter: "1 de 1", ". 1 de 1", ", 1 de 1"
_RX_COUNTER = re.compile(r"[.,]?\s*\d+\s+(?:de|of)\s+\d+\s*$", re.I)
# WhatsApp inline reply UI noise
# WhatsApp inline reply UI noise + badge "X mensagens nao lidas"
_RX_WA_NOISE = re.compile(
    r"[.\s]*(?:entrada de texto|text input|type a reply|resposta inline)[.\s]*"
    r"|\s*✉\s*\d*\s*(?:mensagens?\s*n[ãa]o\s*lidas?)?"
    r"|\s*\d+\s+mensagens?\s+n[ãa]o\s+lidas?",
    re.I | re.UNICODE,
)
_SYSTEM_STRINGS = {
    "nova notifica\u00e7\u00e3o", "nova notificacao",
    "new notification",
    "configura\u00e7\u00f5es para esta notifica\u00e7\u00e3o",
    "configuracoes para esta notificacao",
    "mova esta notifica\u00e7\u00e3o para o centro de notifica\u00e7\u00f5es",
    "mova esta notificacao para o centro de notificacoes",
    "move this notification to notification center",
    "dismiss", "fechar",
    "digit uma resposta", "digite uma resposta",
    "type a reply", "enviar", "send",
}


def _clean_discord_channel_name(sender: str) -> str:
    """
    Extrai o nome limpo do canal Discord a partir de formatos como:
      'ServerName | #general'  → 'general'
      '#general'               → 'general'
      '🎮│general'             → '🎮│general'  (já é um nome, mantém)
    O nome retornado é colado via clipboard no Quick Switcher, então
    chars especiais (emojis, Unicode) são totalmente suportados.
    """
    # Remove prefixo de servidor "Server | #channel" → "#channel"
    if " | " in sender:
        sender = sender.rsplit(" | ", 1)[-1]
    # Remove chars direcionais Unicode e '#' do início
    sender = re.sub(r"^[\u2068\u2069#\s]+", "", sender).strip()
    return sender or "Desconhecido"


def _clean_content(content: str) -> str:
    content = _RX_COUNTER.sub("", content).strip()
    content = _RX_WA_NOISE.sub("", content).strip()
    return content.strip(". ")


def _parse_notif_texts(texts: list) -> tuple:
    """
    Returns (app_key, sender, content) from UIAutomation texts of a toast.
    app_key is None when no monitored app is detected.
    """
    joined_low = " ".join(texts).lower()

    app_key = None
    for kw, key in _APP_KEYWORDS:
        if kw in joined_low:
            app_key = key
            break
    if not app_key:
        return None, "", ""

    # Primary path: structured summary line from Windows 11 toast host
    for t in texts:
        m = _RX_NOTIF_SUMMARY.search(t)
        if m:
            rest = m.group("rest")
            parts = [p.strip() for p in rest.split(",", 1)]
            sender  = parts[0] if parts else "Desconhecido"
            content = _clean_content(parts[1]) if len(parts) > 1 else ""

            # Discord: bloqueia @everyone/@here; permite DMs e @menções diretas
            if app_key == "discord":
                if _RX_DISCORD_MASS_MENTION.search(content):
                    return None, "", ""   # @everyone ou @here — ignora
                if _RX_DISCORD_SERVER.search(sender):
                    # Notificação de canal de servidor → limpa nome para navegação
                    sender = _clean_discord_channel_name(sender)

            return app_key, sender, content

    # Fallback: pick first non-system text as sender, second as content
    useful = [
        t for t in texts
        if t.lower() not in _SYSTEM_STRINGS
        and "\ue10c" not in t
        and "\ue711" not in t
        and not any(kw == t.lower() for kw, _ in _APP_KEYWORDS)
    ]
    sender  = useful[0] if useful else "Desconhecido"
    content = _clean_content(useful[1]) if len(useful) > 1 else ""

    # Discord: bloqueia @everyone/@here; permite DMs e @menções diretas (fallback)
    if app_key == "discord":
        if _RX_DISCORD_MASS_MENTION.search(content):
            return None, "", ""   # @everyone ou @here — ignora
        if _RX_DISCORD_SERVER.search(sender):
            sender = _clean_discord_channel_name(sender)

    return app_key, sender, content


# ─────────────────────────────────────────────────────────────────────────────
# InstagramMonitor  – polling de DMs via instagrapi (sem toasts)
# ─────────────────────────────────────────────────────────────────────────────

class InstagramMonitor:
    """
    Verifica novas mensagens diretas do Instagram a cada _POLL_SEC seconds.
    Usa o mesmo _DebounceBuffer / cooldown que o NotificationMonitor de toasts,
    portanto respeita os 3 minutos de cooldown por remetente.
    """

    _POLL_SEC = 10  # intervalo de polling

    def __init__(self, username: str, password: str,
                 callback: Callable[[str, str, list[dict]], None],
                 totp_seed: str = ""):
        self._username  = username
        self._password  = password
        self._totp_seed = totp_seed
        self._buffer    = _DebounceBuffer(callback)
        self._seen_ids: set[str] = set()
        self._stop_evt  = threading.Event()
        self._thread: threading.Thread | None = None

    # ── public ───────────────────────────────────────────────────────────────

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="ig-dm-monitor"
        )
        self._thread.start()
        return True

    def stop(self):
        self._stop_evt.set()
        self._buffer.clear()

    def reset_sender(self, app_key: str, sender: str):
        self._buffer.reset_sender(app_key, sender)

    def activate_convo(self, app_key: str, sender: str):
        """Ativa modo conversa (leitura automática por 15 min) para este remetente."""
        self._buffer.activate_convo(app_key, sender)

    def deactivate_convo(self, app_key: str, sender: str):
        self._buffer.deactivate_convo(app_key, sender)

    def is_convo_active(self, app_key: str, sender: str) -> bool:
        return self._buffer.is_convo_active(app_key, sender)

    def get_unread(self, app_key: str | None = None) -> dict[tuple, list[dict]]:
        """Return and clear accumulated recent messages."""
        return self._buffer.get_unread(app_key)

    # ── internals ────────────────────────────────────────────────────────────

    # ── helpers para item_type → (mtype, content) ────────────────────────────
    _AUDIO_TYPES  = {"voice_media", "audio"}
    _MEDIA_TYPES  = {
        "clip", "felix_share", "reel_share", "media_share",
        "story_share", "animated_media",
    }
    _XMA_TYPES    = {
        "xma_media_share", "xma_reel_share", "xma_story_share",
        "xma_clip", "xma_video",
    }

    @staticmethod
    def _classify_msg(item_type: str, text: str | None):
        """Return (mtype, content) for a DM item."""
        if item_type in InstagramMonitor._AUDIO_TYPES:
            return "audio", "[áudio]"
        if item_type in InstagramMonitor._MEDIA_TYPES:
            return "media", "[mídia/vídeo]"
        if item_type in InstagramMonitor._XMA_TYPES:
            return "media", "[mídia compartilhada]"
        content = text or ""
        if not content and item_type not in ("text", "link"):
            return "media", f"[{item_type}]"
        return "text", content

    # ── raw JSON fallback ────────────────────────────────────────────────────

    def _poll_raw(self, cl) -> list[dict]:
        """
        Busca DMs via API bruta e retorna lista de dicts simplificados:
        [{"sender": "username", "messages": [{"id": ..., "item_type": ..., "text": ..., "user_id": ...}, ...]}]
        Nunca toca em Pydantic — imune a ValidationError.
        """
        raw = cl.private_request("direct_v2/inbox/", params={"limit": "20"})
        results = []
        for raw_th in raw.get("inbox", {}).get("threads", []):
            users = raw_th.get("users") or []
            if not users:
                continue
            sender = users[0].get("username", "Desconhecido")
            msgs = []
            for item in raw_th.get("items", []):
                msgs.append({
                    "id":        str(item.get("item_id", "")),
                    "item_type": item.get("item_type", "text") or "text",
                    "text":      item.get("text"),
                    "user_id":   str(item.get("user_id", "")),
                })
            results.append({"sender": sender, "messages": msgs})
        return results

    # ── main loop ────────────────────────────────────────────────────────────

    def _poll_loop(self):
        seed = True   # primeira rodada: só marca mensagens existentes como vistas
        cl   = None

        while not self._stop_evt.is_set():
            try:
                if cl is None:
                    cl = self._get_client()

                # ----------------------------------------------------------
                # Tenta a API Pydantic; se der ValidationError, cai no JSON bruto.
                # ----------------------------------------------------------
                use_raw = False
                try:
                    threads_obj = cl.direct_threads(amount=20) or []
                except Exception as _parse_err:
                    if "validation error" in str(_parse_err).lower():
                        use_raw = True
                    else:
                        raise

                new_by_sender: dict[str, list[dict]] = {}

                if use_raw:
                    # ---------- caminho JSON bruto ----------
                    raw_threads = self._poll_raw(cl)
                    my_uid = str(cl.user_id)
                    for th in raw_threads:
                        sender_name = th["sender"]
                        for m in th["messages"]:
                            msg_id = m["id"]
                            if seed:
                                self._seen_ids.add(msg_id)
                                continue
                            if msg_id in self._seen_ids:
                                continue
                            if m["user_id"] == my_uid:
                                self._seen_ids.add(msg_id)
                                continue
                            self._seen_ids.add(msg_id)
                            mtype, content = self._classify_msg(m["item_type"], m["text"])
                            new_by_sender.setdefault(sender_name, []).append(
                                {"type": mtype, "content": content}
                            )
                else:
                    # ---------- caminho Pydantic normal ----------
                    for thread in threads_obj:
                        if not thread.users:
                            continue
                        sender_name = thread.users[0].username
                        for msg in thread.messages:
                            msg_id = str(msg.id)
                            if seed:
                                self._seen_ids.add(msg_id)
                                continue
                            if msg_id in self._seen_ids:
                                continue
                            if str(getattr(msg, "user_id", "")) == str(cl.user_id):
                                self._seen_ids.add(msg_id)
                                continue
                            self._seen_ids.add(msg_id)
                            item_type = getattr(msg, "item_type", "text") or "text"
                            mtype, content = self._classify_msg(
                                item_type, getattr(msg, "text", None)
                            )
                            new_by_sender.setdefault(sender_name, []).append(
                                {"type": mtype, "content": content}
                            )

                if seed:
                    seed = False
                    print(f"[IG] Monitor iniciado — {len(self._seen_ids)} msgs existentes ignoradas.")
                else:
                    for sname, msgs_list in new_by_sender.items():
                        print(f"[IG] Nova DM de @{sname}: {msgs_list}")
                        for m in msgs_list:
                            self._buffer.add("instagram", sname, m["type"], m["content"])

            except Exception as e:
                err_str = str(e)
                # Erros de parsing/validação NÃO devem resetar o client
                if "validation error" in err_str.lower():
                    print(f"[IG] Aviso parse (ignorado): {e}")
                    self._stop_evt.wait(self._POLL_SEC)
                    continue
                print(f"[IG] Erro no poll: {e}")

                # Invalida o singleton em memória (NÃO apaga sessão salva)
                from comandos.msg_sender import _ig_invalidar
                _ig_invalidar()
                cl = None

                if "login_required" in err_str.lower():
                    print("[IG] Sessão expirada — re-login será tentado na próxima rodada.")
                    self._stop_evt.wait(60)  # espera 1 min antes de re-login
                    continue
                elif "Two-factor" in err_str or "verification_code" in err_str:
                    if not self._totp_seed:
                        print(
                            "[IG] 2FA necessário mas INSTAGRAM_TOTP_SEED não está configurado.\n"
                            "[IG] Preencha INSTAGRAM_TOTP_SEED no config.py com a chave base32\n"
                            "[IG] do seu app autenticador e reinicie o JARVIS.\n"
                            "[IG] Monitor de Instagram DESATIVADO."
                        )
                        self._stop_evt.set()
                        return
                    print("[IG] Código 2FA rejeitado — tentando novamente em 30s.")
                    self._stop_evt.wait(30)
                    continue
                elif "security code" in err_str.lower() or "check the security" in err_str.lower():
                    print("[IG] TOTP rejeitado. Tentando novamente em 30s.")
                    self._stop_evt.wait(30)
                    continue
                elif any(kw in err_str for kw in (
                    "blacklist", "challenge", "We can send you", "IP address",
                )):
                    print("[IG] IP bloqueado. Pausando poll por 5 minutos.")
                    self._stop_evt.wait(300)
                    continue

            self._stop_evt.wait(self._POLL_SEC)

    def _get_client(self):
        # Import local para não criar dependência circular no topo do módulo
        from comandos.msg_sender import _ig_cliente
        return _ig_cliente(self._username, self._password, self._totp_seed)
