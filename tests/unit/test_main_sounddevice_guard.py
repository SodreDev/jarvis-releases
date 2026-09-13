"""F1-05 (AST, sem importar main.py): sounddevice protegido quando falta PortAudio.

- o import de sounddevice fica em Try cujo except captura OSError e zera sd;
- todo método que usa `sd.<algo>` tem a guarda `sd is None` antes do primeiro uso.
"""
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN = REPO_ROOT / "main.py"


def _tree() -> ast.Module:
    return ast.parse(MAIN.read_text(encoding="utf-8-sig", errors="replace"))


def test_import_sounddevice_try_except_oserror():
    tree = _tree()
    ok = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        importa_sd = any(
            isinstance(s, ast.Import) and any(a.name == "sounddevice" for a in s.names)
            for s in node.body
        )
        if not importa_sd:
            continue
        for h in node.handlers:
            # except OSError (ou tupla contendo OSError)
            nomes = []
            if isinstance(h.type, ast.Name):
                nomes = [h.type.id]
            elif isinstance(h.type, ast.Tuple):
                nomes = [e.id for e in h.type.elts if isinstance(e, ast.Name)]
            if "OSError" not in nomes:
                continue
            zera = any(
                isinstance(s, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "sd" for t in s.targets)
                and isinstance(s.value, ast.Constant) and s.value.value is None
                for s in h.body
            )
            if zera:
                ok = True
    assert ok, "import de sounddevice deve estar em try/except OSError que zera sd"


def _usa_sd(node) -> int | None:
    """Menor lineno de um acesso sd.<algo> dentro de node."""
    linhas = [
        n.lineno
        for n in ast.walk(node)
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "sd"
    ]
    return min(linhas) if linhas else None


def _guarda_sd_none(node) -> int | None:
    """Menor lineno de uma comparação `sd is None` dentro de node."""
    linhas = []
    for n in ast.walk(node):
        if isinstance(n, ast.Compare) and isinstance(n.left, ast.Name) and n.left.id == "sd" \
                and len(n.ops) == 1 and isinstance(n.ops[0], ast.Is) \
                and isinstance(n.comparators[0], ast.Constant) and n.comparators[0].value is None:
            linhas.append(n.lineno)
    return min(linhas) if linhas else None


def test_todo_metodo_com_sd_tem_guarda_antes():
    tree = _tree()
    faltando = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        uso = _usa_sd(node)
        if uso is None:
            continue
        guarda = _guarda_sd_none(node)
        if guarda is None or guarda >= uso:
            faltando.append(f"{node.name} (uso sd. na linha {uso}, guarda={guarda})")
    assert not faltando, "métodos sem guarda `sd is None` antes do 1º uso:\n" + "\n".join(faltando)
