"""K F2-07: adapters de session e o REGISTRY.

- Windows (W1): WindowsSession.idle_seconds igual ao oráculo legado (windll falso),
  exceção vira 0.0 (nunca None); locale/fuso delegam para core.win_locale.
- Linux: locale/fuso por variáveis e /etc/localtime; ScreenSaver (s), Mutter (ms) e
  logind (µs) em serviços FALSOS no barramento PRIVADO (o logind usa esse mesmo
  barramento como "sistema" via DBUS_SYSTEM_BUS_ADDRESS); XScreenSaver com libs falsas.
- REGISTRY: cadeias por kind, XdgSession fechando as do Linux.
Nenhum teste fala com o D-Bus do host nem abre o DISPLAY de verdade.
"""
import ctypes
import subprocess
import sys
import time
import types

import pytest

from jarvis.platform import registry
from jarvis.platform.capabilities import Cap
from jarvis.platform.detect import detect
from jarvis.platform.windows.session import WindowsSession
from tests.golden.legacy_31bc0ce import legacy_idle_seconds

WIN32 = detect(sys_platform="win32", environ={}, frozen=False)
WAYLAND = detect(sys_platform="linux", environ={"WAYLAND_DISPLAY": "wayland-0"}, frozen=False)
X11 = detect(sys_platform="linux", environ={"DISPLAY": ":0"}, frozen=False)
HEADLESS = detect(sys_platform="linux", environ={}, frozen=False)

MOCK_IFACE = "org.freedesktop.DBus.Mock"


# ── Windows ──────────────────────────────────────────────────────────────────────

def _fake_ctypes(*, tick_count, last_input_time):
    class _User32:
        def GetLastInputInfo(self, lii_ref):
            lii_ref._obj.dwTime = last_input_time

    class _Kernel32:
        def GetTickCount(self):
            return tick_count

    fake = types.SimpleNamespace(
        windll=types.SimpleNamespace(user32=_User32(), kernel32=_Kernel32()),
        Structure=ctypes.Structure, c_uint=ctypes.c_uint, byref=ctypes.byref, sizeof=ctypes.sizeof,
    )
    return fake


def test_windows_idle_igual_ao_legado():
    ct = _fake_ctypes(tick_count=10_000, last_input_time=7_000)
    assert WindowsSession(WIN32, ctypes_mod=ct).idle_seconds() == legacy_idle_seconds(ct) == 3.0


def test_windows_idle_excecao_vira_zero_nunca_none():
    class _Boom:
        def __getattr__(self, _nome):
            raise RuntimeError("windll indisponível")

    assert WindowsSession(WIN32, ctypes_mod=_Boom()).idle_seconds() == 0.0


def test_windows_locale_e_fuso_delegam_para_win_locale(monkeypatch):
    import core.win_locale as wl

    monkeypatch.setattr(wl, "get_locale", lambda: "es-AR")
    monkeypatch.setattr(wl, "get_timezone_name", lambda: "America/Argentina/Buenos_Aires")
    s = WindowsSession(WIN32)
    assert s.locale() == "es-AR"
    assert s.timezone_name() == "America/Argentina/Buenos_Aires"


# ── Linux: locale e fuso ─────────────────────────────────────────────────────────

linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="só Linux")


@linux
@pytest.mark.parametrize("env, esperado", [
    ({"LC_ALL": "pt_BR.UTF-8", "LANG": "en_US.UTF-8"}, "pt-BR"),
    ({"LC_MESSAGES": "en_US.UTF-8", "LANG": "pt_BR.UTF-8"}, "en-US"),
    ({"LANG": "de_DE@euro"}, "de-DE"),
    ({"LC_ALL": "C.UTF-8", "LANG": "es_AR.UTF-8"}, "es-AR"),
    ({"LANG": "POSIX"}, "pt-BR"),
    ({}, "pt-BR"),
])
def test_locale_por_variaveis(env, esperado):
    from jarvis.platform.linux.session import XdgSession

    assert XdgSession(environ=env).locale() == esperado


@linux
def test_fuso_por_tz_e_por_localtime(tmp_path):
    from jarvis.platform.linux.session import XdgSession

    assert XdgSession(environ={"TZ": ":America/Sao_Paulo"}).timezone_name() == "America/Sao_Paulo"
    assert XdgSession(environ={"TZ": "/usr/share/zoneinfo/Asia/Tokyo"}).timezone_name() == "Asia/Tokyo"

    link = tmp_path / "localtime"
    link.symlink_to("../usr/share/zoneinfo/Europe/Berlin")
    assert XdgSession(environ={}, localtime_path=str(link)).timezone_name() == "Europe/Berlin"
    assert XdgSession(environ={}, localtime_path=str(tmp_path / "nao-existe")).timezone_name() == "UTC"


