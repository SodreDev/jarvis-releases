"""open_path no Linux (F2-06): ``xdg-open`` → ``gio open``.

- Sem shell. O processo sai destacado (stdin/stdout/stderr em DEVNULL,
  ``close_fds``, sessão nova) e NÃO é registrado como filho: o app aberto tem de
  sobreviver ao Jarvis.
- Código de saída diferente de zero dentro de 3 s levanta ``OSError``, para o
  ``except`` do call site cair no fallback que já existia. Ainda rodando depois
  de 3 s conta como sucesso, e uma thread daemon faz o ``wait()`` para não
  sobrar zumbi.
- ``open_text_file`` = ``open(path)``: o texto longo abre no editor padrão.
"""
from __future__ import annotations

import subprocess
import threading
from typing import List

from ..common.base import BackendBase, Probe
from . import tools

EXIT_WINDOW = 3.0


def _reap(proc) -> None:
    try:
        proc.wait()
    except Exception:
        pass


class _DetachedOpener(BackendBase):
    name = ""
    tool = ""  # executável procurado pela sonda

    def __init__(self, ctx=None, *, popen_fn=None, exit_window: float = EXIT_WINDOW):
        self.ctx = ctx
        self._popen_fn = popen_fn or subprocess.Popen
        self._exit_window = exit_window

    @classmethod
    def probe(cls, ctx) -> Probe:
        if tools.which(cls.tool):
            return Probe(True)
        return Probe(False, f"{cls.tool} ausente no PATH")

    def _argv(self, target: str) -> List[str]:
        raise NotImplementedError

    def open(self, target: str) -> bool:
        argv = self._argv(str(target))
        proc = self._popen_fn(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        wait = getattr(proc, "wait", None)
        if wait is None:
            return True
        try:
            code = wait(timeout=self._exit_window)
        except subprocess.TimeoutExpired:
            threading.Thread(target=_reap, args=(proc,), daemon=True, name=f"{self.tool}-wait").start()
            return True
        if code != 0:
            raise OSError(f"{argv[0]} saiu com código {code} ao abrir {target!r}")
        return True

    def open_text_file(self, path: str) -> bool:
        return self.open(path)


class XdgOpen(_DetachedOpener):
    name = "linux.xdg_open"
    tool = "xdg-open"

    def _argv(self, target: str) -> List[str]:
        return ["xdg-open", target]


class GioOpen(_DetachedOpener):
    name = "linux.gio_open"
    tool = "gio"

    def _argv(self, target: str) -> List[str]:
        return ["gio", "open", target]
