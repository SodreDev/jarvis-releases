"""K — contrato (F1-14): `main.py` sem `_JOBOBJECT_*` (movido para
`jarvis/platform/windows/processes.py`) e `register_child(` logo depois do
`Popen` do ffplay (âncora `self._tts_process = proc`).

Só leitura de texto — nunca importa `main.py`.
`xfail(strict=True, reason="F1-14")`.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = REPO_ROOT / "main.py"
_ANCHOR = "self._tts_process = proc"


def test_main_has_no_jobobject_identifiers():
    source = MAIN_PY.read_text(encoding="utf-8")
    assert "_JOBOBJECT_" not in source


def test_register_child_right_after_ffplay_popen():
    lines = MAIN_PY.read_text(encoding="utf-8").splitlines()
    anchor_idx = next(i for i, line in enumerate(lines) if _ANCHOR in line)
    window = lines[anchor_idx : anchor_idx + 6]
    assert any("register_child(" in line for line in window), "\n".join(window)
