"""F1-04 (AST, sem importar main.py): pynput protegido e hotkeys atrás da feature.

- os imports de pynput ficam dentro de um Try cujo except zera keyboard/Key/GlobalHotKeys;
- _SHIFT_KEYS tolera Key == None (atribuição condicional);
- _start_keyboard_listener e _start_global_hotkeys checam _has_feature("global_hotkeys")
  antes de qualquer keyboard.Listener(...) ou GlobalHotKeys(...);
- jarvis.platform entra no hidden do JARVIS.spec e no if False do launcher.py.
"""
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN = REPO_ROOT / "main.py"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))


def _func(tree: ast.Module, nome: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == nome:
            return node
    raise AssertionError(f"função {nome} não encontrada")


def test_import_pynput_dentro_de_try_com_except_que_zera():
    tree = _tree(MAIN)
    achou = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        importa_pynput = any(
            isinstance(s, ast.ImportFrom) and (s.module or "").startswith("pynput")
            for s in node.body
        )
        if not importa_pynput:
            continue
        # algum handler zera keyboard/Key/GlobalHotKeys com None
        for h in node.handlers:
            for stmt in h.body:
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant) \
                        and stmt.value.value is None:
                    alvos = {t.id for t in stmt.targets if isinstance(t, ast.Name)}
                    if {"keyboard", "Key", "GlobalHotKeys"} <= alvos:
                        achou = True
    assert achou, "imports de pynput devem estar em try/except que zera keyboard/Key/GlobalHotKeys"


def test_shift_keys_tolera_key_none():
    tree = _tree(MAIN)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_SHIFT_KEYS" for t in node.targets
        ):
            assert isinstance(node.value, ast.IfExp), "_SHIFT_KEYS deve ser condicional (Key is not None)"
            return
    raise AssertionError("_SHIFT_KEYS não encontrado")


def _primeiro_lineno(func, pred) -> int | None:
    linhas = [n.lineno for n in ast.walk(func) if pred(n)]
    return min(linhas) if linhas else None


def _guard_lineno(func) -> int | None:
    def eh_guard(n):
        return (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_has_feature"
            and any(isinstance(a, ast.Constant) and a.value == "global_hotkeys" for a in n.args)
        )
    return _primeiro_lineno(func, eh_guard)


def _uso_pynput_lineno(func) -> int | None:
    def eh_uso(n):
        if not isinstance(n, ast.Call):
            return False
        f = n.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                and f.value.id == "keyboard" and f.attr == "Listener":
            return True
        if isinstance(f, ast.Name) and f.id == "GlobalHotKeys":
            return True
        return False
    return _primeiro_lineno(func, eh_uso)


def _uso_backend_lineno(func, metodo) -> int | None:
    """F2-01: keyboard.Listener/GlobalHotKeys vivem no backend pynput; o main.py
    chama hk.listen_keys(...)/hk.bind(...)."""
    return _primeiro_lineno(
        func,
        lambda n: isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == metodo,
    )


def test_keyboard_listener_atras_do_portao():
    func = _func(_tree(MAIN), "_start_keyboard_listener")
    guard = _guard_lineno(func)
    uso = _uso_backend_lineno(func, "listen_keys")
    assert guard is not None, "falta o portão _has_feature('global_hotkeys')"
    assert uso is not None, "esperava hk.listen_keys(...)"
    assert guard < uso, "o portão deve vir antes de hk.listen_keys(...)"


def test_global_hotkeys_atras_do_portao():
    func = _func(_tree(MAIN), "_start_global_hotkeys")
    guard = _guard_lineno(func)
    uso = _uso_backend_lineno(func, "bind")
    assert guard is not None, "falta o portão _has_feature('global_hotkeys')"
    assert uso is not None, "esperava hk.bind(...)"
    assert guard < uso, "o portão deve vir antes de hk.bind(...)"


def test_jarvis_platform_no_spec_e_launcher():
    spec = (REPO_ROOT / "JARVIS.spec").read_text(encoding="utf-8-sig", errors="replace")
    launcher = (REPO_ROOT / "launcher.py").read_text(encoding="utf-8-sig", errors="replace")
    assert "'jarvis.platform'" in spec, "jarvis.platform ausente do hidden do JARVIS.spec"
    assert "import jarvis.platform" in launcher, "jarvis.platform ausente do if False do launcher.py"
