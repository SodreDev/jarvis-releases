"""Ressalva da revisão (BAIXA): _try_registry_app_paths não pode levantar no
Linux — quem chama espera None para seguir para a próxima estratégia de busca.
"""
import ast
from pathlib import Path

from comandos import janela_ctrl

REPO_ROOT = Path(__file__).resolve().parents[2]
MOD_PATH = REPO_ROOT / "comandos" / "janela_ctrl.py"


def test_registry_app_paths_returns_none_on_linux(fake_platform):
    fake_platform("linux")
    # não levanta e devolve None (sem registro do Windows no Linux)
    assert janela_ctrl._try_registry_app_paths("firefox") is None


def test_import_winreg_stays_inside_win32_branch():
    """AST: `import winreg` continua dentro do ramo `if sys.platform ... win32`
    dentro de _try_registry_app_paths, nunca no nível de módulo."""
    tree = ast.parse(MOD_PATH.read_text(encoding="utf-8-sig", errors="replace"))

    # nenhum import winreg no nível de módulo
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert all(a.name != "winreg" for a in node.names), "winreg importado no topo do módulo"

    # o import winreg vive dentro da função e sob o ramo win32 (após o early-return)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_try_registry_app_paths"
    )
    imports_winreg = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Import) and any(a.name == "winreg" for a in n.names)
    ]
    assert imports_winreg, "import winreg deveria estar dentro de _try_registry_app_paths"
    # há um guard `if sys.platform != "win32": return` antes do import
    first_import_line = min(n.lineno for n in imports_winreg)
    guard_returns = [
        n.lineno for n in ast.walk(fn)
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant) and n.value.value is None
    ]
    assert any(gl < first_import_line for gl in guard_returns), (
        "o early-return (Linux) deve vir antes do import winreg"
    )
