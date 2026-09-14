"""K F2-05 (N1): notifier do Linux.

- DbusNotifier fala com um notification-daemon FALSO (template do python-dbusmock)
  num D-Bus PRIVADO (fixture private_session_bus), nunca com o D-Bus do host.
- NotifySendNotifier usa um notify-send falso (fixture fake_tools).
- REGISTRY: D-Bus → notify-send em linux-wayland e linux-x11; headless e win32
  sem notifier (o win32 nem sonda).
"""
import subprocess
import sys
import time

import pytest

pytestmark = [
    pytest.mark.linux_only,
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="notifier só no Linux"),
]

from jarvis.platform import registry  # noqa: E402
from jarvis.platform.capabilities import Cap  # noqa: E402
from jarvis.platform.common.unavailable import Unavailable  # noqa: E402
from jarvis.platform.detect import detect  # noqa: E402
from jarvis.platform.linux import dbus as jdbus  # noqa: E402
from jarvis.platform.linux import notifier, tools  # noqa: E402
from jarvis.platform.linux.app_id import APP_ID, APP_NAME  # noqa: E402

WAYLAND = detect(sys_platform="linux", environ={"WAYLAND_DISPLAY": "wayland-0"}, frozen=False)
X11 = detect(sys_platform="linux", environ={"DISPLAY": ":0"}, frozen=False)
HEADLESS = detect(sys_platform="linux", environ={}, frozen=False)
WIN32 = detect(sys_platform="win32", environ={}, frozen=False)

CADEIA = [
    "jarvis.platform.linux.notifier:DbusNotifier",
    "jarvis.platform.linux.notifier:NotifySendNotifier",
]


@pytest.fixture(autouse=True)
def _isolado(monkeypatch, tmp_path):
    """Sem barramento privado, o D-Bus aponta para um socket inexistente; caches limpos."""
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/sem-barramento")
    jdbus.reset()
    tools.clear_which_cache()
    registry._clear_all()
    yield
    registry._clear_all()
    tools.clear_which_cache()
    jdbus.reset()


@pytest.fixture
def daemon_falso(private_session_bus):
    """notification-daemon do dbusmock no barramento privado; encerra só o PID dele."""
    pytest.importorskip("jeepney")
    dbusmock = pytest.importorskip("dbusmock")
    proc, _obj = dbusmock.DBusTestCase.spawn_server_template(
        "notification_daemon", {}, stdout=subprocess.DEVNULL
    )
    try:
        yield proc
    finally:
        jdbus.reset()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _valor(v):
    """Desembrulha a variante do jeepney: (assinatura, valor) → valor."""
    return v[1] if isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str) else v


def _chamadas_notify():
    (linhas,) = jdbus.call(
        notifier.BUS_NAME, notifier.OBJECT_PATH, "org.freedesktop.DBus.Mock",
        "GetMethodCalls", "s", ("Notify",),
    )
    return [[_valor(v) for v in args] for _ts, args in linhas]


# ── DbusNotifier no daemon falso ─────────────────────────────────────────────────

def test_dbus_notify_chega_ao_daemon_com_os_argumentos(daemon_falso):
    assert notifier.DbusNotifier.probe(WAYLAND).ok
    n = notifier.DbusNotifier(WAYLAND)
    assert n.notify("Alarme", "Reunião às 15h", urgency="critical", timeout_ms=5000) is True

    (args,) = _chamadas_notify()
    assert args[:5] == [APP_NAME, 0, "", "Alarme", "Reunião às 15h"]
    assert list(args[5]) == []
    assert args[6]["urgency"] == ("y", 2)
    assert args[6]["desktop-entry"] == ("s", APP_ID)
    assert args[7] == 5000


def test_dbus_notify_padrao_normal_e_timeout_do_servidor(daemon_falso):
    assert notifier.DbusNotifier(X11).notify("titulo", "corpo") is True
    (args,) = _chamadas_notify()
    assert args[6]["urgency"] == ("y", 1)
    assert args[7] == -1


def test_dbus_sonda_sem_daemon_falha_rapido(private_session_bus):
    pytest.importorskip("jeepney")
    inicio = time.monotonic()
    p = notifier.DbusNotifier.probe(WAYLAND)
    assert p.ok is False
    assert "sem dono" in p.reason
    assert time.monotonic() - inicio <= 1.2


