"""O que só existe no POSIX, num lugar só e com a recusa dita no Windows (P11).

O mypy do CI roda nos dois sistemas, e cada um enxerga só o `typeshed` do seu: `os.getuid`,
`os.getsid`, `socket.AF_UNIX`, `os.killpg` e `signal.SIGKILL` não existem no Windows. O código
que só faz sentido no POSIX (o host nativo do navegador, a tabela de processos, o grupo de
processos da caixa) pede essas coisas aqui. No Linux o comportamento é o mesmo de chamar o
`os`/`socket` direto; no Windows a chamada falha com um `OSError` que diz qual caminho ainda
não tem equivalente — em vez de um `AttributeError` mudo no meio do laço.

A forma `if sys.platform != "win32": ... raise` não é estilo: é a única que o mypy aceita nos
dois sistemas sem `type: ignore` (um `raise` antecipado deixa o resto "inalcançável" no outro).
"""

from __future__ import annotations

import os
import signal
import socket
import sys
from typing import Final

if sys.platform == "win32":
    SINAL_DE_MATAR: Final = signal.SIGTERM
    """No Windows `os.kill(pid, SIGTERM)` é `TerminateProcess`: o fim forçado de lá."""
else:
    SINAL_DE_MATAR: Final = signal.SIGKILL


def _so_posix(o_que: str) -> OSError:
    return OSError(f"{o_que} só existe no POSIX: este caminho ainda não tem equivalente no Windows")


def uid_atual() -> int:
    """O uid real deste processo."""
    if sys.platform != "win32":
        return os.getuid()
    raise _so_posix("uid do processo")


def sessao_atual() -> int:
    """O id da sessão deste processo (`getsid(0)`)."""
    if sys.platform != "win32":
        return os.getsid(0)
    raise _so_posix("sessão do processo (getsid)")


def soquete_unix() -> socket.socket:
    """Um socket `AF_UNIX` em fluxo, ainda sem conectar."""
    if sys.platform != "win32":
        return socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    raise _so_posix("socket AF_UNIX")


def matar_o_grupo(pid: int) -> None:
    """Fim forçado do grupo de processos de `pid` (filho lançado com `start_new_session`).

    No Windows não há grupo de processos POSIX: termina só o próprio processo.
    """
    if sys.platform == "win32":
        os.kill(pid, SINAL_DE_MATAR)
    else:
        os.killpg(os.getpgid(pid), SINAL_DE_MATAR)
