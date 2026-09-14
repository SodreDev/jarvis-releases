"""open_path no Windows (F2-06): cópia literal do que main.py e comandos/ faziam.

W1/W2:
- ``open`` = ``os.startfile(target)``: devolve True e PROPAGA a exceção (os call
  sites continuam com o mesmo try/except de antes);
- ``open_text_file`` = ``subprocess.Popen(["notepad.exe", path], close_fds=True)``.
``os.startfile``/``subprocess.Popen`` são importados só na chamada e podem ser
injetados (``startfile_fn``/``popen_fn``) para os testes rodarem no Linux.
"""
from __future__ import annotations

from ..common.base import BackendBase


class StartfileOpenPath(BackendBase):
    name = "windows.startfile"

    def __init__(self, ctx=None, *, startfile_fn=None, popen_fn=None):
        self.ctx = ctx
        self._startfile_fn = startfile_fn
        self._popen_fn = popen_fn

    def open(self, target: str) -> bool:
        startfile = self._startfile_fn
        if startfile is None:
            import os
            startfile = os.startfile  # type: ignore[attr-defined]
        startfile(target)
        return True

    def open_text_file(self, path: str) -> bool:
        popen = self._popen_fn
        if popen is None:
            import subprocess
            popen = subprocess.Popen
        popen(["notepad.exe", path], close_fds=True)
        return True
