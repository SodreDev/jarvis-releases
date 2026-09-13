"""N2: smoke de boot em X11 (dentro do container Fedora 44 + Xvfb). M1 da
SPEC F1-10.
"""
import pytest

from tests.smoke._boot_helpers import run_boot_smoke, skip_unless_sandboxed

pytestmark = [
    pytest.mark.linux_only,
    pytest.mark.x11,
    pytest.mark.needs_display,
    pytest.mark.slow,
]


def test_boot_opens_and_exits_cleanly_on_x11():
    skip_unless_sandboxed()
    run_boot_smoke("linux-x11", session_type="x11")
