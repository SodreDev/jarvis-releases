"""C — caracterização (F2-06): `open_path`/`open_text_file` no Windows
precisam continuar idênticos depois da fachada `jarvis.platform.open_path`
entrar. Precisa passar HOJE (antes de F2-06 existir) e continuar depois.
"""
from tests.golden.legacy_31bc0ce import (
    legacy_open_path_windows,
    legacy_open_text_file_windows,
)


def test_startfile_called_once_with_same_argument():
    calls = []

    def fake_startfile(target):
        calls.append(target)

    legacy_open_path_windows(fake_startfile, r"C:\Users\ana\Downloads\relatorio.pdf")
    assert calls == [r"C:\Users\ana\Downloads\relatorio.pdf"]


def test_startfile_propagates_exception():
    def fake_startfile(_target):
        raise OSError("arquivo não encontrado")

    try:
        legacy_open_path_windows(fake_startfile, "x.txt")
    except OSError as e:
        assert str(e) == "arquivo não encontrado"
    else:
        raise AssertionError("esperava OSError propagada")


def test_open_text_file_is_notepad_literal():
    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))

    legacy_open_text_file_windows(fake_popen, r"C:\temp\longo.txt")
    assert calls == [(["notepad.exe", r"C:\temp\longo.txt"], {"close_fds": True})]