# ── Linux: idle por D-Bus (barramento privado) ──────────────────────────────────

@pytest.fixture
def isolado(monkeypatch, tmp_path):
    """D-Bus de sessão e de sistema apontando para sockets inexistentes; caches limpos."""
    pytest.importorskip("jeepney")
    from jarvis.platform.linux import dbus as jdbus

    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/sem-sessao")
    # sem a variável o logind usaria o socket de sistema do host
    monkeypatch.setenv("DBUS_SYSTEM_BUS_ADDRESS", f"unix:path={tmp_path}/sem-sistema")
    jdbus.reset()
    registry._clear_all()
    yield jdbus
    registry._clear_all()
    jdbus.reset()


@pytest.fixture
def servico(isolado, private_session_bus):
    """Sobe objetos dbusmock no barramento privado; encerra só os PIDs deles."""
    dbusmock = pytest.importorskip("dbusmock")
    jdbus = isolado
    procs = []

    def _subir(nome, caminho, iface):
        procs.append(dbusmock.DBusTestCase.spawn_server(nome, caminho, iface, stdout=subprocess.DEVNULL))

        def add_method(metodo, out_sig, codigo):
            jdbus.call(nome, caminho, MOCK_IFACE, "AddMethod", "sssss", (iface, metodo, "", out_sig, codigo))

        def add_property(prop, sig, valor):
            jdbus.call(nome, caminho, MOCK_IFACE, "AddProperty", "ssv", (iface, prop, (sig, valor)))

        def set_property(prop, sig, valor):  # propriedade que já existe
            jdbus.call(nome, caminho, "org.freedesktop.DBus.Properties", "Set", "ssv", (iface, prop, (sig, valor)))

        return types.SimpleNamespace(add_method=add_method, add_property=add_property, set_property=set_property)

    yield _subir
    jdbus.reset()
    for p in procs:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=5)


@linux
def test_screensaver_segundos_e_sonda(servico):
    from jarvis.platform.linux.session import ScreenSaverSession

    servico("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver").add_method(
        "GetSessionIdleTime", "u", "ret = 42")
    assert ScreenSaverSession().idle_seconds() == 42.0
    assert ScreenSaverSession.probe(WAYLAND).ok


@linux
def test_screensaver_bug_de_ms_avisa_uma_vez(servico, monkeypatch, capsys):
    from jarvis.platform.linux import session

    monkeypatch.setattr(session, "_uptime_seconds", lambda: 100.0)
    monkeypatch.setattr(session, "_aviso_ms_dado", False)
    servico("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver").add_method(
        "GetSessionIdleTime", "u", "ret = 5000")
    s = session.ScreenSaverSession()
    assert s.idle_seconds() == 5.0
    assert s.idle_seconds() == 5.0
    assert capsys.readouterr().out.count("milissegundos") == 1


@linux
def test_mutter_ms_para_segundos(servico):
    from jarvis.platform.linux.session import MutterSession

    servico("org.gnome.Mutter.IdleMonitor", "/org/gnome/Mutter/IdleMonitor/Core",
            "org.gnome.Mutter.IdleMonitor").add_method("GetIdletime", "t", "ret = 2500")
    assert MutterSession().idle_seconds() == 2.5


@linux
def test_logind_idle_hint_e_monotonic(servico, private_session_bus, monkeypatch):
    from jarvis.platform.linux.session import LogindSession

    monkeypatch.setenv("DBUS_SYSTEM_BUS_ADDRESS", private_session_bus)  # "sistema" = barramento privado
    svc = servico("org.freedesktop.login1", "/org/freedesktop/login1/session/auto",
                  "org.freedesktop.login1.Session")
    since = time.clock_gettime_ns(time.CLOCK_MONOTONIC) // 1000 - 5_000_000
    svc.add_property("IdleHint", "b", True)
    svc.add_property("IdleSinceHintMonotonic", "t", since)
    s = LogindSession()
    try:
        assert 4.5 <= s.idle_seconds() <= 8.0
        s.close()
        svc.set_property("IdleHint", "b", False)
        assert s.idle_seconds() == 0.0
    finally:
        s.close()


