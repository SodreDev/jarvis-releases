"""Garante que constantes de subprocess exclusivas do Windows não sejam
acessadas diretamente (quebrariam com AttributeError no Linux).

O padrão seguro é ``getattr(subprocess, "CREATE_NO_WINDOW", 0)`` ou o acesso
protegido por ``if sys.platform == "win32"`` / ``if os.name == "nt"``.

Só usa a stdlib (ast + pathlib): varre os .py do repositório e falha
listando arquivo:linha de cada acesso direto desprotegido.
"""
import ast
from pathlib import Path

WINDOWS_ONLY = {
    "CREATE_NO_WINDOW",
    "DETACHED_PROCESS",
    "CREATE_NEW_PROCESS_GROUP",
    "STARTUPINFO",
    "STARTF_USESHOWWINDOW",
}

REPO_ROOT = Path(__file__).resolve().parents[2]
IGNORE_DIR_PREFIXES = (".venv", "venv")
IGNORE_DIR_NAMES = {"build", "dist", "tests", "__pycache__"}


def _is_win_guard(test: ast.expr) -> bool:
    """True se o teste do ``if`` for sys.platform == "win32" ou os.name == "nt"."""
    if isinstance(test, ast.Compare) and isinstance(test.left, ast.Attribute):
        attr = test.left
        target = None
        if isinstance(attr.value, ast.Name):
            target = f"{attr.value.id}.{attr.attr}"
        if target in ("sys.platform", "os.name"):
            for op, comp in zip(test.ops, test.comparators):
                if isinstance(op, (ast.Eq,)) and isinstance(comp, ast.Constant):
                    if comp.value in ("win32", "nt"):
                        return True
    return False


def _collect_unprotected(path: Path):
    """Retorna [(linha, nome)] de cada acesso direto desprotegido no arquivo."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    hits = []

    def visit(node, guarded: bool):
        if isinstance(node, ast.Attribute) and node.attr in WINDOWS_ONLY and not guarded:
            hits.append((node.lineno, node.attr))
        if isinstance(node, ast.If):
            body_guarded = guarded or _is_win_guard(node.test)
            for child in node.body:
                visit(child, body_guarded)
            for child in node.orelse:
                visit(child, guarded)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, guarded)

    visit(tree, False)
    return hits


def _iter_py_files():
    for path in REPO_ROOT.rglob("*.py"):
        rel_parts = path.relative_to(REPO_ROOT).parts
        skip = False
        for part in rel_parts[:-1]:
            if (
                part in IGNORE_DIR_NAMES
                or part.startswith(IGNORE_DIR_PREFIXES)
                or part.startswith(".")  # .git, .claude/worktrees, .venv etc.
            ):
                skip = True
                break
        if not skip:
            yield path


def test_no_unprotected_windows_subprocess_flags():
    offenders = []
    for path in _iter_py_files():
        for lineno, name in _collect_unprotected(path):
            rel = path.relative_to(REPO_ROOT)
            offenders.append(f"{rel}:{lineno}: subprocess.{name}")
    assert not offenders, (
        "Acesso direto a constante de subprocess exclusiva do Windows "
        "(quebra no Linux); use getattr(..., 0) ou guarde com "
        "if sys.platform == 'win32':\n" + "\n".join(sorted(offenders))
    )


if __name__ == "__main__":
    test_no_unprotected_windows_subprocess_flags()
    print("OK")
