"""K — contrato (F2-01): `jarvis.platform.linux_wayland.hotkeys_portal`
(ainda não existe — import dentro de cada teste). Portal FALSO no
barramento privado (`private_session_bus` + `fake_dbus_service`), nunca
o `xdg-desktop-portal` do host. `xfail(strict=True, reason="F2-01")`.

Usa só os métodos do Protocol (`jarvis.platform.protocols.Hotkeys`):
`bind(bindings)`, `listen_keys(on_press, on_release)`, `stop()`. Nenhum
detalhe interno (`ensure_session`, `bind_signal_handlers`, ...) — isso
só é observável pelo comportamento no D-Bus falso.

O portal falso segue o fluxo ASSÍNCRONO da SPEC F2-01: `CreateSession` e
`BindShortcuts` devolvem só o caminho do `Request` (tipo `o`); o
resultado de verdade -- `session_handle`, a lista de atalhos e o código
0/1/2 -- chega DEPOIS, pelo sinal `Response` de
`org.freedesktop.portal.Request` NAQUELE caminho, nunca como retorno
direto do método. Isso é o que a produção precisa assinar ANTES de
chamar (SPEC), e é exatamente o que estes testes cobram.

Simplificação do fake: o caminho do `Request` usa só o `handle_token` (o
`AddMethod` dinâmico do dbusmock não expõe o sender real do chamador pro
código Python executado) e a sessão sempre sai em um caminho fixo. Isso
não muda o contrato observável (ordem Register→CreateSession, sessão só
via sinal, códigos 0/1/2), só a string exata dos caminhos.
"""
import time

import dbus
import pytest

from tests.fakes.dbus_services import fake_dbus_service


def _wait_until(predicate, *, timeout: float = 2.0, step: float = 0.02) -> bool:
    """A produção despacha `Activated`/`Deactivated` numa thread própria
    (`PortalHotkeys-sinais`) -- o callback pode não ter rodado ainda no
    instante exato em que `EmitSignal` retorna (fila entre a thread
    receptora do jeepney e a thread despachante). Poll curto em vez de
    assert imediato."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(step)
    return predicate()

pytestmark = [pytest.mark.linux_only]

_PORTAL_BUS = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_SESSION_PATH = "/org/freedesktop/portal/desktop/session/anon/s1"

_CREATE_SESSION_CODE = """
import threading
options = args[0]
token = options.get("handle_token", "t1")
req_path = "/org/freedesktop/portal/desktop/request/anon/" + token
objects[self.path].AddObject(req_path, "org.freedesktop.portal.Request", {}, [])

def _responder(path):
    objects[path].EmitSignal(
        "org.freedesktop.portal.Request",
        "Response",
        "ua{sv}",
        [0, dbus.Dictionary({"session_handle": dbus.String("%s")}, signature="sv")],
    )

