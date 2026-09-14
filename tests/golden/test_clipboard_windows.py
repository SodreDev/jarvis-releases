"""C — caracterização (F2-04): `get_clipboard`/`set_clipboard`
(pyperclip) e o corpo do `_monitor_loop` continuam idênticos no Windows
depois da fachada `Cap.CLIPBOARD` entrar.
"""
import types

from tests.golden.legacy_31bc0ce import (
    CLIPBOARD_HISTORY_MAX,
    legacy_get_clipboard,
    legacy_monitor_loop_iteration,
    legacy_set_clipboard,
)


def test_get_clipboard_returns_pasted_text():
    fake = types.SimpleNamespace(paste=lambda: "texto colado")
    assert legacy_get_clipboard(fake) == "texto colado"


def test_get_clipboard_none_becomes_empty_string():
    fake = types.SimpleNamespace(paste=lambda: None)
    assert legacy_get_clipboard(fake) == ""


def test_get_clipboard_exception_becomes_empty_string():
    def _boom():
        raise RuntimeError("sem clipboard")

    fake = types.SimpleNamespace(paste=_boom)
    assert legacy_get_clipboard(fake) == ""


def test_set_clipboard_success_message():
    copied = []
    fake = types.SimpleNamespace(copy=copied.append)
    msg = legacy_set_clipboard(fake, "olá")
    assert copied == ["olá"]
    assert msg == "Copiado para a área de transferência, Senhor."


def test_set_clipboard_failure_message():
    def _boom(_texto):
        raise RuntimeError("negado")

    fake = types.SimpleNamespace(copy=_boom)
    assert legacy_set_clipboard(fake, "x") == "Não foi possível copiar: negado"


def test_monitor_loop_appends_new_text():
    history = []
    last = legacy_monitor_loop_iteration(lambda: "abc", history, None)
    assert last == "abc"
    assert history == ["abc"]


def test_monitor_loop_ignores_single_char():
    history = []
    last = legacy_monitor_loop_iteration(lambda: "a", history, None)
    assert last is None
    assert history == []


def test_monitor_loop_does_not_repeat_last():
    history = ["abc"]
    last = legacy_monitor_loop_iteration(lambda: "abc", history, "abc")
    assert last == "abc"
    assert history == ["abc"]


def test_monitor_loop_respects_max_history():
    history = [f"item{i}" for i in range(CLIPBOARD_HISTORY_MAX)]
    last = legacy_monitor_loop_iteration(lambda: "novo item", history, None)
    assert last == "novo item"
    assert len(history) == CLIPBOARD_HISTORY_MAX
    assert history[0] == "item1"
    assert history[-1] == "novo item"


def test_monitor_loop_swallows_exception():
    def _boom():
        raise RuntimeError("clipboard indisponível")

    history = []
    last = legacy_monitor_loop_iteration(_boom, history, "prev")
    assert last == "prev"
    assert history == []
