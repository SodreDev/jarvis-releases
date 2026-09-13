"""Limpeza de processos filhos no Linux (sem Job Object).

Estratégia (ADR §13.2–13.4): registrar os PIDs dos filhos que criamos e, no
atexit, mandar SIGTERM, esperar até 2 s no total e então SIGKILL os que
sobrarem. Para uma árvore (filho criado com start_new_session=True, líder do
próprio grupo) usamos killpg — mas SÓ quando getpgid(pid) == pid, e NUNCA o
nosso próprio grupo. Sem PR_SET_PDEATHSIG (é por thread) e sem handler de
SIGTERM.
"""
from __future__ import annotations

import atexit
import os
import signal
import threading
import time

from ..common.base import BackendBase

_GRACE_TOTAL_S = 2.0


class PosixProcesses(BackendBase):
    name = "linux.posix"

    def __init__(self, ctx=None):
        self.ctx = ctx
        self._children = []  # list[(proc, tree)]
        self._lock = threading.Lock()
        self._cleanup_registered = False

    # ── registro ─────────────────────────────────────────────────────────────
    def register_child(self, proc, *, tree: bool = False) -> None:
        with self._lock:
            self._prune_locked()
            self._children.append((proc, tree))

    def _prune_locked(self) -> None:
        self._children = [(p, t) for (p, t) in self._children if p.poll() is None]

    def alive_children(self) -> list:
        with self._lock:
            self._prune_locked()
            return [p.pid for (p, _t) in self._children]

    # ── limpeza ──────────────────────────────────────────────────────────────
    def install_child_cleanup(self) -> None:
        if not self._cleanup_registered:
            atexit.register(self._cleanup)
            self._cleanup_registered = True

    def _cleanup(self) -> None:
        with self._lock:
            entries = list(self._children)
        # Fase 1: SIGTERM
        for proc, tree in entries:
            self._signal(proc, tree, signal.SIGTERM)
        # Espera até _GRACE_TOTAL_S no total
        deadline = time.monotonic() + _GRACE_TOTAL_S
        while time.monotonic() < deadline:
            if all(proc.poll() is not None for proc, _t in entries):
                break
            time.sleep(0.05)
        # Fase 2: SIGKILL nos que sobraram
        for proc, tree in entries:
            if proc.poll() is None:
                self._signal(proc, tree, signal.SIGKILL)

    def _signal(self, proc, tree: bool, sig: int) -> None:
        pid = proc.pid
        if tree:
            try:
                pgid = os.getpgid(pid)
            except (ProcessLookupError, OSError):
                pgid = None
            # killpg só se o filho é líder do próprio grupo (start_new_session)
            # e nunca o nosso próprio grupo.
            if pgid is not None and pgid == pid and pgid != os.getpgrp():
                try:
                    os.killpg(pgid, sig)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                return
        # Fallback: sinaliza só o processo.
        try:
            if sig == signal.SIGKILL:
                proc.kill()
            else:
                proc.terminate()
        except (ProcessLookupError, OSError):
            pass

    # ── criação ──────────────────────────────────────────────────────────────
    def new_session_kwargs(self) -> dict:
        return {"start_new_session": True}

    def hidden_console_flags(self) -> int:
        return 0
