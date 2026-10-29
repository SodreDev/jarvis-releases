"""O tier de uma ferramenta não muda com o modelo (ADR-0056, regra de segurança 2): o pacote dos
provedores não conversa com a política nem com o executor — quem decide é o PDP, igual para
todo modelo."""

from __future__ import annotations

import ast
from pathlib import Path

PACOTE = Path(__file__).resolve().parents[3] / "src" / "jarvis" / "provedores"
PROIBIDOS = ("jarvis.politica", "jarvis.policy", "jarvis.executor", "jarvis.capacidades")


def importados(arquivo: Path) -> set[str]:
    nomes: set[str] = set()
    for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            nomes.update(alias.name for alias in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.add(no.module)
    return nomes


def test_provedores_nao_importam_politica_nem_executor() -> None:
    arquivos = sorted(PACOTE.glob("*.py"))
    assert arquivos
    for arquivo in arquivos:
        ruins = {n for n in importados(arquivo) if n.startswith(PROIBIDOS)}
        assert not ruins, f"{arquivo.name} importa {sorted(ruins)}"
