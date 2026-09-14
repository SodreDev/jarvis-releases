"""K — contrato (F2-04): `jarvis.platform.linux_wayland.clipboard`,
`jarvis.platform.linux_x11.clipboard` e `jarvis.platform.linux.clipboard_klipper`
(ainda não existem — import dentro de cada teste).
`xfail(strict=True, reason="F2-04")`.
"""
import pytest

from tests.fakes.dbus_services import fake_dbus_service

pytestmark = [pytest.mark.linux_only]


@pytest.fixture
def _reset_jeepney_router():
    """`KlipperClipboard` fala com o Klipper via `jarvis.platform.linux.dbus`
    (jeepney), que mantém um roteador/thread de recepção compartilhado do
    processo (`session_router`). Sem resetar ANTES do `private_session_bus`
    derrubar o `dbus-daemon` privado, a thread receptora do jeepney continua
    lendo do socket que acabou de morrer e registra um `ConnectionResetError`
    inofensivo (barulho no teste). Pedir este fixture DEPOIS de
    `private_session_bus` na assinatura do teste garante que o teardown
    dele roda ANTES (pytest desmonta na ordem inversa de montagem)."""
    yield
    from jarvis.platform.linux.dbus import reset

    reset()


def test_wl_clipboard_get_text(fake_tools):
    from jarvis.platform.linux_wayland.clipboard import WlClipboard

    fake_tools({"wl-paste": 'echo -n "texto colado"'})
    assert WlClipboard().get_text() == "texto colado"


def test_wl_clipboard_get_text_nonzero_exit_is_none(fake_tools):
    from jarvis.platform.linux_wayland.clipboard import WlClipboard

    fake_tools({"wl-paste": "exit 1"})
    assert WlClipboard().get_text() is None


def test_wl_clipboard_can_watch_new_version(fake_tools):
    from jarvis.platform.linux_wayland.clipboard import WlClipboard

    fake_tools({"wl-paste": 'echo "data-control" >&2; exit 0'})
    # wl-clipboard novo (>= 2.3.0, ext-data-control-v1): sem "not
    # implemented"/erro de --watch -> can_watch True. A sonda exata é do
    # executor decidir; aqui só provamos que a fixture de ferramenta falsa
    # dá pra simular os dois casos (novo/velho).
    assert isinstance(WlClipboard().can_watch, bool)


def test_xclip_get_and_set_text(fake_tools):
    from jarvis.platform.linux_x11.clipboard import XclipClipboard

    calls = fake_tools({"xclip": 'echo -n "via xclip"'})
    assert XclipClipboard().get_text() == "via xclip"
    assert "-selection clipboard -o" in calls["xclip"].read_text()


def test_xsel_fallback_when_xclip_missing(fake_tools, monkeypatch):
    from jarvis.platform.linux_x11.clipboard import XselClipboard

    calls = fake_tools({"xsel": 'echo -n "via xsel"'})
    assert XselClipboard().get_text() == "via xsel"
    assert "--clipboard --output" in calls["xsel"].read_text()


def test_klipper_clipboard_get_text(private_session_bus, _reset_jeepney_router):
    from jarvis.platform.linux.clipboard_klipper import KlipperClipboard

    with fake_dbus_service("org.kde.klipper", "/klipper", "org.kde.klipper.klipper") as (mock, _real):
        mock.AddMethod("org.kde.klipper.klipper", "getClipboardContents", "", "s", 'ret = "do klipper"')
        assert KlipperClipboard().get_text() == "do klipper"


def test_klipper_unavailable_without_service(private_session_bus, _reset_jeepney_router):
    from jarvis.platform.linux.clipboard_klipper import KlipperClipboard

    # sem o serviço no barramento privado -> sonda falha
    assert KlipperClipboard().get_text() is None
