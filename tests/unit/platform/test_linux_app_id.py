"""K F2-00: APP_ID provisório (D-F2-2) em um único lugar.

O valor é um nome D-Bus válido (o portal casa com o .desktop) e o literal só
aparece em jarvis/platform/linux/app_id.py no código de produção.
"""
import os
import re
from pathlib import Path

from jarvis.platform.linux.app_id import APP_ID, APP_NAME

REPO_ROOT = Path(__file__).resolve().parents[3]
DONO = REPO_ROOT / "jarvis" / "platform" / "linux" / "app_id.py"
PULAR = {"tests", "docs", "build", "dist", "__pycache__", ".git", "node_modules"}

_NOME_DBUS = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_-]*)+$")


def test_valores_recomendados():
    assert APP_ID == "io.github.ninjazins2.Jarvis"
    assert APP_NAME == "J.A.R.V.I.S."


def test_app_id_e_nome_dbus_valido():
    assert len(APP_ID) <= 255
    assert _NOME_DBUS.match(APP_ID)


def test_literal_so_em_app_id_py():
    achados = []
    for raiz, dirs, arquivos in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in PULAR and not d.startswith(".venv") and not d.startswith("venv")]
        for nome in arquivos:
            if not nome.endswith((".py", ".spec", ".desktop")):
                continue
            caminho = Path(raiz) / nome
            if caminho == DONO:
                continue
            if APP_ID in caminho.read_text(encoding="utf-8", errors="replace"):
                achados.append(str(caminho.relative_to(REPO_ROOT)))
    assert not achados, f"APP_ID fora de app_id.py: {achados}"
