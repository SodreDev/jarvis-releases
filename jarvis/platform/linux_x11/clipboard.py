"""Clipboard no X11 (F2-04): xclip → xsel.

- ``XclipClipboard``: ``xclip -selection clipboard -o`` / ``-i``;
- ``XselClipboard``: ``xsel --clipboard --output`` / ``--input``;
- ``watch`` = polling de 0,8 s, como no Windows (as regras do histórico ficam no
  ``on_change`` de quem chama).
A cópia usa ``copy_via_stdin``: xclip e xsel ficam em segundo plano servindo a
seleção, então a saída não é capturada e o processo não vira filho registrado.
"""
from __future__ import annotations

from typing import Tuple

from ..common.base import BackendBase, Probe
from ..linux import tools
from ..linux_wayland.clipboard import copy_via_stdin

POLL_INTERVAL = 0.8


class _PollingClipboard(BackendBase):
    name = ""
    tool = ""
    read_args: Tuple[str, ...] = ()
    write_args: Tuple[str, ...] = ()
    can_watch = True

    def __init__(self, ctx=None):
        self.ctx = ctx

    @classmethod
    def probe(cls, ctx) -> Probe:
        if tools.which(cls.tool):
            return Probe(True)
        return Probe(False, f"{cls.tool} ausente no PATH")

    def get_text(self):
        r = tools.run_tool([self.tool, *self.read_args])
        if r is None or r.returncode != 0:
            return None
        return r.stdout

    def set_text(self, text: str) -> bool:
        return copy_via_stdin([self.tool, *self.write_args], text)

    def watch(self, on_change, stop) -> bool:
        while not stop.is_set():
            texto = self.get_text()
            if texto:
                on_change(texto)
            stop.wait(POLL_INTERVAL)
        return True


class XclipClipboard(_PollingClipboard):
    name = "linux_x11.xclip"
    tool = "xclip"
    read_args = ("-selection", "clipboard", "-o")
    write_args = ("-selection", "clipboard", "-i")


class XselClipboard(_PollingClipboard):
    name = "linux_x11.xsel"
    tool = "xsel"
    read_args = ("--clipboard", "--output")
    write_args = ("--clipboard", "--input")
