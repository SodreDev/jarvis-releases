"""Feature flags: padrões por kind, invariante do win32 e override JARVIS_FEATURES."""
import pytest

from jarvis.platform.detect import detect
from jarvis.platform.features import ALL_FEATURES, features_for


def _ctx(kind):
    mapa = {
        "win32": ("win32", {}),
        "linux-x11": ("linux", {"DISPLAY": ":0"}),
        "linux-wayland": ("linux", {"WAYLAND_DISPLAY": "wayland-0"}),
        "linux-headless": ("linux", {}),
    }
    sysp, env = mapa[kind]
    return detect(sys_platform=sysp, environ=env, frozen=False)


def test_invariante_win32():
    assert features_for(_ctx("win32"), {}) == ALL_FEATURES


def test_padroes_por_kind():
    assert features_for(_ctx("linux-x11"), {}) == frozenset({"global_hotkeys"})
    assert features_for(_ctx("linux-wayland"), {}) == frozenset()
    assert features_for(_ctx("linux-headless"), {}) == frozenset()


def test_override_add_e_remove():
    got = features_for(_ctx("linux-x11"), {"JARVIS_FEATURES": "+tray,-global_hotkeys"})
    assert got == frozenset({"tray"})


def test_override_nome_desconhecido_avisa_e_ignora():
    with pytest.warns(UserWarning):
        got = features_for(_ctx("linux-wayland"), {"JARVIS_FEATURES": "+tray,+banana"})
    assert got == frozenset({"tray"})


def test_override_nome_sem_sinal_conta_como_add():
    got = features_for(_ctx("linux-headless"), {"JARVIS_FEATURES": "gestures"})
    assert got == frozenset({"gestures"})
