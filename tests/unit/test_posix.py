"""`jarvis.posix`: no POSIX é o mesmo que chamar o `os`/`socket` direto.

Os corpos ficam sob `if sys.platform != "win32"` além do `skipif`: o mypy do CI do Windows lê
este arquivo e lá `os.getuid`, `socket.AF_UNIX` e `signal.SIGKILL` não existem.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys

import pytest

from jarvis.posix import SINAL_DE_MATAR, matar_o_grupo, sessao_atual, soquete_unix, uid_atual

so_posix = pytest.mark.skipif(sys.platform == "win32", reason="POSIX")


@so_posix
def test_no_posix_e_o_mesmo_que_o_os() -> None:
    if sys.platform != "win32":
        assert uid_atual() == os.getuid()
        assert sessao_atual() == os.getsid(0)
        assert SINAL_DE_MATAR == signal.SIGKILL
        with soquete_unix() as s:
            assert s.family == socket.AF_UNIX and s.type == socket.SOCK_STREAM


@so_posix
def test_matar_o_grupo_leva_o_filho_que_lidera_a_sessao() -> None:
    filho = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    try:
        matar_o_grupo(filho.pid)
        assert filho.wait(timeout=5) == -SINAL_DE_MATAR
    finally:
        if filho.poll() is None:
            filho.kill()
            filho.wait(timeout=5)
