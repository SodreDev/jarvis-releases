"""C1 (F2-06): `os.startfile` e "notepad.exe" só no adapter windows.

Fora de jarvis/platform/windows/ não pode sobrar chamada `<algo>.startfile` nem
a string "notepad.exe". Exceções declaradas (a allowlist só pode diminuir, e
uma entrada que deixou de ser usada tem de sair daqui):
- comandos/executor.py: "notepad.exe" no mapa de nomes de apps (Fase 4);
- jarvis/messaging/pyautogui_sender.py: `os.startfile`, fora da lista fechada
  da F2-06 (precisa de emenda do arquiteto).

Só AST: nenhum módulo é importado.
"""
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
IGNORAR_PASTAS = {"tests", "build", "dist", "__pycache__", "node_modules"}
ADAPTER = ("jarvis", "platform", "windows")

ALLOWLIST = {
    "comandos/executor.py": {"notepad.exe"},
    "jarvis/messaging/pyautogui_sender.py": {"startfile"},
}


def _arquivos():
    for path in REPO_ROOT.rglob("*.py"):
        partes = path.relative_to(REPO_ROOT).parts
        pastas = partes[:-1]
        if any(p in IGNORAR_PASTAS or p.startswith((".", "venv")) for p in pastas):
            continue
        if pastas[:3] == ADAPTER:
            continue
        yield path


def _usos(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8-sig", errors="replace"))
    achados = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and n.attr == "startfile":
            achados.add("startfile")
        elif isinstance(n, ast.Constant) and n.value == "notepad.exe":
            achados.add("notepad.exe")
    return achados


def test_startfile_e_notepad_so_no_adapter():
    proibidos = []
    for path in _arquivos():
        rel = path.relative_to(REPO_ROOT).as_posix()
        sobra = _usos(path) - ALLOWLIST.get(rel, set())
        if sobra:
            proibidos.append(f"{rel}: {sorted(sobra)}")
    assert not proibidos, "os.startfile/notepad.exe fora do adapter windows:\n" + "\n".join(sorted(proibidos))


def test_allowlist_so_tem_o_que_ainda_existe():
    obsoletos = []
    for rel, esperados in ALLOWLIST.items():
        path = REPO_ROOT / rel
        usados = _usos(path) if path.exists() else set()
        if esperados - usados:
            obsoletos.append(f"{rel}: {sorted(esperados - usados)}")
    assert not obsoletos, "entradas da allowlist C1 que já não são usadas (remova):\n" + "\n".join(obsoletos)
