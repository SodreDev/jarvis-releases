"""Oráculo golden: cópias LITERAIS de trechos do commit `31bc0ce` (fim da
fase 1 — base da fase 2, ver docs/linux-port/FILA-fase2-executor.md),
embrulhadas em funções que recebem fakes/parâmetros injetados em vez de
ler `os.environ`, `ctypes.windll` ou chamar as APIs do SO direto.

NUNCA editar este arquivo fora de uma emenda do arquiteto (mesma regra da
fase 1, FILA §Protocolo item 5: "tests/golden/ ... são do qa" e o
executor não edita). É o oráculo contra o qual os testes C/K de
F2-01 (hotkeys), F2-02 (tray), F2-03 (volume), F2-04 (clipboard),
F2-06 (open_path), F2-07 (session), F2-08 (media) e F2-09 (restart_self)
comparam o comportamento novo — cada função entra sob demanda, na tarefa
G-A/G-B/G-C correspondente (ver FILA), sempre ANTES do executor mexer no
código de produção daquela capacidade.

Preenchido incrementalmente, tarefa G-A da FILA (F2-06 open_path,
F2-09 restart_self, F2-07 session e F2-04 clipboard) — cada função cita
a âncora exata em `main.py`/`comandos/*.py`/`core/win_locale.py` de onde
o trecho foi copiado (linha e nome), igual a `legacy_1c32e38.py` da
fase 1.
"""
from __future__ import annotations


# ── F2-06: open_path — main.py:8970/8991 (_os.startfile) e :2928 (notepad) ──

# (arquivo, linha, expressão-fonte do argumento) em 31bc0ce — usado pelo
# AST de tests/golden/test_startfile_callsites.py para conferir que cada
# call site continua passando A MESMA expressão de argumento, seja para
# `os.startfile`/`_os.startfile` (hoje) ou para `_open_path` (depois de
# F2-06).
OPEN_PATH_CALL_SITES: list[tuple[str, int, str]] = [
    ("main.py", 8970, "path"),
    ("main.py", 8991, "caminho"),
    ("comandos/executor.py", 27, "url"),
    ("comandos/games_ctrl.py", 27, "target"),
    ("comandos/msg_sender.py", 432, "uri"),
    ("comandos/msg_sender.py", 526, "uri"),
    ("comandos/msg_sender.py", 578, '"discord://"'),
    ("comandos/msg_sender.py", 709, '"whatsapp://"'),
    ("comandos/janela_ctrl.py", 248, "uri"),
    ("comandos/janela_ctrl.py", 260, "cmd"),
    ("comandos/janela_ctrl.py", 640, "caminho"),
    ("comandos/tool_registry.py", 1761, "caminho"),
    ("comandos/tool_registry.py", 2089, "path"),
    ("comandos/tool_registry.py", 2199, "path"),
    ("comandos/tool_registry.py", 2355, "path"),
    ("comandos/tool_registry.py", 2389, "pdf"),
    ("comandos/tool_registry.py", 2445, "path"),
]

# main.py:2928 — `subprocess.Popen(["notepad.exe", path], close_fds=True)`
NOTEPAD_CALL_SITE_LINE = 2928
NOTEPAD_CALL_SITE_ARGS = ['"notepad.exe"', "path"]  # expressões-fonte exatas


def legacy_open_path_windows(startfile_fn, target):
    """`_os.startfile(X)` em `main.py:8970`/`:8991` — chamada única,
    devolve o que `startfile_fn` devolver e propaga exceção (os call
    sites já tratam com `try/except`)."""
    return startfile_fn(target)


def legacy_open_text_file_windows(popen_fn, path):
    """`main.py:2928` — `subprocess.Popen(["notepad.exe", path],
    close_fds=True)`, literal."""
    return popen_fn(["notepad.exe", path], close_fds=True)


# ── F2-09: restart_self — main.py:6461-6491 (_fazer_restart) ──


