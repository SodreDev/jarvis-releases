"""Execução na thread da GUI do Qt (F2-02).

``run_in_gui_thread(contexto, fn, timeout=5)`` roda ``fn`` na thread do objeto Qt
``contexto`` (a janela do pywebview, ``window.native``, ou o ``QApplication``) e
devolve o resultado:
- chamado da própria thread da GUI, roda ``fn`` na hora (esperar ali travaria o loop);
- de outra thread, agenda com ``QTimer.singleShot(0, contexto, ...)`` e espera o
  resultado num ``threading.Event``; estourou o ``timeout``, devolve None;
- exceção dentro de ``fn`` é levantada de novo em quem chamou.
PySide6 só é importado dentro da função.
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Optional


def run_in_gui_thread(contexto, fn: Callable[[], Any], timeout: float = 5.0) -> Optional[Any]:
    from PySide6.QtCore import QCoreApplication, QThread, QTimer

    if contexto is None:
        contexto = QCoreApplication.instance()
    if contexto is None:
        raise RuntimeError("run_in_gui_thread: sem QApplication")
    if QThread.currentThread() is contexto.thread():
        return fn()

    feito = threading.Event()
    caixa = {}

    def _executar():
        try:
            caixa["valor"] = fn()
        except BaseException as e:  # devolve para quem chamou
            caixa["erro"] = e
        finally:
            feito.set()

    QTimer.singleShot(0, contexto, _executar)
    if not feito.wait(timeout):
        return None
    if "erro" in caixa:
        raise caixa["erro"]
    return caixa.get("valor")
