"""K — contrato (F2-01): `jarvis.platform.linux.hotkeys_kglobalaccel`
(ainda não existe — import dentro de cada teste). KGlobalAccel FALSO no
barramento privado (`private_session_bus` + `fake_dbus_service`, conexão
nova por teste). `xfail(strict=True, reason="F2-01")`.

Usa só os métodos do Protocol (`jarvis.platform.protocols.Hotkeys`):
`bind(bindings)`, `listen_keys(on_press, on_release)`, `stop()`. Nenhum
detalhe interno (`bind_action`, `bind_signal_handlers`) — isso só é
observável pelo comportamento no D-Bus falso.
"""
import os
import time

import dbus
import dbus.bus
import pytest

from tests.fakes.dbus_services import fake_dbus_service

pytestmark = [pytest.mark.linux_only]

_BUS = "org.kde.kglobalaccel"
_PATH = "/kglobalaccel"
_COMPONENT_PATH = "/component/jarvis"


def _wait_until(predicate, *, timeout: float = 2.0, step: float = 0.02) -> bool:
    """A produção despacha `globalShortcutPressed`/`Released` numa thread
    própria -- o callback pode não ter rodado ainda no instante exato em
    que `EmitSignal`/`invokeShortcut` retorna. Poll curto em vez de assert
    imediato (achado: flaky ~1/8 sem isso)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def _mount_kglobalaccel(mock, *, set_shortcut_ret="[71]"):
    mock.AddMethod("org.kde.KGlobalAccel", "doRegister", "as", "", "")
    mock.AddMethod("org.kde.KGlobalAccel", "setShortcut", "asaiu", "ai", f"ret = {set_shortcut_ret}")
    mock.AddMethod("org.kde.KGlobalAccel", "unRegister", "as", "", "")
    mock.AddMethod(
        "org.kde.KGlobalAccel", "getComponent", "s", "o", f'ret = dbus.ObjectPath("{_COMPONENT_PATH}")'
    )


def test_register_and_set_shortcut_called(private_session_bus):
    from jarvis.platform.linux.hotkeys_kglobalaccel import KGlobalAccelHotkeys
    from jarvis.platform.protocols import HotkeyBinding

    with fake_dbus_service(_BUS, _PATH, "org.kde.KGlobalAccel") as (mock, _real):
        _mount_kglobalaccel(mock)

        binding = HotkeyBinding("ptt", "Falar com o JARVIS", "<shift>+g", lambda: None, lambda: None)
        KGlobalAccelHotkeys().bind([binding])

        method_names = [call[1] for call in mock.GetCalls()]
        assert "doRegister" in method_names
        assert "setShortcut" in method_names


def test_set_shortcut_called_with_is_default_then_set_present_flags(private_session_bus):
    """SPEC F2-01 §5: `setShortcut` é chamado com `IsDefault` (8) pra
    definir o atalho padrão e DEPOIS com `SetPresent` (2) pra ativá-lo de
    verdade -- os dois valores de flags precisam aparecer nas chamadas."""
    from jarvis.platform.linux.hotkeys_kglobalaccel import KGlobalAccelHotkeys
    from jarvis.platform.protocols import HotkeyBinding

    with fake_dbus_service(_BUS, _PATH, "org.kde.KGlobalAccel") as (mock, _real):
        _mount_kglobalaccel(mock)

        binding = HotkeyBinding("ptt", "Falar com o JARVIS", "<shift>+g", lambda: None, lambda: None)
        KGlobalAccelHotkeys().bind([binding])

        set_shortcut_flags = [call[2][-1] for call in mock.GetCalls() if call[1] == "setShortcut"]
        assert 8 in set_shortcut_flags, f"esperava flags=IsDefault(8) em alguma chamada, veio {set_shortcut_flags}"
        assert 2 in set_shortcut_flags, f"esperava flags=SetPresent(2) em alguma chamada, veio {set_shortcut_flags}"


def test_conflicting_shortcut_empty_list_gives_warning_trigger(private_session_bus):
    from jarvis.platform.linux.hotkeys_kglobalaccel import KGlobalAccelHotkeys
    from jarvis.platform.protocols import HotkeyBinding

    with fake_dbus_service(_BUS, _PATH, "org.kde.KGlobalAccel") as (mock, _real):
        _mount_kglobalaccel(mock, set_shortcut_ret="[]")

        binding = HotkeyBinding("ptt", "Falar com o JARVIS", "<shift>+g", lambda: None, lambda: None)
        result = KGlobalAccelHotkeys().bind([binding])
        assert "sem atalho" in result["ptt"].lower()


def test_global_shortcut_pressed_signal_dispatches(private_session_bus):
    from jarvis.platform.linux.hotkeys_kglobalaccel import KGlobalAccelHotkeys
    from jarvis.platform.protocols import HotkeyBinding

    with fake_dbus_service(_BUS, _PATH, "org.kde.KGlobalAccel") as (mock, _real):
        _mount_kglobalaccel(mock)
        mock.AddObject(_COMPONENT_PATH, "org.kde.kglobalaccel.Component", {}, [])

        pressed = []
        binding = HotkeyBinding(
            "ptt", "Falar com o JARVIS", "<shift>+g", lambda: pressed.append("ptt"), lambda: None
        )
        KGlobalAccelHotkeys().bind([binding])

        mock.EmitSignal(
            "org.kde.kglobalaccel.Component",
            "globalShortcutPressed",
            "ssx",
            [dbus.String("jarvis"), dbus.String("ptt"), dbus.Int64(0)],
            path=_COMPONENT_PATH,
        )
        assert _wait_until(lambda: pressed == ["ptt"]), f"pressed={pressed!r}"


def test_global_shortcut_released_signal_dispatches(private_session_bus):
    from jarvis.platform.linux.hotkeys_kglobalaccel import KGlobalAccelHotkeys
    from jarvis.platform.protocols import HotkeyBinding

    with fake_dbus_service(_BUS, _PATH, "org.kde.KGlobalAccel") as (mock, _real):
        _mount_kglobalaccel(mock)
        mock.AddObject(_COMPONENT_PATH, "org.kde.kglobalaccel.Component", {}, [])

        released = []
        binding = HotkeyBinding(
            "ptt", "Falar com o JARVIS", "<shift>+g", lambda: None, lambda: released.append("ptt")
        )
        KGlobalAccelHotkeys().bind([binding])

        mock.EmitSignal(
            "org.kde.kglobalaccel.Component",
            "globalShortcutReleased",
            "ssx",
            [dbus.String("jarvis"), dbus.String("ptt"), dbus.Int64(0)],
            path=_COMPONENT_PATH,
        )
        assert _wait_until(lambda: released == ["ptt"]), f"released={released!r}"


def test_invoke_shortcut_triggers_pressed_signal(private_session_bus):
    """`invokeShortcut(shortcutName)` existe no componente REAL (conferido
    contra o `kglobalacceld` de verdade em container, sem fake nenhum) e é
    o gancho que o smoke N3 (`JARVIS_SMOKE_PTT=press`) usa pra simular um
    press sem input físico. Aqui só prova que o comportamento do PRÓPRIO
    Hotkeys (dispatch de `globalShortcutPressed` -> `on_press`) funciona
    quando ESSE sinal é emitido, seja por `invokeShortcut` de verdade ou
    por qualquer outro caminho."""
    from jarvis.platform.linux.hotkeys_kglobalaccel import KGlobalAccelHotkeys
    from jarvis.platform.protocols import HotkeyBinding

    with fake_dbus_service(_BUS, _PATH, "org.kde.KGlobalAccel") as (mock, _real):
        _mount_kglobalaccel(mock)
        mock.AddObject(
            _COMPONENT_PATH,
            "org.kde.kglobalaccel.Component",
            {},
            [
                (
                    "invokeShortcut",
                    "s",
                    "",
                    'self.EmitSignal("org.kde.kglobalaccel.Component", "globalShortcutPressed", '
                    '"ssx", ["jarvis", args[0], 0])',
                )
            ],
        )

        pressed = []
        binding = HotkeyBinding(
            "ptt", "Falar com o JARVIS", "<shift>+g", lambda: pressed.append("ptt"), lambda: None
        )
        KGlobalAccelHotkeys().bind([binding])

        # conexão própria (não a de `mock`/`_real`) pra chamar o método
        # dinâmico que acabamos de adicionar no path do componente -- mesma
        # regra de "conexão nova, nunca dbus.SessionBus() em cache".
        aux_bus = dbus.bus.BusConnection(os.environ["DBUS_SESSION_BUS_ADDRESS"])
        try:
            component = dbus.Interface(
                aux_bus.get_object(_BUS, _COMPONENT_PATH), "org.kde.kglobalaccel.Component"
            )
            component.invokeShortcut("ptt")
        finally:
            aux_bus.close()

        assert _wait_until(lambda: pressed == ["ptt"]), f"pressed={pressed!r}"


def test_stop_calls_unregister_for_each_action(private_session_bus):
    from jarvis.platform.linux.hotkeys_kglobalaccel import KGlobalAccelHotkeys
    from jarvis.platform.protocols import HotkeyBinding

    with fake_dbus_service(_BUS, _PATH, "org.kde.KGlobalAccel") as (mock, _real):
        _mount_kglobalaccel(mock)

        binding = HotkeyBinding("ptt", "Falar com o JARVIS", "<shift>+g", lambda: None, lambda: None)
        hk = KGlobalAccelHotkeys()
        hk.bind([binding])
        hk.stop()

        method_names = [call[1] for call in mock.GetCalls()]
        assert "unRegister" in method_names


def test_listen_keys_returns_false():
    from jarvis.platform.linux.hotkeys_kglobalaccel import KGlobalAccelHotkeys

    assert KGlobalAccelHotkeys().listen_keys(lambda k: None, lambda k: None) is False
