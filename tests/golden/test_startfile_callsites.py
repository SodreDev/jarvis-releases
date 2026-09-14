"""C AST (F2-06): cada call site da lista fechada de `os.startfile`
continua passando A MESMA expressão de argumento de `31bc0ce`, seja
chamando `os.startfile`/`_os.startfile` (hoje, antes de F2-06) ou
`_open_path` (depois — mesmo nome de variável/literal, função nova).
Precisa passar HOJE e continuar passando depois de F2-06.

ÂNCORA POR NOME DE FUNÇÃO (não por número de linha): edições acima do
call site no arquivo (ex.: um import novo no topo) deslocam a linha
sem mudar o comportamento — visto na F2-05 (091fa27, ver FILA). O nome
da função que envolve cada call site é estável e único em cada
arquivo, então localizamos o `ast.Call` por
"está dentro da FunctionDef com este nome" em vez de "está nesta
linha".

Só leitura de texto/AST — nunca importa `main.py` nem os módulos de
`comandos/` (import teria efeito colateral / dependências pesadas).
"""
import ast
from pathlib import Path

import pytest

from tests.golden.legacy_31bc0ce import (
    NOTEPAD_CALL_SITE_ARGS,
    NOTEPAD_CALL_SITE_FUNC,
    OPEN_PATH_CALL_SITES,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _build_enclosing_func_map(tree: ast.Module) -> dict[int, str]:
    """Mapa `id(node) -> nome qualificado` (com pontos p/ funções
    aninhadas, ex.: "_t_gerar_imagem._gen") da FunctionDef/
    AsyncFunctionDef mais interna que contém cada nó. Um único
    percurso da árvore (evita re-caminhar a árvore por nó, que é
    O(n²)/O(n³) em arquivos grandes como tool_registry.py)."""
    mapping: dict[int, str] = {}

    def walk(node: ast.AST, parents: list[str]) -> None:
        qualname = ".".join(parents)
        if qualname:
            mapping[id(node)] = qualname
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, parents + [child.name])
            else:
                walk(child, parents)

    walk(tree, [])
    return mapping


def _calls_in_function(
    tree: ast.Module, func_map: dict[int, str], func_qualname: str
) -> list[ast.Call]:
    """Todo `ast.Call` cuja FunctionDef mais interna tem esse nome
    qualificado."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and func_map.get(id(node)) == func_qualname
    ]


def _is_open_path_like(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "startfile":
        return True
    if isinstance(func, ast.Name) and func.id == "_open_path":
        return True
    return False


@pytest.mark.parametrize(
    "file_rel,func_qualname,expected_arg_src",
    OPEN_PATH_CALL_SITES,
    ids=[f"{f}:{fn}" for f, fn, _ in OPEN_PATH_CALL_SITES],
)
def test_call_site_matches_golden_argument(file_rel, func_qualname, expected_arg_src):
    path = REPO_ROOT / file_rel
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    func_map = _build_enclosing_func_map(tree)

    candidates = [
        c for c in _calls_in_function(tree, func_map, func_qualname) if _is_open_path_like(c)
    ]
    assert candidates, (
        f"nenhuma chamada startfile/_open_path dentro de {func_qualname!r} em {file_rel}"
    )
    assert len(candidates) == 1, (
        f"{func_qualname!r} em {file_rel} tem mais de uma chamada startfile/_open_path "
        f"candidata ({len(candidates)}) — âncora ambígua"
    )
    call = candidates[0]
    assert len(call.args) == 1, f"{file_rel}:{func_qualname} esperava 1 argumento posicional"

    actual_arg_src = ast.get_source_segment(source, call.args[0])
    assert actual_arg_src == expected_arg_src


def test_notepad_call_site_matches_golden():
    path = REPO_ROOT / "main.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    func_map = _build_enclosing_func_map(tree)

    candidates = []
    for node in _calls_in_function(tree, func_map, NOTEPAD_CALL_SITE_FUNC):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "Popen":
            candidates.append(node)

    assert candidates, f"nenhuma chamada Popen dentro de {NOTEPAD_CALL_SITE_FUNC!r} em main.py"
    assert len(candidates) == 1, (
        f"{NOTEPAD_CALL_SITE_FUNC!r} tem mais de uma chamada Popen candidata "
        f"({len(candidates)}) — âncora ambígua"
    )
    call = candidates[0]

    list_arg = call.args[0]
    assert isinstance(list_arg, ast.List)
    items_src = [ast.get_source_segment(source, e) for e in list_arg.elts]
    assert items_src == NOTEPAD_CALL_SITE_ARGS

    close_fds = next((kw for kw in call.keywords if kw.arg == "close_fds"), None)
    assert close_fds is not None
    assert ast.get_source_segment(source, close_fds.value) == "True"
