"""N2/N3: smoke de encerramento com áudio (F2-10c). Com
`JARVIS_SMOKE_AUDIO=1`, `main.py` enfileira um WAV sintético (numpy) no
`_audio_queue`, exercitando o `ffplay` sob `SDL_AUDIODRIVER=dummy`, e
troca o `os._exit(0)` forçado do smoke por `sys.exit(0)` normal (via
`_plat_processes().shutdown_children(2.0)` + `threading.Timer` de
segurança). Aceite da SPEC F2-10c: código 0, `children_alive=0` e SEM
`JARVIS_SMOKE_FORCED_EXIT`. Só roda dentro do container
(`JARVIS_TEST_SANDBOXED=1`).

Enquanto F2-10c não existe (não é módulo importável -- é código dentro
do `__main__` de `main.py`), os dois casos são COLETADOS mas pulam com
motivo claro em vez de rodar contra um `main.py` que ainda não entende
`JARVIS_SMOKE_AUDIO` (mesmo padrão de `test_hotkeys_n2_n3.py`).
"""
import os
import subprocess
import sys

import pytest

from tests.smoke._boot_helpers import BOOT_TIMEOUT, REPO_ROOT, skip_unless_sandboxed

pytestmark = [pytest.mark.linux_only, pytest.mark.needs_display, pytest.mark.slow]


def _f2_10c_ready() -> bool:
    source = (REPO_ROOT / "main.py").read_text(encoding="utf-8", errors="replace")
    return "JARVIS_SMOKE_AUDIO" in source and "shutdown_children" in source


def _run_audio_exit_smoke(kind: str, *, session_type: str) -> None:
    env = dict(os.environ)
    env["JARVIS_SMOKE_SECONDS"] = "8"
    env["JARVIS_SMOKE_AUDIO"] = "1"
    env["SDL_AUDIODRIVER"] = "dummy"
    env["XDG_SESSION_TYPE"] = session_type

    proc = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        stdout, _ = proc.communicate(timeout=BOOT_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()  # só o PID que este teste criou -- nunca pkill/killall
        proc.communicate(timeout=10)
        pytest.fail(f"main.py não saiu em {BOOT_TIMEOUT}s (kind={kind})")

    assert proc.returncode == 0, stdout[-4000:]
    assert f"JARVIS_SMOKE_READY kind={kind}" in stdout, stdout[-4000:]
    assert "JARVIS_SMOKE_FORCED_EXIT" not in stdout, stdout[-4000:]

    lines = [line for line in stdout.splitlines() if line.strip()]
    exit_line = next((l for l in lines if l.startswith("JARVIS_SMOKE_EXIT children_alive=")), None)
    assert exit_line is not None, lines[-5:]
    children_alive = exit_line.split("=", 1)[1].strip()
    assert children_alive == "0", stdout[-4000:]


@pytest.mark.x11
def test_audio_exit_clean_on_x11():
    if not _f2_10c_ready():
        pytest.skip("F2-10c ainda não implementado (JARVIS_SMOKE_AUDIO/shutdown_children em main.py)")
    skip_unless_sandboxed()
    _run_audio_exit_smoke("linux-x11", session_type="x11")


@pytest.mark.wayland
def test_audio_exit_clean_on_wayland():
    if not _f2_10c_ready():
        pytest.skip("F2-10c ainda não implementado (JARVIS_SMOKE_AUDIO/shutdown_children em main.py)")
    skip_unless_sandboxed()
    _run_audio_exit_smoke("linux-wayland", session_type="wayland")
