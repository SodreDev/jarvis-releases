"""C — caracterização (F2-01): hotkeys pynput (Listener, GlobalHotKeys,
Shift+G, PTT) continuam idênticos depois de `_ptt_iniciar`/`_ptt_finalizar`
saírem para funções próprias e o adapter `common/pynput_hotkeys.py` entrar.
"""
import types

from tests.golden.legacy_31bc0ce import (
    legacy_is_g_key,
    legacy_ptt_finalizar,
    legacy_ptt_iniciar,
    legacy_shift_keys,
    legacy_start_global_hotkeys,
    legacy_start_keyboard_listener,
)


def _fake_key(char):
    return types.SimpleNamespace(char=char)


def test_is_g_key_lowercase():
    assert legacy_is_g_key(_fake_key("g")) is True


def test_is_g_key_uppercase():
    assert legacy_is_g_key(_fake_key("G")) is True


def test_is_g_key_other_char():
    assert legacy_is_g_key(_fake_key("a")) is False


def test_is_g_key_special_key_without_char_attr():
    class _Special:
        pass

    assert legacy_is_g_key(_Special()) is False


def test_shift_keys_built_from_key_enum():
    Key = types.SimpleNamespace(shift="SHIFT", shift_r="SHIFT_R", shift_l="SHIFT_L")
    assert legacy_shift_keys(Key) == {"SHIFT", "SHIFT_R", "SHIFT_L"}


def test_shift_keys_empty_when_key_is_none():
    assert legacy_shift_keys(None) == set()


def test_start_keyboard_listener_creates_and_starts():
    calls = []

    class _FakeListener:
        def __init__(self, on_press, on_release):
            self.on_press = on_press
            self.on_release = on_release

        def start(self):
            calls.append("start")

    keyboard_mod = types.SimpleNamespace(Listener=_FakeListener)
    on_press, on_release = (lambda k: None), (lambda k: None)
    listener = legacy_start_keyboard_listener(
        keyboard_mod, has_feature=True, on_press=on_press, on_release=on_release
    )
    assert listener.on_press is on_press
    assert listener.on_release is on_release
    assert calls == ["start"]


def test_start_keyboard_listener_blocked_without_feature(capsys):
    listener = legacy_start_keyboard_listener(object(), has_feature=False, on_press=None, on_release=None)
    assert listener is None
    assert "Atalho global indisponível" in capsys.readouterr().out


def test_start_keyboard_listener_blocked_without_pynput():
    assert legacy_start_keyboard_listener(None, has_feature=True, on_press=None, on_release=None) is None


def test_start_global_hotkeys_filters_unknown_action_and_logs(capsys):
    calls = []

    class _FakeGlobalHotKeys:
        def __init__(self, handlers):
            self.handlers = handlers

        def start(self):
            calls.append("start")

    raw = {"<ctrl>+<alt>+j": "screenshot_analise", "<ctrl>+<alt>+x": "acao_desconhecida"}
    hotkey_cmds = {"screenshot_analise": "analise a tela"}
    listener = legacy_start_global_hotkeys(
        _FakeGlobalHotKeys,
        has_feature=True,
        raw=raw,
        hotkey_cmds=hotkey_cmds,
        make_handler=lambda cmd: (lambda: cmd),
    )
    assert set(listener.handlers) == {"<ctrl>+<alt>+j"}
    assert "Ação desconhecida ignorada: 'acao_desconhecida'" in capsys.readouterr().out
    assert calls == ["start"]


def test_start_global_hotkeys_no_raw_returns_none():
    assert (
        legacy_start_global_hotkeys(object, has_feature=True, raw={}, hotkey_cmds={}, make_handler=lambda c: c)
        is None
    )


def test_ptt_iniciar_order_and_arguments():
    calls = []
    legacy_ptt_iniciar(
        set_recording=lambda v: calls.append(("recording", v)),
        notify_recording=lambda v: calls.append(("notify", v)),
        clear_mic_frames=lambda: calls.append("clear"),
        print_fn=lambda s: calls.append(("print", s)),
        set_status=lambda s, c: calls.append(("status", s, c)),
        after_fn=lambda: calls.append("after"),
        stop_tts=lambda: calls.append("stop_tts"),
        start_thread=lambda: calls.append("start_thread"),
    )
    assert calls == [
        ("recording", True),
        ("notify", True),
        "clear",
        ("print", "[PTT] Gravando..."),
        ("status", "▤  OUVINDO...  (Solte G para enviar)", "_RED"),
        "after",
        "stop_tts",
        "start_thread",
    ]


def test_ptt_finalizar_with_frames_starts_thread():
    calls = []
    legacy_ptt_finalizar(
        set_recording=lambda v: calls.append(("recording", v)),
        notify_recording=lambda v: calls.append(("notify", v)),
        print_fn=lambda s: calls.append(("print", s)),
        set_status=lambda s, c: calls.append(("status", s, c)),
        after_fn=lambda: calls.append("after"),
        get_frames=lambda: [1, 2, 3],
        start_thread_with_frames=lambda frames: calls.append(("thread", frames)),
    )
    assert ("thread", [1, 2, 3]) in calls
    assert ("status", "⟳  Processando áudio...", "_CYAN") in calls


def test_ptt_finalizar_without_frames_shows_ready_status():
    status_calls = []
    thread_started = []
    legacy_ptt_finalizar(
        set_recording=lambda v: None,
        notify_recording=lambda v: None,
        print_fn=lambda s: None,
        set_status=lambda s, c: status_calls.append(s),
        after_fn=lambda: None,
        get_frames=lambda: [],
        start_thread_with_frames=lambda frames: thread_started.append(frames),
    )
    assert status_calls == ["⟳  Processando áudio...", "PRONTO  |  Segure Shift+G para falar"]
    assert thread_started == []
