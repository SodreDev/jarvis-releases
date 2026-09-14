"""K F2-09 (AST, sem importar main.py): restart via jarvis.platform.

- `_fazer_restart` (dentro de `_reiniciar_jarvis`) chama
  `restart_self(main_path=..., frozen=...)`, na ordem sleep → restart_self →
  destroy → os._exit; o comando PowerShell/CREATE_NEW_CONSOLE saiu do main.py
  (vive literal em jarvis/platform/windows/processes.py);
- gancho de smoke em `_smoke_boot_finish`: `JARVIS_SMOKE_RESTART=1` marca "done"
  ANTES de chamar `_reiniciar_jarvis` (a 2ª instância não relança de novo) e
  retorna em seguida.
"""
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN = REPO_ROOT / "main.py"


def _tree() -> ast.Module:
    return ast.parse(MAIN.read_text(encoding="utf-8-sig", errors="replace"))


def _func(tree, nome):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == nome:
            return node
    raise AssertionError(f"função {nome} não encontrada")


def _linhas_de_chamada(node, attr):
    return sorted(
        n.lineno for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr
    )


def test_fazer_restart_usa_restart_self_na_ordem():
    func = _func(_func(_tree(), "_reiniciar_jarvis"), "_fazer_restart")
    chamadas = [n for n in ast.walk(func)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "restart_self"]
    assert len(chamadas) == 1
    assert {k.arg for k in chamadas[0].keywords} == {"main_path", "frozen"}

    sleep = _linhas_de_chamada(func, "sleep")
    restart = _linhas_de_chamada(func, "restart_self")
    destroy = _linhas_de_chamada(func, "destroy")
    sair = _linhas_de_chamada(func, "_exit")
    assert sleep and destroy and sair
    assert sleep[0] < restart[0] < destroy[0] < sair[0]


def test_reiniciar_sem_powershell_nem_create_new_console():
    # Só o restart (_reiniciar_jarvis) é da F2-09; outros usos de PowerShell no
    # main.py ficam para as tarefas deles.
    func = _func(_tree(), "_reiniciar_jarvis")
    sobras = [
        n.lineno for n in ast.walk(func)
        if (isinstance(n, ast.Attribute) and n.attr in ("CREATE_NEW_CONSOLE", "Popen"))
        or (isinstance(n, ast.Constant) and isinstance(n.value, str)
            and ("Activate.ps1" in n.value or n.value == "powershell"))
    ]
    assert not sobras, f"restart do Windows ainda em _reiniciar_jarvis nas linhas {sobras}"


def test_gancho_de_smoke_relanca_uma_vez():
    func = _func(_tree(), "_smoke_boot_finish")
    alvo = None
    for node in ast.walk(func):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and any(isinstance(c, ast.Constant) and c.value == "1" for c in node.test.comparators)
                and _linhas_de_chamada(node, "_reiniciar_jarvis")):
            alvo = node
            break
    assert alvo is not None, "falta o if JARVIS_SMOKE_RESTART == '1' com _reiniciar_jarvis()"

    marca = [
        n.lineno for n in ast.walk(alvo)
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and n.value.value == "done"
        and any(isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                and t.slice.value == "JARVIS_SMOKE_RESTART" for t in n.targets)
    ]
    assert marca and marca[0] < _linhas_de_chamada(alvo, "_reiniciar_jarvis")[0]
    assert isinstance(alvo.body[-1], ast.Return)