def legacy_fazer_restart(*, frozen: bool, sys_executable: str, root: str, popen_fn):
    """Corpo de `_fazer_restart` (`main.py:6461-6489`), sem o
    `time.sleep(1.2)`/`self._window.destroy()`/`os._exit(0)` (efeitos
    colaterais que não cabem num oráculo puro — só a decisão de comando).
    Devolve `(args, kwargs)` passados a `popen_fn`.
    """
    if frozen:
        return popen_fn([sys_executable])

    import ntpath  # não os.path: em host Linux junta com "/", main.py roda no Windows

    venv_activate = ntpath.join(root, ".venv", "Scripts", "Activate.ps1")
    main_path = ntpath.join(root, "main.py")
    ps_cmd = (
        f"Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force; "
        f"& '{venv_activate}'; "
        f"Clear-Host; "
        f"Write-Host '  J.A.R.V.I.S. — iniciando...' -ForegroundColor Cyan; "
        f"& python '{main_path}'"
    )
    return popen_fn(
        ["powershell", "-NoLogo", "-NoExit", "-Command", ps_cmd],
        creationflags=0x10,  # subprocess.CREATE_NEW_CONSOLE
    )


# ── F2-07: session — main.py:7206 (_idle_seconds) e core/win_locale.py ──


def legacy_idle_seconds(ctypes_mod) -> float:
    """`main.py:7206-7224` (`_idle_seconds`), literal — usa
    `ctypes.windll` (compartilhado, não o WinDLL privado da F1-12) e
    devolve `0.0` em qualquer exceção."""
    try:
        class _LASTINPUTINFO(ctypes_mod.Structure):
            _fields_ = [("cbSize", ctypes_mod.c_uint), ("dwTime", ctypes_mod.c_uint)]

        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes_mod.sizeof(lii)
        ctypes_mod.windll.user32.GetLastInputInfo(ctypes_mod.byref(lii))
        millis = ctypes_mod.windll.kernel32.GetTickCount() - lii.dwTime
        return max(0.0, millis / 1000.0)
    except Exception:
        return 0.0


_WIN_TZ_TO_IANA = {
    "E. South America Standard Time": "America/Sao_Paulo",
    "UTC": "UTC",
}  # subconjunto de core/win_locale.py:_WIN_TZ_TO_IANA — só o que os testes usam


def legacy_get_timezone_name(winreg_mod, tzname: tuple[str, str]) -> str:
    """`core/win_locale.py:get_timezone_name`/`_read_winreg_tz_name`,
    literal: winreg → mapa IANA; se não achar, `time.tzname[0]`; se nada,
    `"UTC"`."""
    win_name = None
    try:
        key = winreg_mod.OpenKey(
            winreg_mod.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation",
        )
        try:
            val, _ = winreg_mod.QueryValueEx(key, "TimeZoneKeyName")
            win_name = val.strip()
        finally:
            winreg_mod.CloseKey(key)
    except Exception:
        win_name = None

    if win_name and win_name in _WIN_TZ_TO_IANA:
        return _WIN_TZ_TO_IANA[win_name]
    try:
        return tzname[0]
    except Exception:
        return "UTC"


def legacy_get_locale(getdefaultlocale_fn) -> str:
    """`core/win_locale.py:get_locale`, literal: `locale.getdefaultlocale()`
    → `"pt_BR"` vira `"pt-BR"`; qualquer falha → `"pt-BR"`."""
    try:
        loc, _enc = getdefaultlocale_fn()
        if loc:
            return loc.replace("_", "-")
    except Exception:
        pass
    return "pt-BR"


# ── F2-04: clipboard — comandos/system_ctrl.py e clipboard_hist_ctrl.py ──


def legacy_get_clipboard(pyperclip_mod) -> str:
    """`comandos/system_ctrl.py:250-255` (`get_clipboard`), literal."""
    try:
        return pyperclip_mod.paste() or ""
    except Exception:
        return ""


