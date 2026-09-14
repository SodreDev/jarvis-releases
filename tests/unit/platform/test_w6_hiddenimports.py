"""W6 (ADR-001 §10): todo módulo de jarvis/platform está no ``hidden`` do
JARVIS.spec e no bloco ``if False:`` do launcher.py. Sem isso, o .exe em modo
standalone não acha os backends carregados por string no REGISTRY.

Só estático (ast): nenhum dos dois arquivos é executado.
"""
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PLATFORM = REPO_ROOT / "jarvis" / "platform"


def _modulos():
    """Nomes pontuados dos módulos (não os __init__) de jarvis/platform."""
    nomes = []
    for py in sorted(PLATFORM.rglob("*.py")):
        if "__pycache__" in py.parts or py.name == "__init__.py":
            continue
        nomes.append(".".join(py.relative_to(REPO_ROOT).with_suffix("").parts))
    return nomes


def _hidden_do_spec():
    tree = ast.parse((REPO_ROOT / "JARVIS.spec").read_text(encoding="utf-8-sig", errors="replace"))
    nomes = set()
    for node in ast.walk(tree):
        alvo = None
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "hidden" for t in node.targets):
                alvo = node.value
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == "hidden":
            alvo = node.value
        if isinstance(alvo, (ast.List, ast.Tuple)):
            nomes.update(e.value for e in alvo.elts if isinstance(e, ast.Constant) and isinstance(e.value, str))
    return nomes


def _imports_do_if_false():
    tree = ast.parse((REPO_ROOT / "launcher.py").read_text(encoding="utf-8-sig", errors="replace"))
    nomes = set()
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Constant) and node.test.value is False:
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Import):
                    nomes.update(a.name for a in stmt.names)
    return nomes


def test_ha_modulos_para_conferir():
    assert "jarvis.platform.registry" in _modulos()


def test_todo_modulo_no_hidden_do_spec():
    hidden = _hidden_do_spec()
    faltando = [m for m in _modulos() if m not in hidden]
    assert not faltando, f"faltam no hidden do JARVIS.spec: {faltando}"


def test_todo_modulo_no_if_false_do_launcher():
    importados = _imports_do_if_false()
    faltando = [m for m in _modulos() if m not in importados]
    assert not faltando, f"faltam no if False do launcher.py: {faltando}"
