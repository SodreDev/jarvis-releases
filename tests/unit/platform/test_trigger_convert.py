"""K — contrato (F2-01): conversão do formato de trigger do pynput
(`"<shift>+g"`) para o formato do portal GlobalShortcuts
(`"SHIFT+g"`) e para o `qt_key` do KGlobalAccel. Módulos ainda não
existem — import dentro de cada teste. `xfail(strict=True, reason="F2-01")`.
"""
import pytest

pytestmark = pytest.mark.xfail(strict=True, reason="F2-01")


def test_portal_trigger_shift_g():
    from jarvis.platform.linux_wayland.hotkeys_portal import convert_trigger_to_portal

    assert convert_trigger_to_portal("<shift>+g") == "SHIFT+g"


def test_portal_trigger_ctrl_alt():
    from jarvis.platform.linux_wayland.hotkeys_portal import convert_trigger_to_portal

    assert convert_trigger_to_portal("<ctrl>+<alt>+j") == "CTRL+ALT+j"


def test_portal_trigger_cmd_becomes_logo():
    from jarvis.platform.linux_wayland.hotkeys_portal import convert_trigger_to_portal

    assert convert_trigger_to_portal("<cmd>+<shift>+g") == "LOGO+SHIFT+g"


def test_qt_key_shift_g():
    from jarvis.platform.linux.hotkeys_kglobalaccel import convert_trigger_to_qt_key

    # Shift = 0x02000000, Key_G = 0x47
    assert convert_trigger_to_qt_key("<shift>+g") == (0x02000000 | 0x47)


def test_qt_key_ctrl_alt_letter():
    from jarvis.platform.linux.hotkeys_kglobalaccel import convert_trigger_to_qt_key

    # Ctrl = 0x04000000, Alt = 0x08000000, letras A-Z = ASCII maiúsculo
    assert convert_trigger_to_qt_key("<ctrl>+<alt>+j") == (0x04000000 | 0x08000000 | ord("J"))


def test_qt_key_meta_modifier():
    from jarvis.platform.linux.hotkeys_kglobalaccel import convert_trigger_to_qt_key

    # Meta = 0x10000000
    assert convert_trigger_to_qt_key("<cmd>+g") == (0x10000000 | 0x47)


def test_qt_key_space():
    from jarvis.platform.linux.hotkeys_kglobalaccel import convert_trigger_to_qt_key

    # Key_Space = 0x20
    assert convert_trigger_to_qt_key("<ctrl>+space") == (0x04000000 | 0x20)
