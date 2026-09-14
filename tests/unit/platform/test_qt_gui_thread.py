"""K — contrato (F2-02, gate): `jarvis.platform.linux.qt_gui.run_in_gui_thread`
precisa funcionar chamado de uma thread QUE NÃO É a do Qt — é o pré-requisito
de F2-02 (tray) e de qualquer chamada Qt vinda de fora do main loop.
N2/N3 (precisa de display real via Xvfb/KWin virtual). Ainda não existe —
import dentro do teste. `xfail(strict=True, reason="F2-02")`.
"""
import threading
import time

import pytest

pytestmark = [
    pytest.mark.linux_only,
    pytest.mark.x11,
    pytest.mark.wayland,
    pytest.mark.needs_display,
    pytest.mark.slow,
]


def test_run_in_gui_thread_from_worker_thread():
    from PySide6.QtWidgets import QApplication, QWidget

    from jarvis.platform.linux.qt_gui import run_in_gui_thread

    app = QApplication.instance() or QApplication([])
    window = QWidget()

    result = {}

    def _worker():
        def _fn():
            result["thread_name"] = threading.current_thread().name
            return 42

        result["returned"] = run_in_gui_thread(window, _fn, timeout=5)

    t = threading.Thread(target=_worker, name="worker-nao-qt")
    t.start()

    deadline = time.monotonic() + 6
    while "returned" not in result and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.05)
    t.join(timeout=1)

    assert result.get("returned") == 42
    # a função em si rodou na thread principal (Qt), não na worker
    assert result.get("thread_name") != "worker-nao-qt"


def test_run_in_gui_thread_from_gui_thread_runs_immediately():
    """Chamada JÁ vinda da thread da GUI roda `fn` na hora, sem passar por
    fila/evento nenhum -- esperar ali (como se fosse "de outra thread")
    travaria o próprio loop do Qt que a chamada precisaria pra ser
    processada."""
    from PySide6.QtWidgets import QApplication, QWidget

    from jarvis.platform.linux.qt_gui import run_in_gui_thread

    QApplication.instance() or QApplication([])
    window = QWidget()

    started = time.monotonic()
    result = run_in_gui_thread(window, lambda: 1, timeout=0.2)
    elapsed = time.monotonic() - started
    assert result == 1
    assert elapsed < 0.05, "deveria ter rodado direto, sem esperar timeout nenhum"


def test_run_in_gui_thread_times_out_from_worker_thread_without_event_loop():
    """De uma thread QUE NÃO é a da GUI, sem ninguém bombeando o loop de
    eventos (`processEvents`), o `fn` nunca roda -- tem que estourar o
    timeout (devolve None) em vez de travar pra sempre."""
    from PySide6.QtWidgets import QApplication, QWidget

    from jarvis.platform.linux.qt_gui import run_in_gui_thread

    QApplication.instance() or QApplication([])
    window = QWidget()

    result = {}

    def _worker():
        started = time.monotonic()
        result["returned"] = run_in_gui_thread(window, lambda: 1, timeout=0.2)
        result["elapsed"] = time.monotonic() - started

    t = threading.Thread(target=_worker, name="worker-nao-qt")
    t.start()
    t.join(timeout=2)

    assert not t.is_alive(), "run_in_gui_thread travou em vez de estourar o timeout"
    assert result.get("returned") is None
    assert result.get("elapsed", 99) < 2.0
