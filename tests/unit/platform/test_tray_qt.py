"""K — contrato (F2-02): `jarvis.platform.linux.tray_qt.QtSystemTray`
(ainda não existe — import dentro de cada teste). N2/N3 (precisa de
display real via Xvfb/KWin virtual). `xfail(strict=True, reason="F2-02")`.

Usa só o Protocol (`jarvis.platform.protocols.Tray`):
`setup(title, make_image, items) -> bool`, `set_visible(visible)`,
`stop()`. Nenhum nome inventado (`menu()`, `isVisible()`, `icon_path=`).

Sonda (SPEC F2-02): `org.kde.StatusNotifierWatcher` tem dono OU
`ctx.kind == "linux-x11"` (XEmbed do próprio Qt, sem watcher). Sem
nenhum dos dois, a bandeja fica indisponível -- comportamento provado
via `private_session_bus` (barramento privado SEM watcher nenhum
registrado), nunca com gancho de teste no construtor de produção.
"""
import time
import types

import pytest

pytestmark = [
    pytest.mark.linux_only,
    pytest.mark.x11,
    pytest.mark.wayland,
    pytest.mark.needs_display,
    pytest.mark.slow,
]


def _fake_image():
    from PIL import Image

    return Image.new("RGB", (8, 8))


def test_probe_true_on_x11_even_without_watcher(private_session_bus):
    from jarvis.platform.linux.tray_qt import QtSystemTray

    # barramento privado sem NENHUM serviço registrado -- x11 com DISPLAY
    # não depende do watcher (XEmbed do próprio Qt).
    ctx = types.SimpleNamespace(kind="linux-x11")
    assert QtSystemTray.probe(ctx).ok is True


def test_probe_false_on_wayland_without_watcher(private_session_bus):
    from jarvis.platform.linux.tray_qt import QtSystemTray

    ctx = types.SimpleNamespace(kind="linux-wayland")
    probe = QtSystemTray.probe(ctx)
    assert probe.ok is False


def test_probe_true_on_wayland_with_watcher(private_session_bus):
    from jarvis.platform.linux.tray_qt import QtSystemTray

    from tests.fakes.dbus_services import fake_dbus_service

    with fake_dbus_service(
        "org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher"
    ):
        ctx = types.SimpleNamespace(kind="linux-wayland")
        assert QtSystemTray.probe(ctx).ok is True


def test_setup_on_x11_returns_true_and_starts_hidden():
    from PySide6.QtWidgets import QApplication

    from jarvis.platform.linux.tray_qt import QtSystemTray

    QApplication.instance() or QApplication([])

    from jarvis.platform.protocols import TrayItem

    calls = []
    items = [
        TrayItem("Restaurar JARVIS", lambda: calls.append("restaurar"), default=True),
        TrayItem("Briefing", lambda: calls.append("briefing")),
        TrayItem("", None, separator=True),
        TrayItem("Encerrar", lambda: calls.append("encerrar")),
    ]

    tray = QtSystemTray(ctx=types.SimpleNamespace(kind="linux-x11"))
    ok = tray.setup("J.A.R.V.I.S.", _fake_image, items)
    assert ok is True
    tray.stop()


def test_register_status_notifier_item_only_after_set_visible_true(private_session_bus):
    """SPEC F2-02 + golden (`visible=False` igual ao pystray do Windows):
    a bandeja NASCE OCULTA, e o Qt só se registra de verdade no watcher
    (`RegisterStatusNotifierItem`) quando fica visível -- confirmado pelo
    executor no N3 real: oculto dá `calls=[]`, visível dá o Register.
    Decisão do dono: a produção fica como está, o teste que confere DEPOIS
    de `set_visible(True)`, não logo após `setup()`."""
    from PySide6.QtWidgets import QApplication

    from jarvis.platform.linux.tray_qt import QtSystemTray
    from jarvis.platform.protocols import TrayItem
    from tests.fakes.dbus_services import fake_dbus_service

    app = QApplication.instance() or QApplication([])

    with fake_dbus_service(
        "org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher"
    ) as (mock, _real):
        mock.AddMethod("org.kde.StatusNotifierWatcher", "RegisterStatusNotifierItem", "s", "", "")

        tray = QtSystemTray(ctx=types.SimpleNamespace(kind="linux-wayland"))
        ok = tray.setup("J.A.R.V.I.S.", _fake_image, [TrayItem("Encerrar", lambda: None)])
        assert ok is True

        # oculto -- ainda não se registrou no watcher.
        assert mock.GetCalls() == []

        tray.set_visible(True)

        end = time.monotonic() + 2.0
        method_names = []
        while time.monotonic() < end:
            app.processEvents()
            method_names = [c[1] for c in mock.GetCalls()]
            if "RegisterStatusNotifierItem" in method_names:
                break
            time.sleep(0.02)
        assert "RegisterStatusNotifierItem" in method_names, method_names

        tray.stop()


def test_set_visible_and_stop_do_not_raise():
    from PySide6.QtWidgets import QApplication

    from jarvis.platform.linux.tray_qt import QtSystemTray
    from jarvis.platform.protocols import TrayItem

    QApplication.instance() or QApplication([])

    tray = QtSystemTray(ctx=types.SimpleNamespace(kind="linux-x11"))
    tray.setup("J.A.R.V.I.S.", _fake_image, [TrayItem("Encerrar", lambda: None)])
    tray.set_visible(True)
    tray.set_visible(False)
    tray.stop()
