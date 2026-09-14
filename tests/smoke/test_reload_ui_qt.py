"""N2/N3: `JARVIS_SMOKE_RELOADS=10` não deixa rastro da corrida do
`reload_ui` (F1-13) no `crash.log`, dentro do smoke boot (F1-10).
"""
import os
import subprocess
import sys

import pytest

from tests.smoke._boot_helpers import BOOT_TIMEOUT, REPO_ROOT, skip_unless_sandboxed

pytestmark = [
    pytest.mark.linux_only,
    pytest.mark.x11,
    pytest.mark.needs_display,
    pytest.mark.slow,
]


def test_ten_reloads_leave_no_reload_ui_race_in_crash_log():
    skip_unless_sandboxed()

    crash_log = REPO_ROOT / "crash.log"
    before = crash_log.stat().st_size if crash_log.exists() else 0

    env = dict(os.environ)
    env["JARVIS_SMOKE_SECONDS"] = "8"
    env["JARVIS_SMOKE_RELOADS"] = "10"
    env.setdefault("XDG_SESSION_TYPE", "x11")

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
        proc.kill()  # só o PID que este teste criou
        proc.communicate(timeout=10)
        pytest.fail(f"main.py não saiu em {BOOT_TIMEOUT}s")

    assert proc.returncode == 0, stdout[-4000:]

    if crash_log.exists():
        new_content = crash_log.read_text(encoding="utf-8", errors="replace")[before:]
        assert "_returnValuesCallbacks.reload_ui" not in new_content, new_content[-2000:]