# emite com um pequeno atraso, DEPOIS da resposta RPC deste método já ter
# voltado pro chamador -- essencial: a produção assina o caminho PREVISTO
# (calculado com o próprio remetente, que o dbusmock não expõe pro código
# dinâmico do AddMethod) e, se o caminho devolvido por CreateSession for
# diferente (é, aqui: o fake usa "anon" no lugar do remetente real),
# assina TAMBÉM o caminho devolvido -- mas só DEPOIS de receber a
# resposta síncrona da chamada. Emitir o sinal síncrono, antes da
# resposta RPC, faz a produção perder o Response (ela ainda não tinha
# assinado o caminho certo) e travar até o timeout. `req_path` vai como
# ARGUMENTO do Timer (não por closure): função aninhada dentro de um
# `exec(code, globals(), loc)` não fecha sobre nomes de `loc`.
threading.Timer(0.2, _responder, args=(req_path,)).start()
ret = dbus.ObjectPath(req_path)
""" % _SESSION_PATH


def _bind_shortcuts_code(response_code: int) -> str:
    """`BindShortcuts(session, [(id, {description, preferred_trigger})], "",
    {handle_token})` -- `options` é o 4º argumento posicional (`args[3]`).
    Devolve só o caminho do Request; o código de resposta (0/1/2) chega
    pelo sinal `Response`, nunca como retorno direto -- por isso o código
    é escolhido AQUI, no fake, e não por um gancho no construtor de
    produção. Emissão com atraso: mesmo motivo do `_CREATE_SESSION_CODE`."""
    return (
        "import threading\n"
        "options = args[3]\n"
        'token = options.get("handle_token", "bt1")\n'
        'req_path = "/org/freedesktop/portal/desktop/request/anon/" + token\n'
        'objects[self.path].AddObject(req_path, "org.freedesktop.portal.Request", {}, [])\n'
        "def _responder(path):\n"
        "    objects[path].EmitSignal(\n"
        '        "org.freedesktop.portal.Request", "Response", "ua{sv}",\n'
        f'        [{response_code}, dbus.Dictionary({{}}, signature="sv")],\n'
        "    )\n"
        "threading.Timer(0.2, _responder, args=(req_path,)).start()\n"
        "ret = dbus.ObjectPath(req_path)\n"
    )


def _mount_portal(mock, *, bind_response_code: int = 0):
    mock.AddProperty("org.freedesktop.portal.GlobalShortcuts", "version", 2)
    mock.AddMethod("org.freedesktop.host.portal.Registry", "Register", "sa{sv}", "", "")
    mock.AddMethod(
        "org.freedesktop.portal.GlobalShortcuts", "CreateSession", "a{sv}", "o", _CREATE_SESSION_CODE
    )
    mock.AddMethod(
        "org.freedesktop.portal.GlobalShortcuts",
        "BindShortcuts",
        "oa(sa{sv})sa{sv}",
        "o",
        _bind_shortcuts_code(bind_response_code),
    )


def test_registry_register_called_before_create_session(private_session_bus, isolated_home):
    from jarvis.platform.linux_wayland.hotkeys_portal import PortalGlobalShortcuts
    from jarvis.platform.protocols import HotkeyBinding

    with fake_dbus_service(_PORTAL_BUS, _PORTAL_PATH, "org.freedesktop.host.portal.Registry") as (mock, _real):
        _mount_portal(mock)

        binding = HotkeyBinding("ptt", "Falar com o JARVIS", "<shift>+g", lambda: None, lambda: None)
        PortalGlobalShortcuts(app_id="jarvis").bind([binding])

        method_names = [call[1] for call in mock.GetCalls()]
        assert "Register" in method_names and "CreateSession" in method_names
        assert method_names.index("Register") < method_names.index("CreateSession")


def test_session_handle_only_arrives_via_response_signal(private_session_bus, isolated_home):
    """`CreateSession` sozinho não devolve `session_handle` nenhum -- só o
    caminho do Request. `BindShortcuts` só pode ter sido chamado DEPOIS do
    sinal `Response` do `CreateSession` ter entregue a sessão."""
    from jarvis.platform.linux_wayland.hotkeys_portal import PortalGlobalShortcuts
    from jarvis.platform.protocols import HotkeyBinding

    with fake_dbus_service(_PORTAL_BUS, _PORTAL_PATH, "org.freedesktop.host.portal.Registry") as (mock, _real):
        _mount_portal(mock)

        binding = HotkeyBinding("ptt", "Falar com o JARVIS", "<shift>+g", lambda: None, lambda: None)
        PortalGlobalShortcuts(app_id="jarvis").bind([binding])

        calls = [(c[1], c[2]) for c in mock.GetCalls()]
        create_session_calls = [args for name, args in calls if name == "CreateSession"]
        bind_calls = [args for name, args in calls if name == "BindShortcuts"]
        assert create_session_calls, "CreateSession não foi chamado"
        assert bind_calls, "BindShortcuts não foi chamado"
        # a sessão usada no BindShortcuts (1º argumento) é exatamente a que
        # veio pelo sinal Response do CreateSession -- não um valor
        # qualquer inventado sem esperar o sinal.
        assert bind_calls[0][0] == _SESSION_PATH


def test_response_code_1_is_capability_unavailable_and_does_not_repeat(private_session_bus, isolated_home):
    from jarvis.platform.errors import CapabilityUnavailable
    from jarvis.platform.linux_wayland.hotkeys_portal import PortalGlobalShortcuts
    from jarvis.platform.protocols import HotkeyBinding

    with fake_dbus_service(_PORTAL_BUS, _PORTAL_PATH, "org.freedesktop.host.portal.Registry") as (mock, _real):
        # resposta 1 = usuário recusou -- o adapter deve devolver
        # CapabilityUnavailable e marcar internamente pra não repetir o
        # pedido na mesma sessão de processo.
        _mount_portal(mock, bind_response_code=1)

        binding = HotkeyBinding("ptt", "Falar com o JARVIS", "<shift>+g", lambda: None, lambda: None)
        hk = PortalGlobalShortcuts(app_id="jarvis")
        try:
            hk.bind([binding])
        except CapabilityUnavailable as e:
            assert "recusou" in str(e)
        else:
            raise AssertionError("esperava CapabilityUnavailable com resposta 1")

        # segunda chamada não deve refazer o pedido ao portal
        calls_before = len(mock.GetCalls())
        try:
            hk.bind([binding])
        except CapabilityUnavailable:
            pass
        assert len(mock.GetCalls()) == calls_before


def test_activated_signal_becomes_on_press(private_session_bus, isolated_home):
    from jarvis.platform.linux_wayland.hotkeys_portal import PortalGlobalShortcuts
    from jarvis.platform.protocols import HotkeyBinding

    with fake_dbus_service(_PORTAL_BUS, _PORTAL_PATH, "org.freedesktop.host.portal.Registry") as (mock, _real):
        _mount_portal(mock)

        pressed = []
        binding = HotkeyBinding(
            "ptt", "Falar com o JARVIS", "<shift>+g", lambda: pressed.append("press"), lambda: None
        )
        PortalGlobalShortcuts(app_id="jarvis").bind([binding])

        mock.EmitSignal(
            "org.freedesktop.portal.GlobalShortcuts",
            "Activated",
            "osta{sv}",
            [_SESSION_PATH, "ptt", 0, dbus.Dictionary({}, signature="sv")],
        )
        assert _wait_until(lambda: pressed == ["press"]), f"pressed={pressed!r}"


def test_deactivated_signal_becomes_on_release(private_session_bus, isolated_home):
    from jarvis.platform.linux_wayland.hotkeys_portal import PortalGlobalShortcuts
    from jarvis.platform.protocols import HotkeyBinding

    with fake_dbus_service(_PORTAL_BUS, _PORTAL_PATH, "org.freedesktop.host.portal.Registry") as (mock, _real):
        _mount_portal(mock)

        released = []
        binding = HotkeyBinding(
            "ptt", "Falar com o JARVIS", "<shift>+g", lambda: None, lambda: released.append("release")
        )
        PortalGlobalShortcuts(app_id="jarvis").bind([binding])

        mock.EmitSignal(
            "org.freedesktop.portal.GlobalShortcuts",
            "Deactivated",
            "osta{sv}",
            [_SESSION_PATH, "ptt", 0, dbus.Dictionary({}, signature="sv")],
        )
        assert _wait_until(lambda: released == ["release"]), f"released={released!r}"


def test_listen_keys_returns_false():
    from jarvis.platform.linux_wayland.hotkeys_portal import PortalGlobalShortcuts

    assert PortalGlobalShortcuts(app_id="jarvis").listen_keys(lambda k: None, lambda k: None) is False
