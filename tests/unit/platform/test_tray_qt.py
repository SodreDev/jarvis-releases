"""K — contrato (F2-02): `jarvis.platform.linux.tray_qt` (QSystemTrayIcon,
ainda não existe — import dentro de cada teste). N2/N3 (precisa de display
real via Xvfb/KWin virtual). `xfail(strict=True, reason="F2-02")`.
"""
import pytest

pytestmark = [
    pytest.mark.linux_only,
    pytest.mark.x11,
    pytest.mark.needs_display,
    pytest.mark.xfail(strict=True, reason="F2-02"),
]


def test_tray_menu_has_four_items_in_order():
    from PySide6.QtWidgets import QApplication

    from jarvis.platform.linux.tray_qt import QtTray

    QApplication.instance() or QApplication([])

    calls = []
    tray = QtTray(
        icon_path=None,
        on_restaurar=lambda: calls.append("restaurar"),
        on_briefing=lambda: calls.append("briefing"),
        on_encerrar=lambda: calls.append("encerrar"),
    )
    actions = tray.menu().actions()
    labels = [a.text() for a in actions if not a.isSeparator()]
    assert labels == ["Restaurar JARVIS", "Briefing", "Encerrar"]
    assert any(a.isSeparator() for a in actions)


def test_tray_starts_hidden_and_callbacks_fire():
    from PySide6.QtWidgets import QApplication

    from jarvis.platform.linux.tray_qt import QtTray

    QApplication.instance() or QApplication([])

    calls = []
    tray = QtTray(
        icon_path=None,
        on_restaurar=lambda: calls.append("restaurar"),
        on_briefing=lambda: calls.append("briefing"),
        on_encerrar=lambda: calls.append("encerrar"),
    )
    assert tray.isVisible() is False

    restaurar_action = next(a for a in tray.menu().actions() if a.text() == "Restaurar JARVIS")
    restaurar_action.trigger()
    assert calls == ["restaurar"]


def test_tray_default_action_is_restaurar():
    from PySide6.QtWidgets import QApplication

    from jarvis.platform.linux.tray_qt import QtTray

    QApplication.instance() or QApplication([])

    tray = QtTray(icon_path=None, on_restaurar=lambda: None, on_briefing=lambda: None, on_encerrar=lambda: None)
    restaurar_action = next(a for a in tray.menu().actions() if a.text() == "Restaurar JARVIS")
    assert tray.menu().defaultAction() is restaurar_action