def legacy_set_clipboard(pyperclip_mod, texto: str) -> str:
    """`comandos/system_ctrl.py:258-264` (`set_clipboard`), literal."""
    try:
        pyperclip_mod.copy(texto)
        return "Copiado para a área de transferência, Senhor."
    except Exception as e:
        return f"Não foi possível copiar: {e}"


CLIPBOARD_HISTORY_MAX = 50  # comandos/clipboard_hist_ctrl.py:_MAX


def legacy_monitor_loop_iteration(get_clipboard_text_fn, history: list, last):
    """Um ciclo do corpo de `_monitor_loop` (`clipboard_hist_ctrl.py:76-89`),
    sem o `while`/`time.sleep(0.8)` (efeito colateral) — dedupe contra
    `last` E contra o topo de `history`, `strip() > 1` char, limite
    `CLIPBOARD_HISTORY_MAX`. Devolve o novo `last` (mutando `history` in
    place, como o original faz em `_history`)."""
    try:
        txt = get_clipboard_text_fn()
        if txt and txt != last and len(txt.strip()) > 1:
            last = txt
            if not history or history[-1] != txt:
                history.append(txt)
                if len(history) > CLIPBOARD_HISTORY_MAX:
                    history.pop(0)
    except Exception:
        pass
    return last


# ── F2-03: volume/mic — comandos/system_ctrl.py:92-191 (pycaw) ──


def legacy_discover_audio_volume_interface(*, audio_utilities, iaudio_endpoint_volume, comtypes_mod, cast_fn, pointer_fn, clsctx_all):
    """`system_ctrl.py:_get_audio_volume` (`:92-118`), literal: inicializa
    COM, pega os alto-falantes, tolera o wrapper `AudioDevice` (`_dev`)
    além do `IMMDevice` puro, e ativa a interface de volume."""
    try:
        comtypes_mod.CoInitialize()
    except OSError:
        pass

    speakers = audio_utilities.GetSpeakers()
    if not hasattr(speakers, "Activate"):
        dev = getattr(speakers, "_dev", None)
        if dev is not None and hasattr(dev, "Activate"):
            speakers = dev
        else:
            raise RuntimeError(f"Dispositivo de áudio incompatível: {type(speakers).__name__}")

    interface = speakers.Activate(iaudio_endpoint_volume._iid_, clsctx_all, None)
    return cast_fn(interface, pointer_fn(iaudio_endpoint_volume))


def legacy_discover_mic_volume_interface(*, audio_utilities, iaudio_endpoint_volume, comtypes_mod, cast_fn, pointer_fn, clsctx_all):
    """`system_ctrl.py:_get_mic_volume` (`:144-170`), literal — igual ao
    de saída, mas com `GetMicrophone()` e `mic is None` levantando."""
    try:
        comtypes_mod.CoInitialize()
    except OSError:
        pass

    mic = audio_utilities.GetMicrophone()
    if mic is None:
        raise RuntimeError("Nenhum microfone encontrado no sistema.")
    if not hasattr(mic, "Activate"):
        dev = getattr(mic, "_dev", None)
        if dev is not None and hasattr(dev, "Activate"):
            mic = dev
        else:
            raise RuntimeError(f"Dispositivo de microfone incompatível: {type(mic).__name__}")

    interface = mic.Activate(iaudio_endpoint_volume._iid_, clsctx_all, None)
    return cast_fn(interface, pointer_fn(iaudio_endpoint_volume))


def legacy_set_volume(get_audio_volume_fn, nivel: int) -> str:
    """`system_ctrl.py:set_volume` (`:121-128`), literal — clampa 0-100."""
    nivel = max(0, min(100, nivel))
    try:
        vol = get_audio_volume_fn()
        vol.SetMasterVolumeLevelScalar(nivel / 100.0, None)
        return f"Volume do sistema ajustado para {nivel}%, Senhor."
    except Exception as e:
        return f"Não foi possível ajustar o volume: {e}"


