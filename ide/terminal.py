# -*- coding: utf-8 -*-
"""
ide.terminal — Sessão de PTY/processo por projeto.

No Windows usamos `pywinpty` se disponível; caso contrário, fallback
para `subprocess.Popen` + stdin/stdout pipes (sem interatividade de
TUI complexa, mas suficiente para a maioria dos comandos).
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from typing import Dict, Optional

try:
    import winpty  # type: ignore
    HAS_WINPTY = True
except Exception:
    winpty = None
    HAS_WINPTY = False


class TerminalSession:
    def __init__(self, cwd: str, *, cols: int = 100, rows: int = 30):
        self.cwd = cwd
        self.cols = cols
        self.rows = rows
        self._proc = None
        self._winpty = None
        self._buf = bytearray()
        self._lock = threading.RLock()
        self._listeners: list = []
        self._alive = False

    def start(self) -> None:
        if HAS_WINPTY:
            self._winpty = winpty.PTY(self.cols, self.rows)
            shell = os.environ.get("COMSPEC", "cmd.exe")
            self._winpty.spawn(shell, cwd=self.cwd)
            self._alive = True
            threading.Thread(target=self._reader_winpty, daemon=True).start()
        else:
            import subprocess
            shell = os.environ.get("COMSPEC", "cmd.exe")
            self._proc = subprocess.Popen(
                shell, cwd=self.cwd, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                bufsize=0, creationflags=0,
            )
            self._alive = True
            threading.Thread(target=self._reader_pipe, daemon=True).start()

    def _reader_winpty(self) -> None:
        while self._alive and self._winpty:
            try:
                data = self._winpty.read(4096, blocking=True)
                if not data:
                    continue
                if isinstance(data, str):
                    data = data.encode("utf-8", errors="replace")
                self._emit(data)
            except Exception:
                self._alive = False
                break

    def _reader_pipe(self) -> None:
        assert self._proc and self._proc.stdout
        while self._alive:
            chunk = self._proc.stdout.read(1024)
            if not chunk:
                self._alive = False
                break
            self._emit(chunk)

    def _emit(self, data: bytes) -> None:
        with self._lock:
            self._buf += data
            if len(self._buf) > 200_000:
                self._buf = self._buf[-100_000:]
        for cb in list(self._listeners):
            try:
                cb(data)
            except Exception:
                pass

    def write(self, data: str) -> None:
        if HAS_WINPTY and self._winpty:
            self._winpty.write(data)
        elif self._proc and self._proc.stdin:
            try:
                self._proc.stdin.write(data.encode("utf-8", errors="replace"))
                self._proc.stdin.flush()
            except Exception:
                pass

    def add_listener(self, cb) -> None:
        self._listeners.append(cb)

    def remove_listener(self, cb) -> None:
        try:
            self._listeners.remove(cb)
        except ValueError:
            pass

    def buffer(self) -> bytes:
        with self._lock:
            return bytes(self._buf)

    def close(self) -> None:
        self._alive = False
        if self._winpty:
            try: self._winpty.close()
            except Exception: pass
        if self._proc:
            try: self._proc.terminate()
            except Exception: pass


# ─────────────────────────────────────────────────────────────────────────────
# Registry (uma sessão por projeto)
# ─────────────────────────────────────────────────────────────────────────────
_sessions: Dict[str, TerminalSession] = {}
_lock = threading.RLock()


def get_session(project_path: str, *, cwd: str | None = None) -> TerminalSession:
    """Obtém ou cria uma sessão de terminal.

    `project_path` é a chave da sessão (pode ser composta como `path::id`
    para multi-terminal). `cwd` é o diretório inicial — usa `project_path`
    se não informado e não for composto.
    """
    start_cwd = cwd or (project_path if "::" not in project_path else project_path.split("::")[0])
    with _lock:
        s = _sessions.get(project_path)
        if s and s._alive:
            return s
        s = TerminalSession(start_cwd)
        s.start()
        _sessions[project_path] = s
        return s


def close_session(project_path: str) -> None:
    with _lock:
        s = _sessions.pop(project_path, None)
        if s:
            s.close()


__all__ = ["TerminalSession", "get_session", "close_session", "HAS_WINPTY"]
