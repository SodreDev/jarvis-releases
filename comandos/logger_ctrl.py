# logger_ctrl.py — Logger Central do J.A.R.V.I.S.
# Escreve em @AutomationLog.txt com timestamp + nível + tag.
# Thread-safe via threading.Lock.
# Uso:
#   from comandos.logger_ctrl import get_logger
#   _log = get_logger("MODULO")
#   _log.info("mensagem")
#   _log.warn("algo errado", exc_info=e)
#   _log.error("falha crítica", exc_info=e)
from __future__ import annotations
import os
import time
import threading
import traceback
from typing import Callable, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_PATH = os.path.join(_ROOT, "@AutomationLog.txt")
_MAX_BYTES = 5 * 1024 * 1024   # Roda o arquivo se ultrapassar 5 MB

_lock = threading.Lock()
# Callback opcional: fn(tag, msg) → exibe mensagem de erro na UI
_ui_error_cb: Optional[Callable[[str, str], None]] = None


def set_ui_error_callback(fn: Callable[[str, str], None]) -> None:
    """Registra callback para exibir erros críticos na interface do usuário."""
    global _ui_error_cb
    _ui_error_cb = fn


def _rotate_if_needed() -> None:
    """Mantém o arquivo de log abaixo de _MAX_BYTES com rotação simples."""
    try:
        if os.path.getsize(_LOG_PATH) > _MAX_BYTES:
            backup = _LOG_PATH.replace(".txt", "_old.txt")
            if os.path.exists(backup):
                os.remove(backup)
            os.rename(_LOG_PATH, backup)
    except OSError:
        pass


def _write(level: str, tag: str, message: str, exc: Optional[BaseException]) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [{level}] [{tag}] {message}"
    if exc:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        line += f"\n{tb.rstrip()}"
    line += "\n"
    with _lock:
        _rotate_if_needed()
        try:
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass   # não pode logar que falhou ao logar


class Logger:
    """Logger com nível + tag fixos. Crie via `get_logger(tag)`."""

    def __init__(self, tag: str) -> None:
        self._tag = tag.upper()

    def info(self, message: str, exc_info: Optional[BaseException] = None) -> None:
        _write("INFO", self._tag, message, exc_info)

    def warn(self, message: str, exc_info: Optional[BaseException] = None) -> None:
        _write("WARN", self._tag, message, exc_info)

    def error(self, message: str, exc_info: Optional[BaseException] = None) -> None:
        _write("ERROR", self._tag, message, exc_info)
        # Notifica UI se callback registrado
        if _ui_error_cb:
            try:
                _ui_error_cb(self._tag, message)
            except Exception:
                pass


# Cache de instâncias — evita criar múltiplos objetos para a mesma tag
_loggers: dict[str, Logger] = {}


def get_logger(tag: str) -> Logger:
    """Retorna (e cacheia) uma instância de Logger para a tag fornecida."""
    tag_up = tag.upper()
    if tag_up not in _loggers:
        _loggers[tag_up] = Logger(tag_up)
    return _loggers[tag_up]
