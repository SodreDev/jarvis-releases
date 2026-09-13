"""K — contrato (F1-06, F1-07): AST de `main.py`. Nunca importa `main.py`
(efeitos colaterais no import — grava log, migra credenciais, carrega libs
pesadas): só faz `ast.parse` do texto fonte.
"""
import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = REPO_ROOT / "main.py"


def _parse_main():
    source = MAIN_PY.read_text(encoding="utf-8")
    return source, ast.parse(source, filename=str(MAIN_PY))


def _import_webview_line(tree: ast.AST) -> int:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "webview":
                    return node.lineno
    raise AssertionError("`import webview` não encontrado em main.py")


def _calls_named(tree: ast.AST, name: str) -> list[ast.Call]:
    """Chamadas `name(...)` ou `<algo>.name(...)` em qualquer lugar da árvore."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == name:
            found.append(node)
        elif isinstance(func, ast.Attribute) and func.attr == name:
            found.append(node)
    return found


def _webview_start_calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "start"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "webview"
    ]


def test_webview_bootstrap_precedes_import_and_start_uses_kwargs():
    _source, tree = _parse_main()
    import_line = _import_webview_line(tree)

    engine_calls = _calls_named(tree, "webview_engine")
    prepare_calls = _calls_named(tree, "prepare_env")
    start_kwargs_calls = _calls_named(tree, "start_kwargs")
    assert engine_calls, "nenhuma chamada a webview_engine() encontrada"
    assert prepare_calls, "nenhuma chamada a prepare_env() encontrada"
    assert start_kwargs_calls, "nenhuma chamada a start_kwargs() encontrada"
    assert engine_calls[0].lineno < import_line
    assert prepare_calls[0].lineno < import_line
    assert start_kwargs_calls[0].lineno < import_line

    start_calls = _webview_start_calls(tree)
    assert start_calls, "nenhuma chamada webview.start(...) encontrada"
    call = start_calls[0]

    has_double_star = any(kw.arg is None for kw in call.keywords)
    assert has_double_star, "webview.start(...) precisa receber **_wv_start_kwargs"

    # demais argumentos iguais aos de 1c32e38: _on_ready posicional,
    # debug= e storage_path= — nada além disso mudou nesta tarefa.
    named_kwargs = {kw.arg for kw in call.keywords if kw.arg is not None}
    assert named_kwargs == {"debug", "storage_path"}
    assert len(call.args) == 1


def test_main_storage_expressions_no_longer_read_appdata_directly():
    source, _tree = _parse_main()
    assert 'os.environ.get("APPDATA"' not in source
