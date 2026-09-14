"""K — contrato (F2-10c): o smoke encerra pelo caminho normal, sem `os._exit`.
Só leitura de texto/AST de `main.py` (nunca importa `main.py`), mais o
`shutdown_children` dos dois backends de processos.

- fim do `__main__`: no bloco `if _smoke_seconds()` depois do `webview.start`,
  `shutdown_children(2.0)` e `sys.exit(0)`; `os._exit` só dentro da rede de
  segurança `_forcar` (Timer daemon de 10 s que imprime `JARVIS_SMOKE_FORCED_EXIT`);
- `_smoke_boot_finish` agenda, num Timer daemon, o MESMO caminho do "Encerrar"
  da bandeja (`_encerrar_de_tray`) com `sair_do_processo=False`;
- `_encerrar_de_tray` para o tray, tira a interceptação do X (`events.closing -=`)
  antes do `window.destroy()` (o pywebview despacha o close para a thread da GUI)
  e só chama `os._exit` com `sair_do_processo`;
- `JARVIS_SMOKE_AUDIO` enfileira WAV + flush na `_audio_queue`;
- Timers do `_RootProxy.after` são daemon com nome `RootAfter`.
"""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_PY = REPO_ROOT / "main.py"


def _parse_main():
    source = MAIN_PY.read_text(encoding="utf-8")
    return source, ast.parse(source, filename=str(MAIN_PY))


def _find_function(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _find_class(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_os_exit(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "_exit"
        and isinstance(func.value, ast.Name)
        and func.value.id in {"os", "_os"}
    )


def _calls_smoke_helper(test: ast.AST) -> bool:
    return any(isinstance(n, ast.Call) and _call_name(n) == "_smoke_seconds" for n in ast.walk(test))


def _walk_skipping_defs(nodes):
    """Percorre os nós sem entrar em funções aninhadas (caminho normal)."""
    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
    pilha = [n for n in nodes if not isinstance(n, defs)]
    while pilha:
        node = pilha.pop()
        yield node
        for filho in ast.iter_child_nodes(node):
            if isinstance(filho, defs):
                continue
            pilha.append(filho)


def _main_guard(tree: ast.Module) -> ast.If:
    for node in tree.body:
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
        ):
            return node
    raise AssertionError("bloco `if __name__ == \"__main__\"` não encontrado")


def _smoke_exit_block(tree: ast.Module) -> ast.If:
    """O `if _smoke_seconds()` do `__main__` que imprime JARVIS_SMOKE_EXIT."""
    guard = _main_guard(tree)
    for node in ast.walk(guard):
        if not (isinstance(node, ast.If) and _calls_smoke_helper(node.test)):
            continue
        textos = [
            n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]
        if any("JARVIS_SMOKE_EXIT children_alive=" in t for t in textos):
            return node
    raise AssertionError("bloco de smoke com JARVIS_SMOKE_EXIT não encontrado no __main__")


def test_smoke_exit_block_has_no_os_exit_on_normal_path():
    _source, tree = _parse_main()
    bloco = _smoke_exit_block(tree)
    diretos = [n for n in _walk_skipping_defs(bloco.body) if isinstance(n, ast.Call) and _is_os_exit(n)]
    assert not diretos, f"os._exit no caminho normal do smoke (linhas {[n.lineno for n in diretos]})"


def test_smoke_exit_block_shuts_children_down_and_exits_normally():
    _source, tree = _parse_main()
    bloco = _smoke_exit_block(tree)
    chamadas = [n for n in _walk_skipping_defs(bloco.body) if isinstance(n, ast.Call)]

    shutdown = [c for c in chamadas if _call_name(c) == "shutdown_children"]
    assert shutdown, "o smoke deve chamar shutdown_children antes de sair"
    assert any(
        c.args and isinstance(c.args[0], ast.Constant) and c.args[0].value == 2.0 for c in shutdown
    ), "shutdown_children(2.0)"

    # a última instrução do bloco é o sys.exit(0) (o atexit roda)
    ultimo = bloco.body[-1]
    assert isinstance(ultimo, ast.Expr) and isinstance(ultimo.value, ast.Call)
    assert isinstance(ultimo.value.func, ast.Attribute) and ultimo.value.func.attr == "exit"
    assert ultimo.value.args and isinstance(ultimo.value.args[0], ast.Constant)
    assert ultimo.value.args[0].value == 0


def test_forced_exit_safety_net_is_daemon_timer_of_10s():
    source, tree = _parse_main()
    bloco = _smoke_exit_block(tree)
    forcar = next(
        (n for n in bloco.body if isinstance(n, ast.FunctionDef) and n.name == "_forcar"), None
    )
    assert forcar is not None, "rede de segurança `_forcar` não encontrada no bloco de smoke"
    assert any(isinstance(n, ast.Call) and _is_os_exit(n) for n in ast.walk(forcar))
    textos = [n.value for n in ast.walk(forcar) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert any("JARVIS_SMOKE_FORCED_EXIT threads=" in t for t in textos)

    timers = [
        n for n in _walk_skipping_defs(bloco.body)
        if isinstance(n, ast.Call) and _call_name(n) == "Timer"
        and len(n.args) == 2 and isinstance(n.args[1], ast.Name) and n.args[1].id == "_forcar"
    ]
    assert timers and isinstance(timers[0].args[0], ast.Constant) and timers[0].args[0].value == 10

    trecho = ast.get_source_segment(source, bloco)
    assert ".daemon = True" in trecho, "o Timer de _forcar precisa ser daemon"


def test_smoke_boot_finish_closes_through_tray_quit_path():
    source, tree = _parse_main()
    fn = _find_function(tree, "_smoke_boot_finish")
    assert fn is not None
    assert not any(isinstance(n, ast.Call) and _is_os_exit(n) for n in ast.walk(fn))
    timers = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and _call_name(n) == "Timer"]
    fechamento = [
        t for t in timers
        if len(t.args) == 2 and isinstance(t.args[1], ast.Attribute) and t.args[1].attr == "_encerrar_de_tray"
    ]
    assert fechamento, "o smoke deve fechar pelo mesmo caminho do Encerrar da bandeja"
    kwargs = {k.arg: k.value for k in fechamento[0].keywords}
    assert "kwargs" in kwargs, "o Timer precisa passar sair_do_processo=False"
    assert "'sair_do_processo': False" in ast.unparse(kwargs["kwargs"])
    assert ".daemon = True" in ast.get_source_segment(source, fn)


def test_tray_quit_unhooks_close_interception_before_destroy():
    _source, tree = _parse_main()
    fn = _find_function(tree, "_encerrar_de_tray")
    assert fn is not None
    assert "sair_do_processo" in [a.arg for a in fn.args.kwonlyargs]

    removes = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.AugAssign) and isinstance(n.op, ast.Sub)
        and isinstance(n.target, ast.Attribute) and n.target.attr == "closing"
    ]
    destroys = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and _call_name(n) == "destroy"]
    assert removes, "a interceptação do X (events.closing) deve sair antes do destroy"
    assert destroys and removes[0].lineno < destroys[0].lineno

    # os._exit só sob `if sair_do_processo`
    for node in ast.walk(fn):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "sair_do_processo":
            assert any(isinstance(n, ast.Call) and _is_os_exit(n) for n in ast.walk(node))
            break
    else:
        raise AssertionError("os._exit do Encerrar deve ficar sob `if sair_do_processo`")
    fora = [n for n in _walk_skipping_defs(fn.body) if isinstance(n, ast.If)]
    exits = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and _is_os_exit(n)]
    assert len(exits) == 1 and any(
        isinstance(i.test, ast.Name) and i.test.id == "sair_do_processo" and exits[0] in list(ast.walk(i))
        for i in fora
    )


