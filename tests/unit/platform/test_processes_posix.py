"""K — contrato (F1-14): `PosixProcesses` (`jarvis/platform/linux/processes.py`,
ainda não existe — import dentro de cada subprocesso de teste).
`xfail(strict=True, reason="F1-14")`.

Cada cenário roda num SUBPROCESSO Python próprio (nunca no processo do
pytest): só assim dá pra observar o efeito real do `atexit` de
`install_child_cleanup()` sem afetar a sessão de teste. Só PIDs criados
pelo próprio teste são tocados — nada de pkill/killall/pgrep -f.
"""
import os
import subprocess
import sys
import time

_TIMEOUT = 10.0
_DEATH_DEADLINE = 3.0


def _run_child(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=_TIMEOUT
    )


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_dead(pid: int, deadline: float = _DEATH_DEADLINE) -> bool:
    end = time.monotonic() + deadline
    while time.monotonic() < end and _pid_alive(pid):
        time.sleep(0.1)
    return not _pid_alive(pid)


_CHILD_BASIC = """
import subprocess
from jarvis.platform.linux.processes import PosixProcesses

procs = PosixProcesses()
proc = subprocess.Popen(["sleep", "60"])
procs.register_child(proc)
procs.install_child_cleanup()
print(f"SLEEP_PID={proc.pid}", flush=True)
# sai normalmente (sem terminate explícito) -- o atexit tem que limpar
"""


def test_child_cleanup_kills_registered_process_on_normal_exit():
    result = _run_child(_CHILD_BASIC)
    assert result.returncode == 0, result.stderr

    sleep_pid = next(
        (int(l.split("=", 1)[1]) for l in result.stdout.splitlines() if l.startswith("SLEEP_PID=")),
        None,
    )
    assert sleep_pid is not None, result.stdout
    assert _wait_dead(sleep_pid), "sleep 60 registrado continuou vivo após o pai sair"


_CHILD_TREE = """
import subprocess
import sys
from jarvis.platform.linux.processes import PosixProcesses

procs = PosixProcesses()
# "filho" em sessão própria (start_new_session=True) que por sua vez gera
# um NETO -- como um navegador faria com os processos dele. Neto criado
# via Python (subprocess com sys.executable), não `sh -c "... & ..."`:
# /bin/sh é dash no Debian/Ubuntu, cujo job-control ($!) se comporta
# diferente do bash e não reproduzia o cenário de forma confiável.
_grandchild_script = (
    "import subprocess; "
    "p = subprocess.Popen(['sleep', '60']); "
    "print(f'GRANDCHILD_PID={p.pid}', flush=True); "
    "p.wait()"
)
proc = subprocess.Popen(
    [sys.executable, "-c", _grandchild_script],
    start_new_session=True,
    stdout=subprocess.PIPE,
    text=True,
)
print(proc.stdout.readline(), flush=True)
procs.register_child(proc, tree=True)
procs.install_child_cleanup()
"""


def test_tree_true_kills_grandchild():
    result = _run_child(_CHILD_TREE)
    assert result.returncode == 0, result.stderr

    grandchild_pid = next(
        (int(l.split("=", 1)[1]) for l in result.stdout.splitlines() if l.startswith("GRANDCHILD_PID=")),
        None,
    )
    assert grandchild_pid is not None, result.stdout
    assert _wait_dead(grandchild_pid), "neto continuou vivo -- tree=True não matou o grupo"


_CHILD_KILLPG_SPY = """
import atexit, os, subprocess

violations = []
_real_killpg = os.killpg
own_pgrp = os.getpgrp()

def _spy_killpg(pgrp, sig):
    if pgrp == own_pgrp:
        violations.append(pgrp)
    return _real_killpg(pgrp, sig)

os.killpg = _spy_killpg
# registrado ANTES de install_child_cleanup(): atexit roda em LIFO, então
# este print só executa DEPOIS do handler de limpeza (registrado depois).
atexit.register(lambda: print(f"VIOLATIONS={len(violations)}", flush=True))

from jarvis.platform.linux.processes import PosixProcesses

procs = PosixProcesses()
proc = subprocess.Popen(["sleep", "60"], start_new_session=True)
procs.register_child(proc, tree=True)
procs.install_child_cleanup()
"""


def test_killpg_never_called_with_own_process_group():
    result = _run_child(_CHILD_KILLPG_SPY)
    assert result.returncode == 0, result.stderr
    assert "VIOLATIONS=0" in result.stdout, result.stdout
