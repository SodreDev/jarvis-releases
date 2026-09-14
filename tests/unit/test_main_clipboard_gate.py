"""K F2-04b (AST, sem importar main.py): aviso único sem monitor de clipboard.

O portão `if _has_feature("clipboard_monitor"):` do boot ganha um `else` que só
imprime o motivo: nada de start_monitor, thread ou loop ali. No win32 a feature
é sempre verdadeira, então o else nunca roda.
"""
import ast
from pathlib import Path

MAIN = Path(__file__).resolve().parents[2] / "main.py"


def _portao():
    tree = ast.parse(MAIN.read_text(encoding="utf-8-sig", errors="replace"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Call)
                and isinstance(node.test.func, ast.Name) and node.test.func.id == "_has_feature"
                and node.test.args and isinstance(node.test.args[0], ast.Constant)
                and node.test.args[0].value == "clipboard_monitor"):
            return node
    raise AssertionError('portão if _has_feature("clipboard_monitor") não encontrado')


def _chamadas(nodes, attr_ou_nome):
    achadas = []
    for raiz in nodes:
        for n in ast.walk(raiz):
            if isinstance(n, ast.Call):
                f = n.func
                nome = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
                if nome == attr_ou_nome:
                    achadas.append(n)
    return achadas


def test_portao_tem_else_que_avisa():
    portao = _portao()
    assert portao.orelse, "falta o else do portão clipboard_monitor"
    assert _chamadas(portao.orelse, "print"), "o else tem de imprimir o aviso"


def test_else_nao_inicia_monitor_nem_thread_nem_loop():
    orelse = _portao().orelse
    assert not _chamadas(orelse, "start_monitor")
    assert not _chamadas(orelse, "Thread")
    assert not any(isinstance(n, (ast.While, ast.For)) for raiz in orelse for n in ast.walk(raiz))


def test_monitor_continua_no_ramo_da_feature():
    assert _chamadas(_portao().body, "start_monitor")