def test_smoke_audio_enqueues_wav_and_flush():
    source, tree = _parse_main()
    fn = _find_function(tree, "_smoke_audio")
    assert fn is not None, "_smoke_audio não encontrado"
    trecho = ast.get_source_segment(source, fn)
    assert "self._audio_queue.put((buf.getvalue(), \"wav\"))" in trecho
    assert "self._audio_queue.put((b\"\", \"wav\"))" in trecho
    assert "alive_children()" in trecho

    finish = _find_function(tree, "_smoke_boot_finish")
    assert "JARVIS_SMOKE_AUDIO" in ast.get_source_segment(source, finish)


def test_root_proxy_after_timers_are_daemon_and_named():
    source, tree = _parse_main()
    cls = _find_class(tree, "_RootProxy")
    assert cls is not None
    after = next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "after"), None)
    assert after is not None
    trecho = ast.get_source_segment(source, after)
    assert ".daemon = True" in trecho
    assert '"RootAfter"' in trecho


def test_windows_shutdown_children_is_noop():
    from jarvis.platform.windows.processes import WindowsProcesses

    assert WindowsProcesses().shutdown_children(2.0) is None


@pytest.mark.linux_only
def test_posix_shutdown_children_kills_registered_child():
    from jarvis.platform.linux.processes import PosixProcesses

    procs = PosixProcesses()
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        procs.register_child(proc)
        assert procs.alive_children() == [proc.pid]
        procs.shutdown_children(2.0)
        assert proc.poll() is not None
        assert procs.alive_children() == []
    finally:
        if proc.poll() is None:
            proc.kill()  # só o PID que este teste criou
            proc.wait(timeout=5)
