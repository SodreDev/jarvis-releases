"""F1-09 (AST, sem importar main.py): call sites do boot atrás dos portões certos.

- _criar_tray_icon() sob if _has_feature("tray")
- _iniciar_verificador_updates() sob if _has_feature("self_update_payload")
- _iniciar_monitor_notif (thread) sob if _has_feature("notification_reader")
- _chc.start_monitor() sob if _has_feature("clipboard_monitor")
- apply_update_now e os 3 métodos de gestos começam pelo portão (not _has_feature(...))
"""
import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN = REPO_ROOT / "main.py"


def _tree() -> ast.Module:
    return ast.parse(MAIN.read_text(encoding="utf-8-sig", errors="replace"))


def _func(tree, nome):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == nome:
            return node
    raise AssertionError(f"função {nome} não encontrada")


def _feat_call_name(node):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id == "_has_feature" and node.args \
            and isinstance(node.args[0], ast.Constant):
        return node.args[0].value
    return None


def _gate_of_if(if_node):
    """(feature, negado) do teste do if, ou (None, None)."""
    t = if_node.test
    if isinstance(t, ast.UnaryOp) and isinstance(t.op, ast.Not):
        name = _feat_call_name(t.operand)
        return (name, True) if name else (None, None)
    name = _feat_call_name(t)
    return (name, False) if name else (None, None)


def _attr_pred(attr):
    return lambda n: isinstance(n, ast.Attribute) and n.attr == attr


def _test_tem_feature_positiva(if_test, feature) -> bool:
    """True se o teste do if chama _has_feature(feature) de forma positiva
    (inclusive dentro de um `and`), sem estar sob um `not`."""
    for node in ast.walk(if_test):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            if _feat_call_name(node.operand) == feature:
                return False  # está negado
        if _feat_call_name(node) == feature:
            # confirma que não é o operando de um Not (já tratado acima)
            return True
    return False


def _positivo_contendo(tree, feature, pred):
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _test_tem_feature_positiva(node.test, feature):
            for stmt in node.body:
                if any(pred(n) for n in ast.walk(stmt)):
                    return True
    return False


@pytest.mark.parametrize("feature,attr", [
    ("tray", "_criar_tray_icon"),
    ("self_update_payload", "_iniciar_verificador_updates"),
    ("notification_reader", "_iniciar_monitor_notif"),
    ("clipboard_monitor", "start_monitor"),
])
def test_call_site_sob_portao_positivo(feature, attr):
    assert _positivo_contendo(_tree(), feature, _attr_pred(attr)), (
        f"{attr} deve estar sob if _has_feature('{feature}')"
    )


@pytest.mark.parametrize("metodo,feature", [
    ("apply_update_now", "self_update_payload"),
    ("_ativar_gesture", "gestures"),
    ("_ativar_eye_control", "gestures"),
    ("_calibrar_olhos", "gestures"),
])
def test_metodo_comeca_pelo_portao(metodo, feature):
    func = _func(_tree(), metodo)
    corpo = func.body
    # pula a docstring inicial, se houver
    if corpo and isinstance(corpo[0], ast.Expr) and isinstance(corpo[0].value, ast.Constant) \
            and isinstance(corpo[0].value.value, str):
        corpo = corpo[1:]
    assert corpo, f"{metodo} vazio"
    first = corpo[0]
    assert isinstance(first, ast.If), f"{metodo} não começa por um if de portão"
    name, neg = _gate_of_if(first)
    assert name == feature and neg, f"{metodo} deve começar por 'if not _has_feature(\"{feature}\")'"
    assert any(isinstance(n, ast.Return) for n in ast.walk(first)), (
        f"o portão de {metodo} deve retornar cedo"
    )
