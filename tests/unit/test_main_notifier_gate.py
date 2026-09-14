"""K F2-05 (AST, sem importar main.py): portão do notifier em _exibir_resposta.

- main.py importa `has as _plat_has`, `get as _plat_get` e `Cap` de jarvis.platform;
- em _exibir_resposta há um `if` com `_tray_visible` E `_plat_has(<Cap>.NOTIFIER)`,
  nessa ordem (com a janela visível nada é consultado);
- dentro dele, threading.Thread(..., daemon=True) e um único
  notify("J.A.R.V.I.S.", <texto>[:200]); nenhum notify fora do portão.
No win32 não há notifier no REGISTRY, então `_plat_has` é falso e nada muda.
"""
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN = REPO_ROOT / "main.py"


def _tree() -> ast.Module:
    return ast.parse(MAIN.read_text(encoding="utf-8-sig", errors="replace"))


def _func(tree: ast.Module, nome: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == nome:
            return node
    raise AssertionError(f"função {nome} não encontrada")


def _menciona_tray_visible(node) -> bool:
    return any(
        (isinstance(n, ast.Attribute) and n.attr == "_tray_visible")
        or (isinstance(n, ast.Constant) and n.value == "_tray_visible")
        for n in ast.walk(node)
    )


def _eh_has_notifier(node) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_plat_has"
        and bool(node.args)
        and isinstance(node.args[0], ast.Attribute)
        and node.args[0].attr == "NOTIFIER"
    )


def _portao(func: ast.FunctionDef):
    for node in ast.walk(func):
        if not (isinstance(node, ast.If) and isinstance(node.test, ast.BoolOp)
                and isinstance(node.test.op, ast.And)):
            continue
        valores = node.test.values
        i_tray = next((i for i, v in enumerate(valores) if _menciona_tray_visible(v)), None)
        i_has = next((i for i, v in enumerate(valores) if _eh_has_notifier(v)), None)
        if i_tray is not None and i_has is not None and i_tray < i_has:
            return node
    return None


def _notifies(node):
    return [
        n for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "notify"
    ]


def test_main_importa_has_get_e_cap_da_fachada():
    nomes = {
        (a.name, a.asname)
        for n in _tree().body
        if isinstance(n, ast.ImportFrom) and n.module == "jarvis.platform"
        for a in n.names
    }
    assert ("has", "_plat_has") in nomes
    assert ("get", "_plat_get") in nomes
    assert any(nome == "Cap" for nome, _ in nomes)


def test_portao_tray_visivel_antes_de_has_notifier():
    assert _portao(_func(_tree(), "_exibir_resposta")) is not None, (
        "_exibir_resposta precisa de `if <_tray_visible> and _plat_has(Cap.NOTIFIER):`"
    )


def test_notify_em_thread_daemon_dentro_do_portao():
    portao = _portao(_func(_tree(), "_exibir_resposta"))
    assert portao is not None

    threads = [
        n for n in ast.walk(portao)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "Thread"
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "threading"
    ]
    assert any(
        any(k.arg == "daemon" and isinstance(k.value, ast.Constant) and k.value.value is True
            for k in t.keywords)
        for t in threads
    ), "o notify tem de sair numa threading.Thread(..., daemon=True)"

    notifies = _notifies(portao)
    assert len(notifies) == 1
    primeiro = notifies[0].args[0]
    assert isinstance(primeiro, ast.Constant) and primeiro.value == "J.A.R.V.I.S."
    assert any(
        isinstance(s, ast.Subscript) and isinstance(s.slice, ast.Slice)
        and isinstance(s.slice.upper, ast.Constant) and s.slice.upper.value == 200
        for s in ast.walk(portao)
    ), "o corpo da notificação é o texto cortado em 200 caracteres"


def test_nenhum_notify_fora_do_portao():
    func = _func(_tree(), "_exibir_resposta")
    portao = _portao(func)
    assert portao is not None
    dentro = {id(n) for n in _notifies(portao)}
    fora = [n.lineno for n in _notifies(func) if id(n) not in dentro]
    assert not fora, f"notify fora do portão nas linhas {fora}"
