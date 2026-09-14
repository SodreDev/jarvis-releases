"""K F2-07 (AST, sem importar main.py nem core.win_locale): session pela fachada.

- main._idle_seconds: `v = _plat_get(Cap.SESSION).idle_seconds()` e devolve 0.0
  quando v é None; o GetLastInputInfo/windll saiu do main.py (vive literal em
  jarvis/platform/windows/session.py);
- core/win_locale.get_timezone_name/get_locale: começam por
  `if not _plat_current().is_windows: return _plat_get(Cap.SESSION).<m>()` e o
  ramo Windows continua lá (winreg / getdefaultlocale).
"""
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _func(rel, nome):
    tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8-sig", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == nome:
            return node
    raise AssertionError(f"{nome} não encontrada em {rel}")


def _chama_plat_get_session(call, metodo):
    return (
        isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
        and call.func.attr == metodo
        and isinstance(call.func.value, ast.Call)
        and isinstance(call.func.value.func, ast.Name) and call.func.value.func.id == "_plat_get"
        and isinstance(call.func.value.args[0], ast.Attribute)
        and call.func.value.args[0].attr == "SESSION"
    )


def test_idle_seconds_do_main_usa_a_fachada():
    func = _func("main.py", "_idle_seconds")
    assert any(_chama_plat_get_session(n, "idle_seconds") for n in ast.walk(func))
    sobras = [n.lineno for n in ast.walk(func)
              if isinstance(n, ast.Attribute) and n.attr in ("windll", "GetLastInputInfo")]
    assert not sobras, f"GetLastInputInfo ainda no main.py: {sobras}"
    retornos = [n for n in ast.walk(func) if isinstance(n, ast.Return)]
    assert any(
        isinstance(r.value, ast.IfExp)
        and isinstance(r.value.body, ast.Constant) and r.value.body.value == 0.0
        and isinstance(r.value.test, ast.Compare) and isinstance(r.value.test.ops[0], ast.Is)
        for r in retornos
    ), "None tem de virar 0.0 (desconhecido = não ausente)"


def _primeiro_stmt(func):
    corpo = func.body
    if corpo and isinstance(corpo[0], ast.Expr) and isinstance(getattr(corpo[0], "value", None), ast.Constant):
        corpo = corpo[1:]
    return corpo


def _checa_ramo_linux(nome, metodo, marca_windows):
    func = _func("core/win_locale.py", nome)
    corpo = _primeiro_stmt(func)
    se = corpo[0]
    assert isinstance(se, ast.If) and isinstance(se.test, ast.UnaryOp) and isinstance(se.test.op, ast.Not)
    teste = se.test.operand
    assert isinstance(teste, ast.Attribute) and teste.attr == "is_windows"
    assert isinstance(teste.value, ast.Call) and teste.value.func.id == "_plat_current"
    assert isinstance(se.body[0], ast.Return) and _chama_plat_get_session(se.body[0].value, metodo)
    resto = ast.Module(body=corpo[1:], type_ignores=[])
    assert any(
        (isinstance(n, ast.Name) and n.id == marca_windows)
        or (isinstance(n, ast.Attribute) and n.attr == marca_windows)
        for n in ast.walk(resto)
    ), f"ramo Windows de {nome} tem de continuar literal ({marca_windows})"


def test_win_locale_get_timezone_name():
    _checa_ramo_linux("get_timezone_name", "timezone_name", "_read_winreg_tz_name")


def test_win_locale_get_locale():
    _checa_ramo_linux("get_locale", "locale", "getdefaultlocale")
