"""O lançador de verdade, com um programa inofensivo (`sleep`) — nada de aplicativo gráfico.

Achado do dono (2026-10-17): `NotImplementedError: posix_spawn: setsid unavailable on this
platform`. O lançador agora usa `subprocess.Popen(start_new_session=True)`, que existe em todo
Python POSIX.
"""

from __future__ import annotations

import os
import shutil
import signal
import sys
import time
from pathlib import Path

import pytest

from jarvis.executor.lancador import App, AppRecusado, lancar, lancar_argv

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX")


def _app(argv: tuple[str, ...]) -> App:
    return App(id="dorminhoco", nome="Dorminhoco", nomes=("Dorminhoco",), argv=argv, arquivo=Path())


def _encerrar(pid: int) -> None:
    """Só o PID que este teste criou, e só depois de conferir que ainda é o `sleep` dele."""
    comm = Path(f"/proc/{pid}/comm")
    if comm.exists() and comm.read_text().strip() == "sleep":
        os.kill(pid, signal.SIGTERM)
        for _ in range(100):
            if not comm.exists() or Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z":
                break
            time.sleep(0.02)


def test_lanca_em_sessao_propria_sem_posix_spawn(monkeypatch: pytest.MonkeyPatch) -> None:
    def sem_posix_spawn(*_a: object, **_k: object) -> int:
        raise NotImplementedError("posix_spawn: setsid unavailable on this platform")

    monkeypatch.setattr(os, "posix_spawn", sem_posix_spawn)
    sleep = shutil.which("sleep")
    assert sleep is not None
    pid = lancar(_app((sleep, "30")))
    try:
        assert pid > 0 and pid != os.getpid()
        assert Path(f"/proc/{pid}/comm").read_text().strip() == "sleep"
        assert os.getsid(pid) == pid, "o filho tem de liderar uma sessão só dele"
        assert os.getsid(pid) != os.getsid(0)
    finally:
        _encerrar(pid)


def test_o_filho_encerrado_nao_vira_zumbi() -> None:
    pid = lancar(_app(("sleep", "30")))
    _encerrar(pid)
    for _ in range(100):
        if not Path(f"/proc/{pid}").exists():
            break
        time.sleep(0.02)
    assert not Path(f"/proc/{pid}").exists(), "a linha que espera o filho não colheu o processo"


def test_lancar_argv_leva_a_url_como_um_unico_argumento(tmp_path: Path) -> None:
    saida = tmp_path / "argv.txt"
    script = tmp_path / "navegador"
    script.write_text(f'#!/bin/sh\nprintf "%s|" "$@" > "{saida}"\n')
    script.chmod(0o755)
    lancar_argv([str(script), "https://exemplo.com/?a=1&b=$(rm -rf ~)"])
    for _ in range(100):
        if saida.exists() and saida.read_text():
            break
        time.sleep(0.02)
    assert saida.read_text() == "https://exemplo.com/?a=1&b=$(rm -rf ~)|"


def test_executavel_que_nao_existe_e_recusa_com_o_nome() -> None:
    with pytest.raises(AppRecusado, match="não está no PATH"):
        lancar(_app(("programa-que-nao-existe-jarvis",)))
