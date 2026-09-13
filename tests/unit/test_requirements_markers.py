"""K — contrato (F1-03): `requirements.txt` ganha marcadores `sys_platform`
e pins de versão para o pywebview Qt/PySide6. `xfail(strict=True)` — o
executor remove o `xfail` no commit que edita `requirements.txt` (só esse
arquivo, ver SPEC F1-03 / FILA linha 33).

Oráculo: `tests/golden/requirements_1c32e38.txt` (`git show
1c32e38:requirements.txt`), sem nenhum marcador — toda linha vale para
qualquer `sys_platform`.
"""
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = REPO_ROOT / "tests" / "golden" / "requirements_1c32e38.txt"
CURRENT = REPO_ROOT / "requirements.txt"

REMOVED_ON_LINUX = {"pywin32", "pycaw", "uiautomation", "pygetwindow", "pystray"}
ADDED_ON_LINUX = {"pyside6", "qtpy"}


def _parse(path: Path) -> list[Requirement]:
    reqs = []
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        reqs.append(Requirement(line))
    return reqs


def _names_for_platform(reqs: list[Requirement], sys_platform: str) -> set[str]:
    env = {"sys_platform": sys_platform}
    names = set()
    for r in reqs:
        if r.marker is None or r.marker.evaluate(env):
            names.add(canonicalize_name(r.name))
    return names


def test_all_lines_parse_with_packaging():
    # golden também precisa parsear — se um dia ele parar de parsear, o
    # oráculo em si está quebrado, não só o requirements.txt atual.
    _parse(GOLDEN)
    _parse(CURRENT)


def test_win32_set_matches_golden():
    # Guarda tipo C, não K: hoje passa trivialmente (requirements.txt ainda
    # não tem marcadores, então toda linha vale para win32 e para linux) e
    # precisa CONTINUAR passando depois de F1-03 — o conjunto win32 não
    # muda, só o linux ganha/perde pacotes (ver acceptance da SPEC F1-03).
    golden_names = _names_for_platform(_parse(GOLDEN), "win32")
    current_names = _names_for_platform(_parse(CURRENT), "win32")
    assert current_names == golden_names


def test_linux_set_is_golden_minus_windows_only_plus_qt():
    golden_names = _names_for_platform(_parse(GOLDEN), "win32")
    expected = (golden_names - REMOVED_ON_LINUX) | ADDED_ON_LINUX
    current_names = _names_for_platform(_parse(CURRENT), "linux")
    assert current_names == expected


def test_pywebview_and_pyside6_pinned():
    reqs = {canonicalize_name(r.name): r for r in _parse(CURRENT)}
    assert str(reqs["pywebview"].specifier) == "==6.1"
    assert str(reqs["pyside6"].specifier) == "==6.9.3"
