"""N2/N3: smoke de hotkeys reais (F2-01). N2 valida o backend `pynput`
(X11); N3 valida o backend `kglobalaccel` (Wayland/KDE) com um press
simulado via `JARVIS_SMOKE_PTT=press`. Só roda dentro do container
(`JARVIS_TEST_SANDBOXED=1`).

Enquanto F2-01 não existe, os dois casos são COLETADOS (marcadores
certos, sem rc=5) mas pulam com motivo claro em vez de rodar
`main.py` contra variáveis de ambiente que ele ainda não entende (o
que daria um "passou" enganoso, sem testar nada de verdade) — ver
`_f2_01_ready()`. O executor tira esse guard quando os módulos
existirem.
"""
import pytest

from tests.smoke._boot_helpers import run_boot_smoke, skip_unless_sandboxed

pytestmark = [pytest.mark.linux_only, pytest.mark.needs_display, pytest.mark.slow]


def _f2_01_ready() -> bool:
    try:
        import jarvis.platform.linux.hotkeys_kglobalaccel  # noqa: F401
        import jarvis.platform.linux_wayland.hotkeys_portal  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.x11
def test_hotkeys_backend_is_pynput_on_x11():
    if not _f2_01_ready():
        pytest.skip("F2-01 ainda não implementado (jarvis.platform.linux.hotkeys_kglobalaccel/linux_wayland.hotkeys_portal)")
    skip_unless_sandboxed()
    run_boot_smoke("linux-x11", session_type="x11", extra_env={"JARVIS_HOTKEYS_BACKEND": "pynput"})


@pytest.mark.wayland
def test_hotkeys_backend_is_kglobalaccel_and_ptt_press_on_wayland():
    if not _f2_01_ready():
        pytest.skip("F2-01 ainda não implementado (jarvis.platform.linux.hotkeys_kglobalaccel/linux_wayland.hotkeys_portal)")
    skip_unless_sandboxed()
    run_boot_smoke(
        "linux-wayland",
        session_type="wayland",
        extra_env={
            "JARVIS_HOTKEYS_BACKEND": "kglobalaccel",
            "JARVIS_SMOKE_PTT": "press",
        },
    )