def test_dbus_notify_sem_daemon_devolve_false(private_session_bus):
    pytest.importorskip("jeepney")
    assert notifier.DbusNotifier(WAYLAND).notify("titulo", "corpo") is False


def test_dbus_sonda_sem_barramento_nao_levanta():
    assert notifier.DbusNotifier.probe(WAYLAND).ok is False


@pytest.mark.parametrize(
    "entrada, byte",
    [("low", 0), ("normal", 1), ("critical", 2), ("CRITICAL", 2), (" low ", 0), ("urgente", 1), (None, 1)],
)
def test_mapa_de_urgencia_e_assinatura(monkeypatch, entrada, byte):
    chamadas = []
    monkeypatch.setattr(notifier._dbus, "call", lambda *a, **k: chamadas.append(a) or (1,))
    assert notifier.DbusNotifier(WAYLAND).notify("t", "b", urgency=entrada) is True
    dest, path, iface, metodo, assinatura, args, _timeout = chamadas[0]
    assert (dest, path, iface, metodo) == (
        "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
        "org.freedesktop.Notifications", "Notify",
    )
    assert assinatura == "susssasa{sv}i"
    assert args[6]["urgency"] == ("y", byte)


# ── NotifySendNotifier com notify-send falso ────────────────────────────────────

def test_notify_send_argumentos(fake_tools):
    calls = fake_tools({"notify-send": "true"})
    assert notifier.NotifySendNotifier.probe(WAYLAND).ok
    ok = notifier.NotifySendNotifier(WAYLAND).notify("Alarme", "corpo", urgency="critical", timeout_ms=5000)
    assert ok is True
    assert calls["notify-send"].read_text().splitlines() == [
        f"-a {APP_NAME} -u critical -h string:desktop-entry:{APP_ID} -t 5000 -- Alarme corpo"
    ]


def test_notify_send_sem_timeout_nao_passa_t(fake_tools):
    calls = fake_tools({"notify-send": "true"})
    assert notifier.NotifySendNotifier(X11).notify("a", "b", urgency="bogus") is True
    linha = calls["notify-send"].read_text().splitlines()[0]
    assert " -t " not in linha
    assert "-u normal" in linha


def test_notify_send_falhou_devolve_false(fake_tools):
    fake_tools({"notify-send": "exit 1"})
    assert notifier.NotifySendNotifier(WAYLAND).notify("a", "b") is False


def test_notify_send_ausente(monkeypatch, tmp_path):
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    monkeypatch.setenv("PATH", str(vazio))
    assert notifier.NotifySendNotifier.probe(WAYLAND).ok is False


# ── REGISTRY ──────────────────────────────────────────────────────────────────────

def test_registro_prefere_dbus_com_daemon(daemon_falso, fake_tools):
    fake_tools({"notify-send": "true"})
    assert registry.resolve(Cap.NOTIFIER, WAYLAND).name == "linux.dbus_notifications"


@pytest.mark.parametrize("ctx", [WAYLAND, X11], ids=["wayland", "x11"])
def test_registro_cai_para_notify_send_sem_daemon(ctx, fake_tools):
    fake_tools({"notify-send": "true"})
    assert registry._chain_for(Cap.NOTIFIER, ctx.kind) == tuple(CADEIA)
    assert registry.resolve(Cap.NOTIFIER, ctx).name == "linux.notify_send"


def test_registro_headless_sem_notifier(fake_tools):
    fake_tools({"notify-send": "true"})
    assert isinstance(registry.resolve(Cap.NOTIFIER, HEADLESS), Unavailable)


def test_registro_win32_sem_notifier_e_sem_sondar(monkeypatch):
    def proibido(*args, **kwargs):
        raise AssertionError("win32 sondou o notifier")

    monkeypatch.setattr(notifier.DbusNotifier, "probe", classmethod(proibido))
    monkeypatch.setattr(notifier.NotifySendNotifier, "probe", classmethod(proibido))
    inst = registry.resolve(Cap.NOTIFIER, WIN32)
    assert isinstance(inst, Unavailable)
    assert inst._tried == []
