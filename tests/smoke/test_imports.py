"""Smoke test: importa cada módulo de core/, comandos/ e jarvis/ isolado num
subprocesso (com timeout), sem tocar em main.py (tem efeitos colaterais no
import: abre janela, áudio, hotkeys globais).

Os xfail abaixo são a BASELINE do estado atual do port Linux (2026-09-13):
módulos que hoje só funcionam no Windows por dependerem de winreg/ctypes.windll
ou de outra API exclusiva do SO. Conforme o port avança, cada um deve ser
promovido de volta a um import normal (removendo o xfail), nunca o contrário.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ["core", "comandos", "jarvis"]
IMPORT_TIMEOUT = 30

# module -> motivo da falha no Linux (baseline apurada rodando este probe no host)
KNOWN_WINDOWS_ONLY = {}


def discover_modules():
    modules = []
    for pkg in PACKAGES:
        for f in sorted((REPO_ROOT / pkg).rglob("*.py")):
            rel = f.relative_to(REPO_ROOT)
            if "__pycache__" in rel.parts:
                continue
            parts = list(rel.with_suffix("").parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            mod = ".".join(parts)
            if mod:
                modules.append(mod)
    return modules


def _make_param(mod):
    if mod in KNOWN_WINDOWS_ONLY:
        return pytest.param(
            mod,
            marks=[
                pytest.mark.xfail(reason=KNOWN_WINDOWS_ONLY[mod], strict=False),
                pytest.mark.windows_only,
            ],
        )
    return pytest.param(mod)


MODULES = discover_modules()
PARAMS = [_make_param(m) for m in MODULES]


@pytest.mark.slow
@pytest.mark.parametrize("module_name", PARAMS, ids=MODULES)
def test_module_imports(module_name):
    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=IMPORT_TIMEOUT,
    )
    assert result.returncode == 0, (
        f"falha ao importar {module_name}:\n{result.stderr[-4000:]}"
    )


def test_discovered_at_least_one_module_per_package():
    for pkg in PACKAGES:
        assert any(m == pkg or m.startswith(pkg + ".") for m in MODULES), (
            f"nenhum módulo descoberto em {pkg}/"
        )
