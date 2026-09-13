"""N3: smoke de boot em Wayland (container Fedora 44 ligado ao socket de
um `kwin_wayland --virtual --xwayland` do host). M1 da SPEC F1-10.
"""
import pytest

from tests.smoke._boot_helpers import run_boot_smoke, skip_unless_sandboxed

pytestmark = [
    pytest.mark.linux_only,
    pytest.mark.wayland,
    pytest.mark.needs_display,
    pytest.mark.slow,
]


def test_boot_opens_and_exits_cleanly_on_wayland():
    skip_unless_sandboxed()
    run_boot_smoke("linux-wayland", session_type="wayland")
