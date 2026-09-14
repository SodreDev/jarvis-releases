"""C AST (F2-06): cada call site da lista fechada de `os.startfile`
continua passando A MESMA expressão de argumento de `31bc0ce`, seja
chamando `os.startfile`/`_os.startfile` (hoje, antes de F2-06) ou
`_open_path` (depois — mesmo nome de variável/literal, função nova).
Precisa passar HOJE e continuar passando depois de F2-06.

Só leitura de texto/AST — nunca importa `main.py` nem os módulos de
`comandos/` (import teria efeito colateral / dependências pesadas).
"""
import ast
from pathlib import Path

import pytest

from tests.golden.legacy_31bc0ce import (
    NOTEPAD_CALL_SITE_ARGS,
    NOTEPAD_CALL_SITE_LINE,
    OPEN_PATH_CALL_SITES,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _find_call_at_line(tree: ast.AST, lineno: int) -> ast.Call | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.lineno == lineno:
            return node
    return None


def _is_open_path_like(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "startfile":
        return True
    if isinstance(func, ast.Name) and func.id == "_open_path":
        return True
    return False


@pytest.mark.parametrize(
    "file_rel,lineno,expected_arg_src",
    OPEN_PATH_CALL_SITES,
    ids=[f"{f}:{l}" for f, l, _ in OPEN_PATH_CALL_SITES],
)
def test_call_site_matches_golden_argument(file_rel, lineno, expected_arg_src):
    path = REPO_ROOT / file_rel
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    call = _find_call_at_line(tree, lineno)
    assert call is not None, f"nenhuma chamada na linha {lineno} de {file_rel}"
    assert _is_open_path_like(call), (
        f"{file_rel}:{lineno} não é startfile/_os.startfile nem _open_path"
    )
    assert len(call.args) == 1, f"{file_rel}:{lineno} esperava 1 argumento posicional"

    actual_arg_src = ast.get_source_segment(source, call.args[0])
    assert actual_arg_src == expected_arg_src


def test_notepad_call_site_matches_golden():
    path = REPO_ROOT / "main.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    call = _find_call_at_line(tree, NOTEPAD_CALL_SITE_LINE)
    assert call is not None
    assert isinstance(call.func, ast.Attribute) and call.func.attr == "Popen"

    list_arg = call.args[0]
    assert isinstance(list_arg, ast.List)
    items_src = [ast.get_source_segment(source, e) for e in list_arg.elts]
    assert items_src == NOTEPAD_CALL_SITE_ARGS

    close_fds = next((kw for kw in call.keywords if kw.arg == "close_fds"), None)
    assert close_fds is not None
    assert ast.get_source_segment(source, close_fds.value) == "True"
