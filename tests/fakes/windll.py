"""Helpers para simular DLLs do Windows (`ctypes.WinDLL`) em testes que
rodam num host Linux. Padrão herdado da fase 1
(`tests/golden/test_job_object_windows.py`), promovido a fixture
compartilhada (`fake_windll`, em `tests/conftest.py`) na tarefa T0 da
fase 2 — os testes golden/K de F2-01, F2-02, F2-03, F2-07, F2-08 e F2-09
reusam isto em vez de reimplementar.

`ctypes.wintypes` importa normalmente num host Linux; só `ctypes.WinDLL`
(e `ctypes.get_last_error`) não existem, então só esses dois são trocados
— `Structure`/`byref`/`sizeof`/os `c_*` continuam sendo os reais do
`ctypes` do host.
"""
from __future__ import annotations

import ctypes
import types
from typing import Callable


class FakeWinFunc:
    """Uma "função" de DLL falsa: chamável, com `.restype`/`.argtypes`
    setáveis (o código real faz `dll.Foo.restype = ...`) e que registra
    cada chamada numa lista compartilhada (`dll.calls`)."""

    def __init__(self, name: str, impl: Callable, calls: list):
        self._name = name
        self._impl = impl
        self._calls = calls
        self.restype = None
        self.argtypes = None

    def __call__(self, *args):
        self._calls.append(self._name)
        return self._impl(*args)


class FakeWinDLL:
    """DLL falsa: `dll.add("CreateJobObjectW", impl)` registra uma
    função chamável (`FakeWinFunc`) como atributo; `dll.calls` é a lista
    compartilhada de nomes chamados, na ordem real de execução."""

    def __init__(self):
        self.calls: list[str] = []

    def add(self, name: str, impl: Callable) -> FakeWinFunc:
        fn = FakeWinFunc(name, impl, self.calls)
        setattr(self, name, fn)
        return fn


def build_fake_ctypes(dlls: dict[str, object], *, last_error: int = 0) -> types.ModuleType:
    """Módulo `ctypes` falso: `WinDLL(name)` devolve `dlls[name]`
    (tipicamente um `FakeWinDLL`); `get_last_error()` devolve
    `last_error`. Todo o resto (`Structure`, `byref`, `sizeof`, `c_*`)
    é o `ctypes` real do host."""
    fake = types.ModuleType("ctypes")
    fake.__dict__.update(ctypes.__dict__)
    fake.WinDLL = lambda name, use_last_error=True: dlls[name]
    fake.get_last_error = lambda: last_error
    return fake