@linux
def test_sem_servico_devolve_none_rapido(isolado, private_session_bus):
    from jarvis.platform.linux.session import LogindSession, MutterSession, ScreenSaverSession

    inicio = time.monotonic()
    assert ScreenSaverSession().idle_seconds() is None
    assert MutterSession().idle_seconds() is None
    assert LogindSession().idle_seconds() is None  # sem login1 no barramento privado
    assert ScreenSaverSession.probe(WAYLAND).ok is False
    assert time.monotonic() - inicio <= 3.0


# ── Linux: XScreenSaver com libs falsas ─────────────────────────────────────────

def _loader_falso(*, idle_ms=1500, display=0x1234, erro=None):
    from jarvis.platform.linux_x11.session import _XScreenSaverInfo

    fechados = []

    def fn(impl):
        f = lambda *a: impl(*a)  # noqa: E731 — objeto função aceita restype/argtypes
        return f

    x11 = types.SimpleNamespace(
        XOpenDisplay=fn(lambda nome: display),
        XDefaultRootWindow=fn(lambda dpy: 42),
        XFree=fn(lambda ptr: None),
        XCloseDisplay=fn(lambda dpy: fechados.append(dpy)),
    )
    xss = types.SimpleNamespace(
        XScreenSaverAllocInfo=fn(lambda: ctypes.pointer(_XScreenSaverInfo(idle=idle_ms))),
        XScreenSaverQueryInfo=fn(lambda dpy, root, info: 1),
    )

    def loader(nome):
        if erro:
            raise OSError(erro)
        return {"libX11.so.6": x11, "libXss.so.1": xss}[nome]

    loader.fechados = fechados
    return loader


@linux
def test_xss_idle_em_ms_e_sonda(monkeypatch):
    from jarvis.platform.linux_x11.session import XssSession

    loader = _loader_falso(idle_ms=1500)
    s = XssSession(X11, loader=loader)
    assert s.idle_seconds() == 1.5
    s.close()
    assert loader.fechados == [0x1234]

    monkeypatch.setattr(XssSession, "_loader", staticmethod(loader))
    assert XssSession.probe(X11).ok


@linux
def test_xss_sem_display_ou_sem_lib(monkeypatch):
    from jarvis.platform.linux_x11.session import XssSession

    assert XssSession(X11, loader=_loader_falso(display=0)).idle_seconds() is None
    monkeypatch.setattr(XssSession, "_loader", staticmethod(_loader_falso(display=0)))
    assert XssSession.probe(X11).ok is False
    monkeypatch.setattr(XssSession, "_loader", staticmethod(_loader_falso(erro="libXss.so.1: não encontrada")))
    p = XssSession.probe(X11)
    assert p.ok is False and "libXss" in p.reason


# ── REGISTRY ─────────────────────────────────────────────────────────────────────

def test_cadeias_por_kind():
    L = "jarvis.platform.linux.session:"
    assert registry._chain_for(Cap.SESSION, "win32") == ("jarvis.platform.windows.session:WindowsSession",)
    assert registry._chain_for(Cap.SESSION, "linux-wayland") == (
        L + "ScreenSaverSession", L + "MutterSession", L + "LogindSession", L + "XdgSession")
    assert registry._chain_for(Cap.SESSION, "linux-x11") == (
        L + "ScreenSaverSession", "jarvis.platform.linux_x11.session:XssSession",
        L + "LogindSession", L + "XdgSession")
    assert registry._chain_for(Cap.SESSION, "linux-headless") == (L + "LogindSession", L + "XdgSession")


def test_registro_win32_windows_session():
    registry._clear_all()
    try:
        assert registry.resolve(Cap.SESSION, WIN32).name == "windows.session"
    finally:
        registry._clear_all()


@linux
def test_registro_linux_sem_servicos_cai_na_xdg(isolado):
    assert registry.resolve(Cap.SESSION, WAYLAND).name == "linux.xdg"


@linux
def test_registro_x11_usa_xss(isolado, monkeypatch):
    from jarvis.platform.linux_x11.session import XssSession

    monkeypatch.setattr(XssSession, "_loader", staticmethod(_loader_falso()))
    inst = registry.resolve(Cap.SESSION, X11)
    try:
        assert inst.name == "linux_x11.xss"
    finally:
        inst.close()
