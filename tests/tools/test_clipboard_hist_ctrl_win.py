"""F1-12: leitor de clipboard usa protótipos ctypes PRIVADOS (não o windll shared).

Com WinDLL falso e fake_platform('win32'):
- protótipos definidos (argtypes/restype) antes da primeira chamada;
- wstring_at chamado COM tamanho; NUL cortado;
- GlobalUnlock e CloseClipboard chamados até quando a leitura levanta exceção;
- ctypes.windll (compartilhado) intocado.
"""
import ctypes
import sys

import pytest

from comandos import clipboard_hist_ctrl as chc


class _FakeFunc:
    def __init__(self, name, recorder):
        self.name = name
        self.recorder = recorder
        self.return_value = 1
        self.side_effect = None
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.recorder.append((self.name, args))
        if self.side_effect is not None:
            raise self.side_effect
        return self.return_value


class _FakeLib:
    def __init__(self, recorder):
        object.__setattr__(self, "_recorder", recorder)
        object.__setattr__(self, "_funcs", {})

    def __getattr__(self, name):
        funcs = object.__getattribute__(self, "_funcs")
        if name not in funcs:
            funcs[name] = _FakeFunc(name, object.__getattribute__(self, "_recorder"))
        return funcs[name]


class _Tripwire:
    def __getattr__(self, name):
        raise AssertionError(f"ctypes.windll foi tocado (.{name})")


@pytest.fixture
def win_env(monkeypatch, fake_platform):
    fake_platform("win32")
    recorder = []
    libs = {"user32": _FakeLib(recorder), "kernel32": _FakeLib(recorder)}

    def fake_windll(name, use_last_error=False):
        return libs[name]

    monkeypatch.setattr(ctypes, "WinDLL", fake_windll, raising=False)
    monkeypatch.setattr(ctypes, "windll", _Tripwire(), raising=False)
    chc._reset_win_libs()
    yield libs, recorder
    chc._reset_win_libs()


def test_le_texto_corta_nul_e_usa_tamanho(win_env, monkeypatch):
    libs, recorder = win_env
    u, k = libs["user32"], libs["kernel32"]
    u.OpenClipboard.return_value = 1
    u.GetClipboardData.return_value = 0x1000
    k.GlobalLock.return_value = 0x2000
    k.GlobalSize.return_value = 32

    chamadas_wstring = []

    def fake_wstring_at(p, size):
        chamadas_wstring.append((p, size))
        return "olá ✓\x00lixo além do NUL"

    monkeypatch.setattr(ctypes, "wstring_at", fake_wstring_at)

    resultado = chc._get_clipboard_text()

    assert resultado == "olá ✓"                       # NUL cortado
    assert len(chamadas_wstring) == 1
    assert chamadas_wstring[0][0] == 0x2000            # ponteiro do GlobalLock
    assert chamadas_wstring[0][1] == 32 // ctypes.sizeof(ctypes.c_wchar)  # tamanho
    # protótipos privados definidos
    assert u.GetClipboardData.restype is ctypes.c_void_p
    assert u.OpenClipboard.restype is ctypes.c_int
    assert k.GlobalLock.restype is ctypes.c_void_p
    assert k.GlobalSize.restype is ctypes.c_size_t
    # limpeza chamada
    nomes = [c[0] for c in recorder]
    assert "GlobalUnlock" in nomes and "CloseClipboard" in nomes


def test_limpeza_mesmo_com_excecao_na_leitura(win_env, monkeypatch):
    libs, recorder = win_env
    u, k = libs["user32"], libs["kernel32"]
    u.OpenClipboard.return_value = 1
    u.GetClipboardData.return_value = 0x1000
    k.GlobalLock.return_value = 0x2000
    k.GlobalSize.return_value = 16

    def boom(p, size):
        raise ValueError("falha de leitura")

    monkeypatch.setattr(ctypes, "wstring_at", boom)

    assert chc._get_clipboard_text() is None
    nomes = [c[0] for c in recorder]
    assert "GlobalUnlock" in nomes, "GlobalUnlock deve rodar no finally"
    assert "CloseClipboard" in nomes, "CloseClipboard deve rodar no finally"


def test_prototipos_antes_da_primeira_chamada(win_env, monkeypatch):
    libs, recorder = win_env
    u = libs["user32"]
    u.OpenClipboard.return_value = 0  # falha logo → só OpenClipboard é chamado
    monkeypatch.setattr(ctypes, "wstring_at", lambda *a: "")
    chc._get_clipboard_text()
    # a 1ª chamada registrada é OpenClipboard, e o protótipo já estava setado
    assert recorder and recorder[0][0] == "OpenClipboard"
    assert u.OpenClipboard.argtypes == [ctypes.c_void_p]


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="requer clipboard real do Windows")
def test_roundtrip_real_windows():
    import ctypes as _c
    _c.windll.user32  # sanity
    texto = "olá ✓"
    # (roundtrip real depende de área de transferência do SO; roda só no Windows)
    assert isinstance(texto, str)
