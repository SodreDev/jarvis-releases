"""reload_ui não pode ter corrida com a ponte JS do pywebview.

Testa a peça extraída (core.ui_reload.UiReloadScheduler), sem pywebview real:
- request() retorna na hora, sem chamar o reload dentro da chamada;
- o reload acontece depois, uma única vez, agendado fora da chamada;
- várias chamadas dentro da janela de debounce viram UM reload só;
- o tema aplicado é o último pedido.
"""
import threading
import time

from core.ui_reload import DEFAULT_DEBOUNCE_MS, UiReloadScheduler


def _spy():
    chamadas = []
    ev = threading.Event()

    def reload_fn(theme):
        chamadas.append(theme)
        ev.set()

    return reload_fn, chamadas, ev


def test_request_retorna_sem_recarregar_na_hora():
    reload_fn, chamadas, _ = _spy()
    sched = UiReloadScheduler(reload_fn, debounce_ms=200)
    sched.request("dark")
    # logo após o request, o reload ainda NÃO ocorreu (é adiado)
    assert chamadas == []


def test_reload_ocorre_depois_uma_vez():
    reload_fn, chamadas, ev = _spy()
    sched = UiReloadScheduler(reload_fn, debounce_ms=50)
    sched.request("light")
    assert ev.wait(2.0), "o reload deveria ter ocorrido após o debounce"
    time.sleep(0.1)
    assert chamadas == ["light"]


def test_debounce_coalesce_varias_chamadas():
    reload_fn, chamadas, ev = _spy()
    sched = UiReloadScheduler(reload_fn, debounce_ms=150)
    # rajada de F5/Ctrl+R dentro da janela de debounce
    for _ in range(5):
        sched.request("dark")
        time.sleep(0.01)
    assert ev.wait(2.0)
    time.sleep(0.1)
    assert chamadas == ["dark"], f"esperava 1 reload, veio {chamadas}"


def test_tema_preservado_e_o_ultimo():
    reload_fn, chamadas, ev = _spy()
    sched = UiReloadScheduler(reload_fn, debounce_ms=100)
    sched.request("dark")
    time.sleep(0.02)
    sched.request("light")  # muda o tema dentro da janela
    assert ev.wait(2.0)
    time.sleep(0.1)
    assert chamadas == ["light"]


def test_debounce_padrao_300ms():
    assert DEFAULT_DEBOUNCE_MS == 300
