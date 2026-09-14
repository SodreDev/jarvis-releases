"""N2/N3: smoke de hotkeys reais (F2-01). N2 valida o backend `pynput`
(X11); N3 valida o backend `kglobalaccel` (Wayland/KDE, fallback do
portal -- o `xdg-desktop-portal-kde` real não roda no container sem o
Plasma, SPEC F2-01) com um press simulado via `JARVIS_SMOKE_PTT=press`
(`invoke_shortcut`, sem input físico). Só roda dentro do container
(`JARVIS_TEST_SANDBOXED=1`).

`JARVIS_SMOKE_HOTKEYS=1` faz `main.py` imprimir
`JARVIS_SMOKE_HOTKEYS backend=<nome>` -- é o gancho real da SPEC, não
uma variável de override que main.py nunca leu (`JARVIS_HOTKEYS_BACKEND`
não existe: quem decide o backend é a sonda de `jarvis.platform` pelo
`ctx.kind`, não uma env var).
"""
import pytest

from tests.smoke._boot_helpers import run_boot_smoke, skip_unless_sandboxed

pytestmark = [pytest.mark.linux_only, pytest.mark.needs_display, pytest.mark.slow]


@pytest.mark.x11
def test_hotkeys_backend_is_pynput_on_x11():
    skip_unless_sandboxed()
    stdout = run_boot_smoke("linux-x11", session_type="x11", extra_env={"JARVIS_SMOKE_HOTKEYS": "1"})
    assert "JARVIS_SMOKE_HOTKEYS backend=pynput" in stdout, stdout[-4000:]


@pytest.mark.wayland
def test_hotkeys_backend_is_kglobalaccel_and_ptt_press_on_wayland():
    skip_unless_sandboxed()
    stdout = run_boot_smoke(
        "linux-wayland",
        session_type="wayland",
        extra_env={"JARVIS_SMOKE_HOTKEYS": "1", "JARVIS_SMOKE_PTT": "press"},
    )
    assert "JARVIS_SMOKE_HOTKEYS backend=kglobalaccel" in stdout, stdout[-4000:]
    assert "JARVIS_SMOKE_PTT press" in stdout, stdout[-4000:]
