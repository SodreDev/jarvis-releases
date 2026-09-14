"""K — contrato (F2-01): `jarvis.platform.linux_wayland.hotkeys_portal`
(ainda não existe — import dentro de cada teste). Portal FALSO no
barramento privado (`private_session_bus` + `fake_dbus_service`), nunca
o `xdg-desktop-portal` do host. `xfail(strict=True, reason="F2-01")`.
"""
import pytest

from tests.fakes.dbus_services import fake_dbus_service

pytestmark = [pytest.mark.linux_only, pytest.mark.xfail(strict=True, reason="F2-01")]

_PORTAL_BUS = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"


def test_registry_register_called_before_create_session(private_session_bus):
    from jarvis.platform.linux_wayland.hotkeys_portal import PortalGlobalShortcuts

    with fake_dbus_service(_PORTAL_BUS, _PORTAL_PATH, "org.freedesktop.host.portal.Registry") as (mock, _real):
        mock.AddMethod("org.freedesktop.host.portal.Registry", "Register", "sa{sv}", "", "")
        mock.AddMethod(
            "org.freedesktop.portal.GlobalShortcuts",
            "CreateSession",
            "a{sv}",
            "o",
            'ret = "/org/freedesktop/portal/desktop/session/1"',
        )
        mock.AddProperty("org.freedesktop.portal.GlobalShortcuts", "version", 2)

        PortalGlobalShortcuts(app_id="jarvis").ensure_session()

        method_names = [call[1] for call in mock.GetCalls()]
        assert method_names.index("Register") < method_names.index("CreateSession")


def test_response_code_1_is_capability_unavailable_and_does_not_repeat(private_session_bus):
    from jarvis.platform.common.errors import CapabilityUnavailable
    from jarvis.platform.linux_wayland.hotkeys_portal import PortalGlobalShortcuts

    with fake_dbus_service(_PORTAL_BUS, _PORTAL_PATH, "org.freedesktop.portal.GlobalShortcuts") as (mock, _real):
        mock.AddProperty("org.freedesktop.portal.GlobalShortcuts", "version", 2)
        # resposta 1 = usuário recusou -- o adapter deve devolver
        # CapabilityUnavailable e marcar internamente pra não repetir o
        # pedido na mesma sessão de processo.
        hk = PortalGlobalShortcuts(app_id="jarvis", fake_bind_response_code=1)
        try:
            hk.bind([])
        except CapabilityUnavailable as e:
            assert "recusou" in str(e)
        else:
            raise AssertionError("esperava CapabilityUnavailable com resposta 1")

        # segunda chamada não deve refazer o pedido ao portal
        calls_before = len(mock.GetCalls())
        try:
            hk.bind([])
        except CapabilityUnavailable:
            pass
        assert len(mock.GetCalls()) == calls_before


def test_activated_signal_becomes_on_press(private_session_bus):
    from jarvis.platform.linux_wayland.hotkeys_portal import PortalGlobalShortcuts

    with fake_dbus_service(_PORTAL_BUS, _PORTAL_PATH, "org.freedesktop.portal.GlobalShortcuts") as (mock, _real):
        mock.AddProperty("org.freedesktop.portal.GlobalShortcuts", "version", 2)

        pressed = []
        hk = PortalGlobalShortcuts(app_id="jarvis")
        hk.bind_signal_handlers(on_press=lambda sid: pressed.append(sid), on_release=lambda sid: None)

        mock.EmitSignal(
            "org.freedesktop.portal.GlobalShortcuts",
            "Activated",
            "osta{sv}",
            ["/session", "ptt", 0, {}],
        )
        assert pressed == ["ptt"]


def test_listen_keys_returns_false():
    from jarvis.platform.linux_wayland.hotkeys_portal import PortalGlobalShortcuts

    assert PortalGlobalShortcuts(app_id="jarvis").listen_keys(lambda k: None, lambda k: None) is False
