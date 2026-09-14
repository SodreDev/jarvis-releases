"""K — contrato (F2-01): `jarvis.platform.linux.hotkeys_kglobalaccel`
(ainda não existe — import dentro de cada teste). KGlobalAccel FALSO no
barramento privado. `xfail(strict=True, reason="F2-01")`.
"""
import pytest

from tests.fakes.dbus_services import fake_dbus_service

pytestmark = [pytest.mark.linux_only, pytest.mark.xfail(strict=True, reason="F2-01")]

_BUS = "org.kde.kglobalaccel"
_PATH = "/kglobalaccel"


def test_register_and_set_shortcut_called(private_session_bus):
    from jarvis.platform.linux.hotkeys_kglobalaccel import KGlobalAccelHotkeys

    with fake_dbus_service(_BUS, _PATH, "org.kde.KGlobalAccel") as (mock, _real):
        mock.AddMethod("org.kde.KGlobalAccel", "doRegister", "as", "", "")
        mock.AddMethod("org.kde.KGlobalAccel", "setShortcut", "asaiu", "ai", "ret = [71]")
        mock.AddMethod("org.kde.KGlobalAccel", "getComponent", "s", "o", 'ret = "/component/jarvis"')

        hk = KGlobalAccelHotkeys()
        hk.bind_action(action_id="ptt", description="Falar com o JARVIS", trigger="<shift>+g")

        method_names = [call[1] for call in mock.GetCalls()]
        assert "doRegister" in method_names
        assert "setShortcut" in method_names


def test_conflicting_shortcut_empty_list_gives_warning_trigger(private_session_bus):
    from jarvis.platform.linux.hotkeys_kglobalaccel import KGlobalAccelHotkeys

    with fake_dbus_service(_BUS, _PATH, "org.kde.KGlobalAccel") as (mock, _real):
        mock.AddMethod("org.kde.KGlobalAccel", "doRegister", "as", "", "")
        mock.AddMethod("org.kde.KGlobalAccel", "setShortcut", "asaiu", "ai", "ret = []")

        hk = KGlobalAccelHotkeys()
        result = hk.bind_action(action_id="ptt", description="Falar com o JARVIS", trigger="<shift>+g")
        assert "sem atalho" in result.lower()


def test_global_shortcut_pressed_signal_dispatches(private_session_bus):
    from jarvis.platform.linux.hotkeys_kglobalaccel import KGlobalAccelHotkeys

    with fake_dbus_service("org.kde.kglobalaccel", "/component/jarvis", "org.kde.kglobalaccel.Component") as (
        mock,
        _real,
    ):
        pressed = []
        hk = KGlobalAccelHotkeys()
        hk.bind_signal_handlers(on_press=lambda action: pressed.append(action), on_release=lambda action: None)

        mock.EmitSignal(
            "org.kde.kglobalaccel.Component", "globalShortcutPressed", "ssx", ["jarvis", "ptt", 0]
        )
        assert pressed == ["ptt"]


def test_listen_keys_returns_false():
    from jarvis.platform.linux.hotkeys_kglobalaccel import KGlobalAccelHotkeys

    assert KGlobalAccelHotkeys().listen_keys(lambda k: None, lambda k: None) is False
