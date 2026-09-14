"""C — caracterização (F2-02): montagem do menu/ícone pystray no Windows
continuam idênticos depois da fachada `Cap.TRAY` entrar.
"""
from tests.golden.legacy_31bc0ce import legacy_criar_tray_icon, legacy_criar_tray_menu


class _FakeMenuItem:
    def __init__(self, label, callback, *, default=False):
        self.label = label
        self.callback = callback
        self.default = default


class _SeparatorSentinel:
    pass


class _FakeMenu:
    SEPARATOR = _SeparatorSentinel()

    def __init__(self, *items):
        self.items = items


class _FakeIcon:
    def __init__(self, name, image, title, menu):
        self.name = name
        self.image = image
        self.title = title
        self.menu = menu
        self.visible = None


def _fake_pystray():
    import types

    return types.SimpleNamespace(Menu=_FakeMenu, MenuItem=_FakeMenuItem, Icon=_FakeIcon)


def test_tray_menu_has_four_items_in_order():
    pystray = _fake_pystray()
    on_restaurar, on_briefing, on_encerrar = object(), object(), object()
    menu = legacy_criar_tray_menu(
        pystray, on_restaurar=on_restaurar, on_briefing=on_briefing, on_encerrar=on_encerrar
    )
    assert len(menu.items) == 4
    restaurar, briefing, sep, encerrar = menu.items
    assert restaurar.label == "Restaurar JARVIS"
    assert restaurar.callback is on_restaurar
    assert restaurar.default is True
    assert briefing.label == "Briefing"
    assert briefing.callback is on_briefing
    assert briefing.default is False
    assert sep is _FakeMenu.SEPARATOR
    assert encerrar.label == "Encerrar"
    assert encerrar.callback is on_encerrar


def test_tray_icon_construction_and_starts_hidden():
    pystray = _fake_pystray()
    menu = legacy_criar_tray_menu(pystray, on_restaurar=None, on_briefing=None, on_encerrar=None)
    image = object()
    icon = legacy_criar_tray_icon(pystray, image, menu)
    assert icon.name == "JARVIS"
    assert icon.image is image
    assert icon.title == "J.A.R.V.I.S."
    assert icon.menu is menu
    assert icon.visible is False
