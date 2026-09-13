"""Tabela de detecção de plataforma: sys_platform × environ → kind/source."""
import warnings

import pytest

from jarvis.platform.detect import detect

# (id, sys_platform, environ, kind_esperado, source_esperado)
CASOS = [
    # 1. Windows / não-Linux
    ("windows", "win32", {}, "win32", "os"),
    ("macos", "darwin", {}, "unsupported", "os"),
    ("freebsd", "freebsd13", {}, "unsupported", "os"),
    # 2. Override
    ("override_x11", "linux", {"JARVIS_PLATFORM": "linux-x11"}, "linux-x11", "override"),
    ("override_wayland", "linux", {"JARVIS_PLATFORM": "linux-wayland"}, "linux-wayland", "override"),
    ("override_headless", "linux", {"JARVIS_PLATFORM": "linux-headless"}, "linux-headless", "override"),
    ("override_vence_qt", "linux",
     {"JARVIS_PLATFORM": "linux-x11", "QT_QPA_PLATFORM": "wayland"}, "linux-x11", "override"),
    # 3. QT_QPA_PLATFORM
    ("qt_wayland", "linux", {"QT_QPA_PLATFORM": "wayland"}, "linux-wayland", "qt_qpa"),
    ("qt_wayland_egl", "linux", {"QT_QPA_PLATFORM": "wayland-egl"}, "linux-wayland", "qt_qpa"),
    ("qt_xcb", "linux", {"QT_QPA_PLATFORM": "xcb"}, "linux-x11", "qt_qpa"),
    ("qt_offscreen", "linux", {"QT_QPA_PLATFORM": "offscreen"}, "linux-headless", "qt_qpa"),
    ("qt_minimal", "linux", {"QT_QPA_PLATFORM": "minimal"}, "linux-headless", "qt_qpa"),
    # 4. XDG_SESSION_TYPE + display
    ("xdg_wayland", "linux",
     {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}, "linux-wayland", "xdg_session"),
    ("xdg_x11", "linux",
     {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}, "linux-x11", "xdg_session"),
    ("xdg_wayland_sem_display_cai_pra_display", "linux",
     {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}, "linux-x11", "display"),
    # 5. Só um display
    ("so_wayland", "linux", {"WAYLAND_DISPLAY": "wayland-0"}, "linux-wayland", "wayland_display"),
    ("so_display", "linux", {"DISPLAY": ":0"}, "linux-x11", "display"),
    # 6. Fallback
    ("headless", "linux", {}, "linux-headless", "fallback"),
]


@pytest.mark.parametrize(
    "sys_platform,environ,kind,source",
    [c[1:] for c in CASOS],
    ids=[c[0] for c in CASOS],
)
def test_detect_tabela(sys_platform, environ, kind, source):
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # nenhum caso da tabela deve avisar
        ctx = detect(sys_platform=sys_platform, environ=environ, frozen=False)
    assert (ctx.kind, ctx.source) == (kind, source)


def test_override_invalido_avisa_e_ignora():
    with pytest.warns(UserWarning):
        ctx = detect(
            sys_platform="linux",
            environ={"JARVIS_PLATFORM": "banana", "WAYLAND_DISPLAY": "wayland-0"},
            frozen=False,
        )
    assert (ctx.kind, ctx.source) == ("linux-wayland", "wayland_display")


def test_is_windows_is_linux():
    win = detect(sys_platform="win32", environ={}, frozen=False)
    assert win.is_windows and not win.is_linux
    lin = detect(sys_platform="linux", environ={"DISPLAY": ":0"}, frozen=False)
    assert lin.is_linux and not lin.is_windows


def test_desktops_e_flags():
    ctx = detect(
        sys_platform="linux",
        environ={
            "XDG_CURRENT_DESKTOP": "KDE:plasma",
            "WAYLAND_DISPLAY": "wayland-0",
            "DISPLAY": ":0",
            "APPIMAGE": "/tmp/J.AppImage",
        },
        frozen=True,
    )
    assert ctx.desktops == ("kde", "plasma")
    assert ctx.appimage is True
    assert ctx.frozen is True
    # wayland + DISPLAY definido → xwayland
    assert ctx.xwayland is True


def test_context_e_imutavel():
    ctx = detect(sys_platform="win32", environ={}, frozen=False)
    with pytest.raises(Exception):
        ctx.kind = "linux-x11"  # frozen dataclass
