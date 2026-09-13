"""Garante que o log de crash nativo (faulthandler) não cresce sem limite.

- Rotação na abertura: se o arquivo passar do limite, vira <path>.1 (só 1 cópia
  antiga) e o atual recomeça vazio.
- Sem dump periódico (nenhuma chamada com repeat=True nem dump_traceback_later /
  faulthandler.register), verificado por AST em main.py e core/crash_log.py.
- Dump de crash fatal CONTINUA ligado: faulthandler.enable no arquivo.
"""
import ast
import faulthandler
from pathlib import Path

import pytest

from core.crash_log import DEFAULT_MAX_BYTES, setup_native_crash_log

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(src: Path) -> ast.Module:
    return ast.parse(src.read_text(encoding="utf-8-sig", errors="replace"))


# ── Rotação ──────────────────────────────────────────────────────────────────

def test_rotaciona_quando_passa_do_limite(isolated_home):
    path = isolated_home["data"] / "crash_native.log"
    path.write_text("x" * 500, encoding="utf-8")  # acima do limite abaixo

    fp = setup_native_crash_log(str(path), max_bytes=100)
    try:
        backup = path.with_suffix(".log.1")
        assert backup.exists(), "log antigo deveria ter sido rotacionado para .1"
        assert backup.read_text(encoding="utf-8").startswith("x" * 500)
        # o atual recomeça vazio (só o cabeçalho, sem o conteúdo antigo)
        atual = path.read_text(encoding="utf-8")
        assert "x" * 500 not in atual
        assert path.stat().st_size < 200
    finally:
        fp.close()
        faulthandler.enable()  # volta o dump fatal para o stderr do processo de teste


def test_nao_rotaciona_quando_abaixo_do_limite(isolated_home):
    path = isolated_home["data"] / "crash_native.log"
    path.write_text("pequeno\n", encoding="utf-8")

    fp = setup_native_crash_log(str(path), max_bytes=5_000_000)
    try:
        assert not path.with_suffix(".log.1").exists()
        # append: mantém o conteúdo anterior
        assert "pequeno" in path.read_text(encoding="utf-8")
    finally:
        fp.close()
        faulthandler.enable()


def test_mantem_so_uma_copia_antiga(isolated_home):
    path = isolated_home["data"] / "crash_native.log"
    for marcador in ("primeiro", "segundo"):
        path.write_text(marcador * 100, encoding="utf-8")
        setup_native_crash_log(str(path), max_bytes=50).close()
    faulthandler.enable()
    backup = path.with_suffix(".log.1")
    # só existe .1 (não .2); e ele contém a rotação mais recente
    assert backup.exists()
    assert not path.with_suffix(".log.2").exists()
    assert backup.read_text(encoding="utf-8").startswith("segundo")


def test_limite_padrao_e_5mb():
    assert DEFAULT_MAX_BYTES == 5_000_000


def test_faulthandler_fica_armado(isolated_home):
    path = isolated_home["data"] / "crash_native.log"
    fp = setup_native_crash_log(str(path))
    try:
        assert faulthandler.is_enabled()
    finally:
        fp.close()
        faulthandler.enable()


# ── Sem dump periódico (AST) ───────────────────────────────────────────────────

def _faulthandler_aliases(tree: ast.Module) -> set[str]:
    """Nomes pelos quais o módulo faulthandler é referenciado no arquivo."""
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "faulthandler":
                    aliases.add(a.asname or "faulthandler")
    return aliases


@pytest.mark.parametrize("rel", ["main.py", "core/crash_log.py"])
def test_sem_dump_periodico(rel):
    tree = _read(REPO_ROOT / rel)
    aliases = _faulthandler_aliases(tree)
    proibidos = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Só olhamos chamadas do próprio faulthandler (fh.<algo>()), para não
        # confundir com atexit.register, signal.register, tk after(repeat=...) etc.
        if not (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id in aliases):
            continue
        if func.attr in ("dump_traceback_later", "register"):
            proibidos.append(f"{rel}:{node.lineno}: faulthandler.{func.attr}(...)")
        for kw in node.keywords:
            if kw.arg == "repeat" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                proibidos.append(f"{rel}:{node.lineno}: faulthandler repeat=True")
    assert not proibidos, "dump periódico do faulthandler (loop):\n" + "\n".join(proibidos)


def test_crash_log_arma_enable():
    """core/crash_log.py deve chamar faulthandler.enable (dump de crash fatal)."""
    tree = _read(REPO_ROOT / "core/crash_log.py")
    tem_enable = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "enable"
        for n in ast.walk(tree)
    )
    assert tem_enable, "faulthandler.enable deveria continuar ligado em core/crash_log.py"
