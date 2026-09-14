"""K — contrato (F2-07): `jarvis.platform.linux.session` (ainda não
existe — import dentro de cada teste). `xfail(strict=True, reason="F2-07")`.

ScreenSaver/Mutter/logind: serviços D-Bus FALSOS no barramento privado
(`private_session_bus` + `tests/fakes/dbus_services.fake_dbus_service`) —
nunca fala com o D-Bus do host.
"""
import pytest

from tests.fakes.dbus_services import fake_dbus_service

pytestmark = [pytest.mark.linux_only, pytest.mark.xfail(strict=True, reason="F2-07")]


def test_screensaver_session_reads_idle_seconds(private_session_bus):
    from jarvis.platform.linux.session import ScreenSaverSession

    with fake_dbus_service(
        "org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver"
    ) as (mock, _real):
        mock.AddMethod("org.freedesktop.ScreenSaver", "GetSessionIdleTime", "", "u", "ret = 42")
        assert ScreenSaverSession().idle_seconds() == 42.0


def test_screensaver_session_fixes_old_ms_bug(private_session_bus):
    """kscreenlocker antigo devolvia ms em vez de s: se o valor for maior
    que o uptime do sistema em segundos, divide por 1000."""
    from jarvis.platform.linux.session import ScreenSaverSession

    with fake_dbus_service(
        "org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver"
    ) as (mock, _real):
        # 5_000_000 "segundos" de idle é maior que qualquer uptime real —
        # aciona a correção (valor era em ms): 5_000_000 / 1000 = 5000 s.
        mock.AddMethod("org.freedesktop.ScreenSaver", "GetSessionIdleTime", "", "u", "ret = 5000000")
        assert ScreenSaverSession().idle_seconds() == 5000.0


def test_mutter_session_reads_idle_ms_converted_to_seconds(private_session_bus):
    from jarvis.platform.linux.session import MutterSession

    with fake_dbus_service(
        "org.gnome.Mutter.IdleMonitor",
        "/org/gnome/Mutter/IdleMonitor/Core",
        "org.gnome.Mutter.IdleMonitor",
    ) as (mock, _real):
        mock.AddMethod("org.gnome.Mutter.IdleMonitor", "GetIdletime", "", "t", "ret = 3000")
        assert MutterSession().idle_seconds() == 3.0


def test_logind_session_idle_since_hint(private_session_bus):
    from jarvis.platform.linux.session import LogindSession

    with fake_dbus_service(
        "org.freedesktop.login1", "/org/freedesktop/login1/session/auto", "org.freedesktop.login1.Session"
    ) as (mock, _real):
        mock.AddProperty("org.freedesktop.login1.Session", "IdleHint", True)
        mock.AddProperty("org.freedesktop.login1.Session", "IdleSinceHintMonotonic", dbus_uint64(0))
        session = LogindSession()
        idle = session.idle_seconds()
        assert idle is not None and idle >= 0.0


def test_session_without_any_service_returns_none(private_session_bus):
    from jarvis.platform.linux.session import ScreenSaverSession

    # nenhum serviço no barramento privado -> sonda falha -> None
    assert ScreenSaverSession().idle_seconds() is None


def dbus_uint64(value):
    import dbus

    return dbus.UInt64(value)


def test_locale_priority_lc_all_over_lang(monkeypatch):
    from jarvis.platform.linux.session import XdgSession

    monkeypatch.setenv("LC_ALL", "pt_BR.UTF-8")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert XdgSession().locale() == "pt-BR"


def test_locale_default_when_nothing_set(monkeypatch):
    from jarvis.platform.linux.session import XdgSession

    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    assert XdgSession().locale() == "pt-BR"


def test_timezone_name_from_tz_env(monkeypatch):
    from jarvis.platform.linux.session import XdgSession

    monkeypatch.setenv("TZ", "America/Sao_Paulo")
    assert XdgSession().timezone_name() == "America/Sao_Paulo"
