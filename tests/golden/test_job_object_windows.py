"""C/K (F1-14): Job Object → `jarvis.platform.windows.processes`. É a
mudança de MAIOR risco Windows da fase 1 (código de limpeza de processos
filhos movido praticamente sem alteração).

`xfail(strict=True, reason="F1-14")`: `install_kill_on_close_job` ainda
não existe (import dentro do teste). `ctypes.wintypes` importa normalmente
no Linux (testado); só `ctypes.WinDLL` não existe — por isso só ele (e
`get_last_error`) é substituído; `Structure`/`byref`/`sizeof`/os `c_*`
continuam sendo os reais do `ctypes` do host.
"""
import ctypes
import types
from ctypes import wintypes

import pytest

from tests.golden.legacy_1c32e38 import legacy_job_object

pytestmark = pytest.mark.xfail(strict=True, reason="F1-14")


class _FakeWinFunc:
    """Uma "função" de DLL falsa: chamável, com `.restype`/`.argtypes`
    setáveis (o código real faz `kernel32.Foo.restype = ...`) e que
    registra cada chamada numa lista compartilhada."""

    def __init__(self, name: str, impl, calls: list):
        self._name = name
        self._impl = impl
        self._calls = calls
        self.restype = None
        self.argtypes = None

    def __call__(self, *args):
        self._calls.append(self._name)
        return self._impl(*args)


class FakeKernel32:
    def __init__(self, *, create_ok=True, set_info_ok=True, assign_ok=True, raise_on=None):
        self.calls: list[str] = []
        self.set_info_args = None

        def _create(*_a):
            if raise_on == "CreateJobObjectW":
                raise OSError("CreateJobObjectW explodiu")
            return 1 if create_ok else 0

        def _set_info(handle, info_class, info_ref, info_size):
            if raise_on == "SetInformationJobObject":
                raise OSError("SetInformationJobObject explodiu")
            self.set_info_args = (handle, info_class, info_ref._obj.BasicLimitInformation.LimitFlags, info_size)
            return 1 if set_info_ok else 0

        def _assign(*_a):
            if raise_on == "AssignProcessToJobObject":
                raise OSError("AssignProcessToJobObject explodiu")
            return 1 if assign_ok else 0

        def _get_current_process(*_a):
            return 999

        self.CreateJobObjectW = _FakeWinFunc("CreateJobObjectW", _create, self.calls)
        self.SetInformationJobObject = _FakeWinFunc("SetInformationJobObject", _set_info, self.calls)
        self.AssignProcessToJobObject = _FakeWinFunc("AssignProcessToJobObject", _assign, self.calls)
        self.GetCurrentProcess = _FakeWinFunc("GetCurrentProcess", _get_current_process, self.calls)


def _fake_ctypes(kernel32) -> types.ModuleType:
    fake = types.ModuleType("ctypes")
    fake.__dict__.update(ctypes.__dict__)  # Structure/byref/sizeof/c_* reais
    fake.WinDLL = lambda name, use_last_error=True: kernel32
    fake.get_last_error = lambda: 4242
    return fake


def _install(ct):
    from jarvis.platform.windows.processes import install_kill_on_close_job

    return install_kill_on_close_job(ct=ct, wt=wintypes)


def test_success_sequence_and_limit_flags(capsys):
    oracle_kernel = FakeKernel32()
    real_kernel = FakeKernel32()

    oracle_result = legacy_job_object(_fake_ctypes(oracle_kernel), wintypes)
    real_result = _install(_fake_ctypes(real_kernel))

    # GetCurrentProcess() é avaliado como argumento de AssignProcessToJobObject
    # ANTES da própria chamada (ordem de avaliação de argumentos do Python).
    expected_calls = [
        "CreateJobObjectW",
        "SetInformationJobObject",
        "GetCurrentProcess",
        "AssignProcessToJobObject",
    ]
    assert oracle_kernel.calls == expected_calls
    assert real_kernel.calls == expected_calls

    assert oracle_kernel.set_info_args[2] == 0x2800
    assert real_kernel.set_info_args[2] == 0x2800

    assert oracle_result  # handle retido
    assert real_result

    out = capsys.readouterr().out
    assert "[JOB] Job Object criado (KILL_ON_JOB_CLOSE), assigned=True" in out


def test_create_job_object_fails(capsys):
    oracle_kernel = FakeKernel32(create_ok=False)
    real_kernel = FakeKernel32(create_ok=False)

    oracle_result = legacy_job_object(_fake_ctypes(oracle_kernel), wintypes)
    real_result = _install(_fake_ctypes(real_kernel))

    assert oracle_kernel.calls == ["CreateJobObjectW"]
    assert real_kernel.calls == ["CreateJobObjectW"]
    assert oracle_result is None
    assert real_result is None
    assert "[JOB] CreateJobObjectW falhou: err=4242" in capsys.readouterr().out


def test_set_information_job_object_fails(capsys):
    oracle_kernel = FakeKernel32(set_info_ok=False)
    real_kernel = FakeKernel32(set_info_ok=False)

    oracle_result = legacy_job_object(_fake_ctypes(oracle_kernel), wintypes)
    real_result = _install(_fake_ctypes(real_kernel))

    assert oracle_kernel.calls == ["CreateJobObjectW", "SetInformationJobObject"]
    assert real_kernel.calls == ["CreateJobObjectW", "SetInformationJobObject"]
    assert oracle_result is None
    assert real_result is None
    assert "[JOB] SetInformationJobObject falhou: err=4242" in capsys.readouterr().out


def test_exception_is_swallowed_and_reported(capsys):
    oracle_kernel = FakeKernel32(raise_on="CreateJobObjectW")
    real_kernel = FakeKernel32(raise_on="CreateJobObjectW")

    oracle_result = legacy_job_object(_fake_ctypes(oracle_kernel), wintypes)
    real_result = _install(_fake_ctypes(real_kernel))

    assert oracle_result is None
    assert real_result is None
    out = capsys.readouterr().out
    assert "[JOB] Falha ao configurar Job Object: CreateJobObjectW explodiu" in out
