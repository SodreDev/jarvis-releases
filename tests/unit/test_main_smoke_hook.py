"""K — contrato (F1-10): gancho de smoke boot em `main.py`. Só leitura de
texto/AST — nunca importa `main.py`. `xfail(strict=True, reason="F1-10")`.
"""
import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = REPO_ROOT / "main.py"


def _parse_main():
    source = MAIN_PY.read_text(encoding="utf-8")
    return source, ast.parse(source, filename=str(MAIN_PY))


def _find_function(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _line_of_first_occurrence(source: str, needle: str, start: int = 1, end: int | None = None) -> int:
    lines = source.splitlines()
    end = end or len(lines)
    for i in range(start, end + 1):
        if needle in lines[i - 1]:
            return i
    raise AssertionError(f"{needle!r} não encontrado entre as linhas {start}-{end}")


def _innermost_wrapping_if(tree: ast.AST, lineno: int):
    """Menor `ast.If` cujo corpo contém `lineno`, mas que COMEÇA antes dela
    (exclui o próprio `if` quando a âncora É uma linha de `if`)."""
    best = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        start, end = node.lineno, getattr(node, "end_lineno", node.lineno)
        if start < lineno <= end:
            if best is None or (end - start) < (best.end_lineno - best.lineno):
                best = node
    return best


def _test_calls_smoke_helper(if_node: ast.If) -> bool:
    for node in ast.walk(if_node.test):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "_smoke_seconds":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "_smoke_seconds":
                return True
    return False


def test_smoke_seconds_helper_exists_at_module_level():
    _source, tree = _parse_main()
    fn = _find_function(tree, "_smoke_seconds")
    assert fn is not None, "helper `_smoke_seconds()` não encontrado em main.py"
    assert fn.col_offset == 0, "`_smoke_seconds` precisa ser função de nível de módulo"


def test_all_jarvis_smoke_seconds_reads_go_through_helper():
    source, tree = _parse_main()
    fn = _find_function(tree, "_smoke_seconds")
    assert fn is not None
    fn_start, fn_end = fn.lineno, getattr(fn, "end_lineno", fn.lineno)

    for i, line in enumerate(source.splitlines(), start=1):
        if "JARVIS_SMOKE_SECONDS" in line and not (fn_start <= i <= fn_end):
            pytest.fail(f"main.py:{i} lê JARVIS_SMOKE_SECONDS fora de _smoke_seconds(): {line!r}")


def test_playwright_chromium_check_gated_by_helper():
    source, tree = _parse_main()
    lineno = _line_of_first_occurrence(source, "PlaywrightChromiumCheck")
    guard = _innermost_wrapping_if(tree, lineno)
    assert guard is not None, "criação da thread PlaywrightChromiumCheck não está dentro de nenhum `if`"
    assert _test_calls_smoke_helper(guard), "o `if` que envolve PlaywrightChromiumCheck não chama _smoke_seconds()"


def test_wake_mode_restoration_gated_inside_on_webview_ready():
    source, tree = _parse_main()
    method = _find_function(tree, "_on_webview_ready")
    assert method is not None
    m_start, m_end = method.lineno, getattr(method, "end_lineno", method.lineno)

    lineno = _line_of_first_occurrence(
        source, 'if self._activation_mode == "wake":', start=m_start, end=m_end
    )
    guard = _innermost_wrapping_if(tree, lineno)
    assert guard is not None, "restauração do modo wake não está dentro de outro `if`"
    assert _test_calls_smoke_helper(guard)


def test_update_checker_gated_inside_on_webview_ready():
    source, tree = _parse_main()
    method = _find_function(tree, "_on_webview_ready")
    assert method is not None
    m_start, m_end = method.lineno, getattr(method, "end_lineno", method.lineno)

    lineno = _line_of_first_occurrence(
        source, "self._iniciar_verificador_updates()", start=m_start, end=m_end
    )
    guard = _innermost_wrapping_if(tree, lineno)
    assert guard is not None, "verificador de updates não está dentro de nenhum `if`"
    assert _test_calls_smoke_helper(guard)


def test_smoke_ready_and_exit_markers_are_printed():
    source, _tree = _parse_main()
    assert "JARVIS_SMOKE_READY" in source
    assert "JARVIS_SMOKE_EXIT" in source


def test_smoke_threads_marker_and_shutdown_are_gated():
    source, tree = _parse_main()
    assert "JARVIS_SMOKE_THREADS" in source

    threads_line = _line_of_first_occurrence(source, "JARVIS_SMOKE_THREADS")
    threads_guard = _innermost_wrapping_if(tree, threads_line)
    assert threads_guard is not None and _test_calls_smoke_helper(threads_guard), (
        "o print JARVIS_SMOKE_THREADS deve ficar sob if _smoke_seconds()"
    )

    # o encerramento (os._exit) logo depois também fica no if de modo smoke
    exit_line = _line_of_first_occurrence(source, "os._exit(0)", start=threads_line)
    exit_guard = _innermost_wrapping_if(tree, exit_line)
    assert exit_guard is not None and _test_calls_smoke_helper(exit_guard), (
        "o os._exit(0) do smoke deve ficar sob if _smoke_seconds()"
    )