def legacy_get_volume(get_audio_volume_fn) -> str:
    """`system_ctrl.py:get_volume` (`:131-137`), literal."""
    try:
        vol = get_audio_volume_fn()
        pct = int(vol.GetMasterVolumeLevelScalar() * 100)
        return f"Volume atual do sistema: {pct}%, Senhor."
    except Exception as e:
        return f"Não foi possível obter o volume: {e}"


def legacy_set_mic_volume(get_mic_volume_fn, nivel: int) -> str:
    """`system_ctrl.py:set_mic_volume` (`:173-181`), literal."""
    nivel = max(0, min(100, nivel))
    try:
        vol = get_mic_volume_fn()
        vol.SetMasterVolumeLevelScalar(nivel / 100.0, None)
        return f"Volume do microfone ajustado para {nivel}%, Senhor."
    except Exception as e:
        return f"Não foi possível ajustar o volume do microfone: {e}"


def legacy_get_mic_volume(get_mic_volume_fn) -> str:
    """`system_ctrl.py:get_mic_volume` (`:184-191`), literal."""
    try:
        vol = get_mic_volume_fn()
        pct = int(vol.GetMasterVolumeLevelScalar() * 100)
        return f"Volume atual do microfone: {pct}%, Senhor."
    except Exception as e:
        return f"Não foi possível obter o volume do microfone: {e}"


# ── F2-08: mídia — comandos/midia_ctrl.py:18-147 (teclas virtuais + SMTC/PowerShell) ──

VK_MEDIA_PLAY_PAUSE = 0xB3
VK_MEDIA_STOP = 0xB4
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF


def legacy_press_key(keybd_event_fn, vk: int, *, sleep_fn=lambda s: None) -> None:
    """`midia_ctrl.py:_press_key` (`:47-51`), literal — down, `sleep(0.05)`
    (injetável para espionar sem esperar de verdade), up com
    `KEYEVENTF_KEYUP=0x0002`."""
    keybd_event_fn(vk, 0, 0, 0)
    sleep_fn(0.05)
    keybd_event_fn(vk, 0, 0x0002, 0)


def legacy_play_pause(keybd_event_fn, **kw) -> str:
    legacy_press_key(keybd_event_fn, VK_MEDIA_PLAY_PAUSE, **kw)
    return "Play/Pause enviado, senhor."


def legacy_parar(keybd_event_fn, **kw) -> str:
    legacy_press_key(keybd_event_fn, VK_MEDIA_STOP, **kw)
    return "Mídia parada, senhor."


def legacy_proxima_faixa(keybd_event_fn, **kw) -> str:
    legacy_press_key(keybd_event_fn, VK_MEDIA_NEXT_TRACK, **kw)
    return "Próxima faixa, senhor."


def legacy_faixa_anterior(keybd_event_fn, **kw) -> str:
    legacy_press_key(keybd_event_fn, VK_MEDIA_PREV_TRACK, **kw)
    return "Faixa anterior, senhor."


def legacy_mutar(keybd_event_fn, **kw) -> str:
    legacy_press_key(keybd_event_fn, VK_VOLUME_MUTE, **kw)
    return "Volume mutado/desmutado, senhor."


def legacy_volume_up(keybd_event_fn, steps: int = 3, **kw) -> str:
    for _ in range(steps):
        legacy_press_key(keybd_event_fn, VK_VOLUME_UP, **kw)
    return f"Volume aumentado {steps} nível(is), senhor."


def legacy_volume_down(keybd_event_fn, steps: int = 3, **kw) -> str:
    for _ in range(steps):
        legacy_press_key(keybd_event_fn, VK_VOLUME_DOWN, **kw)
    return f"Volume reduzido {steps} nível(is), senhor."


def legacy_get_media_info_ps(run_fn) -> dict:
    """`midia_ctrl.py:_get_media_info_ps` (`:97-125`), literal — só o
    parsing do stdout do PowerShell (`run_fn` substitui `subprocess.run`,
    o script em si não muda)."""
    try:
        r = run_fn(["powershell", "-NoProfile", "-Command", "<script SMTC>"], capture_output=True, text=True, timeout=8)
        line = r.stdout.strip()
        if line and line != "NULL":
            parts = line.split("|", 3)
            return {
                "title": parts[0] if len(parts) > 0 else "",
                "artist": parts[1] if len(parts) > 1 else "",
                "status": parts[2] if len(parts) > 2 else "",
                "app": parts[3] if len(parts) > 3 else "",
            }
    except Exception:
        pass
    return {}


