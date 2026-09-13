"""F1-09: pyautogui protegido nos módulos de gesto.

AST: o import de pyautogui fica dentro de um Try nos dois arquivos.
Runtime: com sys.modules["pyautogui"]=None o controller ainda importa — só roda
onde mediapipe existe (o venv Linux não tem; ver checagem AST).
"""
import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ARQUIVOS = [
    REPO_ROOT / "gesture_interface" / "main.py",
    REPO_ROOT / "gesture_interface" / "desktop_control" / "controller.py",
]


def _import_pyautogui_em_try(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for s in node.body:
                if isinstance(s, ast.Import) and any(a.name == "pyautogui" for a in s.names):
                    return True
    return False


@pytest.mark.parametrize("path", ARQUIVOS, ids=lambda p: p.name)
def test_pyautogui_dentro_de_try(path):
    assert _import_pyautogui_em_try(path), f"import pyautogui deve estar em try/except em {path}"


def test_controller_importa_com_pyautogui_none(monkeypatch):
    pytest.importorskip("mediapipe", reason="dep pesada ausente no venv Linux; ver checagem AST acima")
    monkeypatch.setitem(sys.modules, "pyautogui", None)
    sys.modules.pop("gesture_interface.desktop_control.controller", None)
    import importlib
    mod = importlib.import_module("gesture_interface.desktop_control.controller")
    assert mod.pyautogui is None
