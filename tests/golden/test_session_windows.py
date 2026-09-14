"""C — caracterização (F2-07): `_idle_seconds`, `get_timezone_name` e
`get_locale` no Windows continuam idênticos depois da fachada
`jarvis.platform` (Cap.SESSION) entrar.
"""
import types

from tests.golden.legacy_31bc0ce import (
    legacy_get_locale,
    legacy_get_timezone_name,
    legacy_idle_seconds,
)


def _fake_ctypes(*, tick_count: int, last_input_time: int):
    class _FakeUser32:
        def GetLastInputInfo(self, lii_ref):
            lii_ref._obj.dwTime = last_input_time

    class _FakeKernel32:
        def GetTickCount(self):
            return tick_count

    fake = types.SimpleNamespace()
    fake.windll = types.SimpleNamespace(user32=_FakeUser32(), kernel32=_FakeKernel32())

    import ctypes as _real_ctypes

    fake.Structure = _real_ctypes.Structure
    fake.c_uint = _real_ctypes.c_uint
    fake.byref = _real_ctypes.byref
    fake.sizeof = _real_ctypes.sizeof
    return fake


def test_idle_seconds_computes_from_tick_minus_last_input():
    ct = _fake_ctypes(tick_count=10_000, last_input_time=7_000)
    assert legacy_idle_seconds(ct) == 3.0


def test_idle_seconds_returns_zero_on_exception():
    class _Boom:
        def __getattr__(self, _name):
            raise RuntimeError("windll indisponível")

    assert legacy_idle_seconds(_Boom()) == 0.0


class _FakeWinregKey:
    pass


class _FakeWinreg:
    HKEY_LOCAL_MACHINE = "HKLM"

    def __init__(self, tz_name: str | None):
        self._tz_name = tz_name

    def OpenKey(self, hive, scope):
        if self._tz_name is None:
            raise OSError("chave não encontrada")
        return _FakeWinregKey()

    def QueryValueEx(self, key, name):
        return self._tz_name, 1

    def CloseKey(self, key):
        pass


def test_get_timezone_name_from_registry_known_tz():
    winreg = _FakeWinreg("E. South America Standard Time")
    assert legacy_get_timezone_name(winreg, ("BRT", "BRST")) == "America/Sao_Paulo"


def test_get_timezone_name_falls_back_to_tzname():
    winreg = _FakeWinreg(None)
    assert legacy_get_timezone_name(winreg, ("UTC", "UTC")) == "UTC"


def test_get_locale_replaces_underscore():
    assert legacy_get_locale(lambda: ("pt_BR", "cp1252")) == "pt-BR"


def test_get_locale_falls_back_on_exception():
    def _boom():
        raise RuntimeError("sem locale")

    assert legacy_get_locale(_boom) == "pt-BR"