def legacy_o_que_esta_tocando(run_fn) -> str:
    """`midia_ctrl.py:o_que_esta_tocando` (`:128-147`), literal — mapa de
    status e formatação da frase, com/sem artista."""
    info = legacy_get_media_info_ps(run_fn)
    if not info or not info.get("title"):
        return "Nenhuma mídia em reprodução detectada, senhor."
    titulo = info.get("title", "?")
    artista = info.get("artist", "")
    status = info.get("status", "")
    app = info.get("app", "").split("!")[-1] or "reprodutor desconhecido"

    status_map = {
        "Playing": "tocando", "Paused": "pausado",
        "Stopped": "parado", "0": "parado", "1": "parado",
        "3": "tocando", "4": "pausado",
    }
    estado = status_map.get(status, status.lower())

    if artista:
        return f"Está {estado} '{titulo}' — {artista}, via {app}, senhor."
    return f"Está {estado} '{titulo}' via {app}, senhor."


__all__ = [
    "OPEN_PATH_CALL_SITES",
    "NOTEPAD_CALL_SITE_LINE",
    "NOTEPAD_CALL_SITE_ARGS",
    "legacy_open_path_windows",
    "legacy_open_text_file_windows",
    "legacy_fazer_restart",
    "legacy_idle_seconds",
    "legacy_get_timezone_name",
    "legacy_get_locale",
    "legacy_get_clipboard",
    "legacy_set_clipboard",
    "CLIPBOARD_HISTORY_MAX",
    "legacy_monitor_loop_iteration",
    "legacy_discover_audio_volume_interface",
    "legacy_discover_mic_volume_interface",
    "legacy_set_volume",
    "legacy_get_volume",
    "legacy_set_mic_volume",
    "legacy_get_mic_volume",
    "VK_MEDIA_PLAY_PAUSE",
    "VK_MEDIA_STOP",
    "VK_MEDIA_NEXT_TRACK",
    "VK_MEDIA_PREV_TRACK",
    "VK_VOLUME_MUTE",
    "VK_VOLUME_DOWN",
    "VK_VOLUME_UP",
    "legacy_press_key",
    "legacy_play_pause",
    "legacy_parar",
    "legacy_proxima_faixa",
    "legacy_faixa_anterior",
    "legacy_mutar",
    "legacy_volume_up",
    "legacy_volume_down",
    "legacy_get_media_info_ps",
    "legacy_o_que_esta_tocando",
    "legacy_is_g_key",
    "legacy_shift_keys",
    "legacy_start_keyboard_listener",
    "legacy_start_global_hotkeys",
    "legacy_ptt_iniciar",
    "legacy_ptt_finalizar",
    "legacy_criar_tray_menu",
    "legacy_criar_tray_icon",
]


# ── F2-01: hotkeys — main.py:201/260/11647-11699/11845-11911 ──


def legacy_is_g_key(key) -> bool:
    """`main.py:260-265` (`_is_g_key`), literal."""
    try:
        return key.char is not None and key.char.lower() == "g"
    except AttributeError:
        return False


def legacy_shift_keys(Key):
    """`main.py:201` (`_SHIFT_KEYS`), literal — `Key` é o
    `pynput.keyboard.Key` (falso ou real)."""
    return {Key.shift, Key.shift_r, Key.shift_l} if Key is not None else set()


def legacy_start_keyboard_listener(keyboard_mod, *, has_feature: bool, on_press, on_release, print_fn=print):
    """`main.py:11647-11656` (`_start_keyboard_listener`), literal.
    Devolve o listener criado (ou `None` se o portão barrar)."""
    if keyboard_mod is None or not has_feature:
        print_fn("[PTT] Atalho global indisponível nesta sessão — use o botão de microfone ou a wake word.")
        return None
    listener = keyboard_mod.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    return listener


