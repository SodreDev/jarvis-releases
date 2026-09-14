"""N2/N3: smoke de tray real (F2-02). N2 X11: tray sempre ativo (XEmbed
do próprio Qt, sem precisar de watcher). N3 Wayland: dois cenários --
COM um `org.kde.StatusNotifierWatcher` falso registrado no barramento
do próprio container (item deve se registrar) e SEM nenhum watcher
(feature desligada, aviso único, fechar a janela encerra o app). Só
roda dentro do container (`JARVIS_TEST_SANDBOXED=1`).

O watcher falso é montado com `python-dbusmock` DIRETO no barramento de
sessão do próprio container (o mesmo que `main.py` vai usar) -- não é
`private_session_bus`/`fake_dbus_service` (barramento PRIVADO à parte,
que `main.py` nunca veria).
"""
import os

import pytest

from tests.smoke._boot_helpers import run_boot_smoke, skip_unless_sandboxed

pytestmark = [pytest.mark.linux_only, pytest.mark.needs_display, pytest.mark.slow]


@pytest.mark.x11
def test_tray_active_on_x11():
    skip_unless_sandboxed()
    stdout = run_boot_smoke("linux-x11", session_type="x11")
    assert "[TRAY] Interceptação do botão X ativa" in stdout, stdout[-4000:]
    assert "[TRAY] Bandeja indisponível" not in stdout, stdout[-4000:]


@pytest.mark.wayland
def test_tray_registered_with_watcher_on_wayland():
    skip_unless_sandboxed()
    import dbus
    import dbus.bus
    from dbusmock import DBusTestCase

    proc = DBusTestCase.spawn_server(
        "org.kde.StatusNotifierWatcher",
        "/StatusNotifierWatcher",
        "org.kde.StatusNotifierWatcher",
        system_bus=False,
    )
    try:
        bus = dbus.bus.BusConnection(os.environ["DBUS_SESSION_BUS_ADDRESS"])
        try:
            obj = bus.get_object("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher")
            mock = dbus.Interface(obj, "org.freedesktop.DBus.Mock")
            mock.AddMethod("org.kde.StatusNotifierWatcher", "RegisterStatusNotifierItem", "s", "", "")
            mock.AddProperty(
                "org.kde.StatusNotifierWatcher", "IsStatusNotifierHostRegistered", dbus.Boolean(True)
            )
            mock.AddProperty(
                "org.kde.StatusNotifierWatcher", "RegisteredStatusNotifierItems", dbus.Array([], signature="s")
            )

            stdout = run_boot_smoke("linux-wayland", session_type="wayland")

            method_names = [call[1] for call in mock.GetCalls()]
            assert "RegisterStatusNotifierItem" in method_names, "item não se registrou no watcher"
            assert "[TRAY] Interceptação do botão X ativa" in stdout, stdout[-4000:]
            assert "[TRAY] Bandeja indisponível" not in stdout, stdout[-4000:]
        finally:
            bus.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


@pytest.mark.wayland
def test_tray_disabled_without_watcher_on_wayland():
    """Sem NENHUM watcher no barramento: feature tray desligada, aviso
    único, fechar a janela (timer do smoke) encerra o app normalmente."""
    skip_unless_sandboxed()
    stdout = run_boot_smoke("linux-wayland", session_type="wayland")
    assert "[TRAY] Bandeja indisponível nesta sessão" in stdout, stdout[-4000:]
    assert stdout.count("[TRAY] Bandeja indisponível") == 1, "aviso deveria aparecer uma única vez"
