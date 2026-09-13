"""Configuração do log de crash nativo (faulthandler).

Captura segfaults/abort de C-extensions (sounddevice, pywebview/CEF, etc.) que
escapam ao sys.excepthook do Python, mantendo o arquivo sob controle de tamanho.

Motivo (F1-11): o crash_native.log era aberto em modo append e nunca
rotacionado. A rotação na abertura limita o tamanho ENTRE sessões.

Motivo (F1-11b): no Windows o faulthandler.enable() instala um handler
vetorizado que despeja TODAS as threads mesmo quando o ctypes converte a access
violation em OSError (foram 45.788 dumps vindos de clipboard_hist_ctrl.py:30).
Como isso acontece DENTRO de uma sessão, a rotação não basta: um guardião
daemon vigia o crescimento do arquivo na sessão e desarma o faulthandler se
passar do teto. JARVIS_FAULTHANDLER=0 desliga tudo (nem abre o arquivo).
"""
from __future__ import annotations

import datetime
import faulthandler
import os
import threading

DEFAULT_MAX_BYTES = 5_000_000
DEFAULT_MAX_SESSION_BYTES = 20_000_000
DEFAULT_INTERVAL_S = 30.0

_DESARMADO_MARKER = "=== faulthandler DESARMADO: teto da sessão ===\n"


def _rotate_if_needed(path: str, max_bytes: int) -> None:
    """Se o log passar de max_bytes, move para <path>.1 (só 1 cópia antiga)."""
    try:
        if os.path.exists(path) and os.path.getsize(path) > max_bytes:
            backup = path + ".1"
            try:
                if os.path.exists(backup):
                    os.remove(backup)
            except OSError:
                pass
            os.replace(path, backup)
    except OSError:
        pass


class FaulthandlerGuard(threading.Thread):
    """Vigia o crescimento do log NA sessão e desarma o faulthandler no teto.

    A cada ``interval_s`` compara o tamanho atual (os.fstat) com o de quando foi
    armado; se o crescimento passar de ``max_session_bytes``, chama
    faulthandler.disable(), escreve o marcador de desarme e para.
    """

    def __init__(self, fp, max_session_bytes: int, interval_s: float):
        super().__init__(daemon=True, name="FaulthandlerGuard")
        self._fp = fp
        self._max = max_session_bytes
        self._interval = interval_s
        self._stop = threading.Event()
        try:
            self._baseline = os.fstat(fp.fileno()).st_size
        except OSError:
            self._baseline = 0

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                size = os.fstat(self._fp.fileno()).st_size
            except OSError:
                return
            if size - self._baseline > self._max:
                try:
                    faulthandler.disable()
                except Exception:
                    pass
                try:
                    self._fp.write(_DESARMADO_MARKER)
                    self._fp.flush()
                except Exception:
                    pass
                return


def setup_native_crash_log(
    path: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_session_bytes: int = DEFAULT_MAX_SESSION_BYTES,
    interval_s: float = DEFAULT_INTERVAL_S,
    environ=None,
):
    """Arma o faulthandler gravando em ``path``, com rotação e teto de sessão.

    - JARVIS_FAULTHANDLER=0 → não arma nem abre o arquivo; devolve None.
    - Cria o diretório se preciso e rotaciona o log se passou de ``max_bytes``.
    - Abre o arquivo, liga faulthandler.enable(all_threads) e sobe um
      FaulthandlerGuard daemon que desarma no teto da sessão.

    Retorna o objeto de arquivo aberto (mantenha vivo p/ o GC não fechar) ou None.
    Comportamento no Windows idêntico, salvo o teto de sessão (F1-11b).
    """
    if environ is None:
        environ = os.environ
    if environ.get("JARVIS_FAULTHANDLER") == "0":
        return None

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass

    _rotate_if_needed(path, max_bytes)

    fp = open(path, "a", buffering=1, encoding="utf-8", errors="replace")
    fp.write(f"\n=== faulthandler armado em {datetime.datetime.now()} ===\n")
    faulthandler.enable(file=fp, all_threads=True)

    FaulthandlerGuard(fp, max_session_bytes, interval_s).start()
    return fp
