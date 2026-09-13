"""Utilitário compartilhado por `test_boot_x11.py` e `test_boot_wayland.py`
(N2/N3, marco M1 da SPEC F1-10). Só roda dentro do container
(`JARVIS_TEST_SANDBOXED=1`) e só mexe no PID do `python main.py` que o
próprio teste cria — nunca `pkill`/`killall`/`pgrep -f`.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOT_TIMEOUT = 90.0


def skip_unless_sandboxed():
    if os.environ.get("JARVIS_TEST_SANDBOXED") != "1":
        pytest.skip("smoke de boot só roda dentro do container (JARVIS_TEST_SANDBOXED=1)")


def _log_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def run_boot_smoke(kind: str, *, session_type: str, extra_env: dict | None = None) -> None:
    """Sobe `python main.py` com `JARVIS_SMOKE_SECONDS=8` e cobra o M1 da SPEC:
    stdout com `JARVIS_SMOKE_READY kind=<kind>`, saída 0 em <=90s, nenhuma
    entrada nova em crash.log, crash_native.log <=5MB, última linha
    `JARVIS_SMOKE_EXIT children_alive=<0 ou n/a>`.
    """
    crash_log = REPO_ROOT / "crash.log"
    crash_native_log = REPO_ROOT / "crash_native.log"
    crash_log_before = _log_size(crash_log)

    env = dict(os.environ)
    env["JARVIS_SMOKE_SECONDS"] = "8"
    env["XDG_SESSION_TYPE"] = session_type
    if extra_env:
        env.update(extra_env)

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
        pytest.fail(f"main.py não saiu em {BOOT_TIMEOUT}s (kind={kind})")

    assert proc.returncode == 0, stdout[-4000:]
    assert f"JARVIS_SMOKE_READY kind={kind}" in stdout, stdout[-4000:]

    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines, "main.py não imprimiu nada no stdout"
    last_line = lines[-1]
    assert last_line.startswith("JARVIS_SMOKE_EXIT children_alive="), last_line
    children_alive = last_line.split("=", 1)[1].strip()
    # antes da F1-14 (limpeza de filhos) é aceito "n/a"
    assert children_alive in {"0", "n/a"}, last_line

    assert _log_size(crash_log) == crash_log_before, "crash.log ganhou entrada nova durante o smoke"
    if crash_native_log.exists():
        assert crash_native_log.stat().st_size <= 5_000_000, "crash_native.log passou de 5 MB"
