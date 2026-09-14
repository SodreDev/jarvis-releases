"""Clipboard no Wayland com wl-clipboard (F2-04).

- ``get_text`` = ``wl-paste --no-newline --type text`` (código ≠ 0 → None).
- ``set_text`` = ``wl-copy`` com o texto no stdin. O wl-copy fica em segundo plano
  servindo a seleção: a saída não é capturada (senão a leitura esperaria esse
  processo) e ele NÃO é registrado como filho.
- ``can_watch``: sonda ``wl-paste --list-types`` uma vez. "data-control" no stderr
  quer dizer que este wl-clipboard não fala o protocolo do compositor (o KWin só
  tem ext-data-control-v1, que exige wl-clipboard ≥ 2.3.0; o Fedora 44 traz
  2.2.1^git), então a decisão sai da sonda e não da string de versão. Sem
  ``--watch`` próprio, numa sessão KDE o monitor usa o Klipper se ele estiver no
  D-Bus; senão ``can_watch`` = False (D-F2-8: monitor desligado).
- ``watch`` = ``wl-paste --type text --watch echo __JARVIS_CLIP__`` (filho
  registrado); cada marcador dispara ``get_text()``; ``stop`` encerra o PID.
"""
from __future__ import annotations

import os
import subprocess
import threading
from typing import Sequence

from ..common.base import BackendBase, Probe
from ..linux import tools
from ..linux.clipboard_klipper import KlipperClipboard, klipper_available

MARCADOR = "__JARVIS_CLIP__"
COPY_TIMEOUT = 3.0


def copy_via_stdin(argv: Sequence[str], text: str, *, timeout: float = COPY_TIMEOUT) -> bool:
    """Roda uma ferramenta de cópia (wl-copy, xclip, xsel) com o texto no stdin.

    Sem shell e sem capturar a saída: essas ferramentas ficam em segundo plano
    servindo a seleção. Ainda em primeiro plano depois do timeout conta como
    cópia feita (é o processo servindo a seleção).
    """
    exe = tools.which(argv[0])
    if exe is None:
        return False
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    try:
        proc = subprocess.Popen(
            [exe, *argv[1:]],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            close_fds=True,
        )
    except OSError:
        return False
    try:
        proc.communicate(input=str(text).encode("utf-8"), timeout=timeout)
    except subprocess.TimeoutExpired:
        return True
    return proc.returncode == 0


def _encerrar(proc) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def _encerrar_quando_parar(proc, stop) -> None:
    while not stop.wait(0.5):
        if proc.poll() is not None:
            return
    _encerrar(proc)


class WlClipboard(BackendBase):
    name = "linux_wayland.wl_clipboard"

    def __init__(self, ctx=None):
        self.ctx = ctx
        self._lock = threading.Lock()
        self._watch_proprio = None  # None = ainda não sondado

    @classmethod
    def probe(cls, ctx) -> Probe:
        faltando = [t for t in ("wl-paste", "wl-copy") if tools.which(t) is None]
        if faltando:
            return Probe(False, f"{', '.join(faltando)} ausente no PATH")
        return Probe(True)

    def get_text(self):
        r = tools.run_tool(["wl-paste", "--no-newline", "--type", "text"])
        if r is None or r.returncode != 0:
            return None
        return r.stdout

    def set_text(self, text: str) -> bool:
        return copy_via_stdin(["wl-copy"], text)

    # ── monitor ──────────────────────────────────────────────────────────────
    def _wl_paste_watch_ok(self) -> bool:
        with self._lock:
            if self._watch_proprio is None:
                r = tools.run_tool(["wl-paste", "--list-types"])
                self._watch_proprio = r is not None and "data-control" not in (r.stderr or "").lower()
            return self._watch_proprio

    def _klipper_assume(self) -> bool:
        desktops = getattr(self.ctx, "desktops", ()) or ()
        return "kde" in desktops and klipper_available()

    @property
    def can_watch(self) -> bool:
        return self._wl_paste_watch_ok() or self._klipper_assume()

    def watch(self, on_change, stop) -> bool:
        if self._wl_paste_watch_ok():
            return self._watch_wl_paste(on_change, stop)
        if self._klipper_assume():
            return KlipperClipboard(self.ctx).watch(on_change, stop)
        return False

    def _watch_wl_paste(self, on_change, stop) -> bool:
        exe = tools.which("wl-paste")
        if exe is None:
            return False
        try:
            proc = subprocess.Popen(
                [exe, "--type", "text", "--watch", "echo", MARCADOR],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                encoding="utf-8",
                errors="replace",
                close_fds=True,
            )
        except OSError as e:
            print(f"[CLIPBOARD] wl-paste --watch não iniciou: {e}")
            return False
        from jarvis.platform import processes

        processes().register_child(proc)
        threading.Thread(
            target=_encerrar_quando_parar, args=(proc, stop), daemon=True, name="wl-paste-watch-stop"
        ).start()
        try:
            for linha in proc.stdout:
                if stop.is_set():
                    break
                if MARCADOR in linha:
                    texto = self.get_text()
                    if texto:
                        on_change(texto)
        finally:
            _encerrar(proc)
            proc.stdout.close()
        if not stop.is_set():
            print(f"[CLIPBOARD] wl-paste --watch terminou (código {proc.returncode}); monitor parado.")
        return True
