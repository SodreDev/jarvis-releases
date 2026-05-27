"""
Runtime hook do PyInstaller — redireciona stdout/stderr para arquivo de log
junto ao executável, para capturar erros de inicialização.
"""
import sys
import os
import traceback

# Arquivo de log fica na mesma pasta do .exe
_log_path = os.path.join(os.path.dirname(sys.executable), "jarvis_startup.log")

class _Tee:
    def __init__(self, path, original):
        self._original = original
        try:
            self._f = open(path, "w", encoding="utf-8", errors="replace")
        except Exception:
            self._f = None

    def write(self, data):
        if self._f:
            try:
                self._f.write(data)
                self._f.flush()
            except Exception:
                pass
        try:
            if self._original:
                self._original.write(data)
        except Exception:
            pass

    def flush(self):
        if self._f:
            try:
                self._f.flush()
            except Exception:
                pass

    def fileno(self):
        raise AttributeError("_Tee has no fileno")

    def isatty(self):
        return False

sys.stdout = _Tee(_log_path + ".stdout.txt", sys.__stdout__)
sys.stderr = _Tee(_log_path + ".stderr.txt", sys.__stderr__)

# Handler global para exceções não tratadas
def _excepthook(exc_type, exc_value, exc_tb):
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        with open(_log_path + ".crash.txt", "w", encoding="utf-8") as f:
            f.write(msg)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _excepthook
