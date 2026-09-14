"""N2/N3: smoke de hotkeys reais (F2-01). N2 valida o backend `pynput`
(X11); N3 valida o backend `kglobalaccel` (Wayland/KDE) com um press
simulado via `JARVIS_SMOKE_PTT=press`. Só roda dentro do container
(`JARVIS_TEST_SANDBOXED=1`).
"""
import pytest

from tests.smoke._boot_helpers import run_boot_smoke, skip_unless_sandboxed

pytestmark = [pytest.mark.linux_only, pytest.mark.needs_display, pytest.mark.slow]


@pytest.mark.x11
def test_hotkeys_backend_is_pynput_on_x11():
    skip_unless_sandboxed()
    run_boot_smoke("linux-x11", session_type="x11", extra_env={"JARVIS_HOTKEYS_BACKEND": "pynput"})


@pytest.mark.wayland
def test_hotkeys_backend_is_kglobalaccel_and_ptt_press_on_wayland():
    skip_unless_sandboxed()
    run_boot_smoke(
        "linux-wayland",
        session_type="wayland",
        extra_env={
            "JARVIS_HOTKEYS_BACKEND": "kglobalaccel",
            "JARVIS_SMOKE_PTT": "press",
        },
    )