def legacy_start_global_hotkeys(
    global_hotkeys_cls,
    *,
    has_feature: bool,
    raw: dict,
    hotkey_cmds: dict,
    make_handler,
    print_fn=print,
    log_info=lambda _msg: None,
):
    """`main.py:11666-11698` (`_start_global_hotkeys`), literal: filtra
    `raw` (combo -> ação) pelo mapa `_HOTKEY_CMDS`, ignora ação
    desconhecida, monta `handlers` e instancia `GlobalHotKeys(handlers)`.
    `make_handler(cmd)` substitui a closure `_handler` (o corpo dela é
    UI/thread, fora do escopo do oráculo)."""
    if not has_feature:
        print_fn("[PTT] Atalho global indisponível nesta sessão — use o botão de microfone ou a wake word.")
        return None
    if not raw:
        return None
    handlers: dict = {}
    for combo, acao in raw.items():
        cmd = hotkey_cmds.get(acao)
        if not cmd:
            print_fn(f"[HOTKEYS] Ação desconhecida ignorada: {acao!r}")
            continue
        handlers[combo] = make_handler(cmd)
    if not handlers:
        return None
    listener = global_hotkeys_cls(handlers)
    listener.start()
    log_info(f"HOTKEYS: {len(handlers)} atalho(s) registrado(s): {', '.join(handlers)}")
    return listener


def legacy_ptt_iniciar(*, set_recording, notify_recording, clear_mic_frames, print_fn, set_status, after_fn, stop_tts, start_thread):
    """Corpo do ramo PTT de `_on_key_press` (`main.py:11868-11875`),
    extraído literalmente para `_ptt_iniciar` (F2-01). Cada efeito
    colateral é uma função injetada, chamada NA MESMA ORDEM do original."""
    set_recording(True)
    notify_recording(True)
    clear_mic_frames()
    print_fn("[PTT] Gravando...")
    set_status("▤  OUVINDO...  (Solte G para enviar)", "_RED")
    after_fn()
    stop_tts()
    start_thread()


def legacy_ptt_finalizar(*, set_recording, notify_recording, print_fn, set_status, after_fn, get_frames, start_thread_with_frames):
    """Corpo do ramo PTT de `_on_key_release` (`main.py:11901-11910`),
    extraído literalmente para `_ptt_finalizar` (F2-01)."""
    set_recording(False)
    notify_recording(False)
    print_fn("[PTT] Parou. Enviando...")
    set_status("⟳  Processando áudio...", "_CYAN")
    after_fn()
    frames = get_frames()
    if frames:
        start_thread_with_frames(frames)
    else:
        set_status("PRONTO  |  Segure Shift+G para falar", "_TEXT_DIM")


# ── F2-02: tray — main.py:13361-13404 (_criar_tray_icon, pystray) ──


def legacy_criar_tray_menu(pystray_mod, *, on_restaurar, on_briefing, on_encerrar):
    """`main.py:13383-13388`, literal: 4 itens, `default=True` no
    primeiro, `SEPARATOR` antes do último."""
    return pystray_mod.Menu(
        pystray_mod.MenuItem("Restaurar JARVIS", on_restaurar, default=True),
        pystray_mod.MenuItem("Briefing", on_briefing),
        pystray_mod.Menu.SEPARATOR,
        pystray_mod.MenuItem("Encerrar", on_encerrar),
    )


def legacy_criar_tray_icon(pystray_mod, image, menu):
    """`main.py:13390-13404`, literal: `Icon("JARVIS", img, "J.A.R.V.I.S.",
    menu)`, começa com `.visible = False`, `.run` roda numa thread daemon
    (a thread em si não é responsabilidade do oráculo — só a construção)."""
    icon = pystray_mod.Icon("JARVIS", image, "J.A.R.V.I.S.", menu)
    icon.visible = False
    return icon
