"""Aceite F0-03 (d): o `executor` não tem caminho de código para shell.

A varredura é de árvore sintática, não de texto: pega `import subprocess`, `os.system`,
`eval`, `exec` e companhia mesmo escritos com apelido (`import subprocess as sp`). O linter já
barra `shell=True` em todo o repositório (regras `S`); este teste é mais estreito e mais duro,
e vale para os módulos onde um shell seria pior: o executor e a política.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]

MODULOS_PROIBIDOS = frozenset(
    {"subprocess", "os.system", "os.popen", "os.spawnl", "pty", "shlex", "commands", "popen2"}
)
CHAMADAS_PROIBIDAS = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "system",
        "popen",
        "__import__",
        # Criar processo por fora do `subprocess` também é caminho para executar algo: a
        # varredura cobre a família inteira, e não só o nome que o F0-03 listou.
        "fork",
        "forkpty",
        "posix_spawn",
        "posix_spawnp",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "startfile",
    }
)

PACOTES_SEM_SHELL = ("executor", "policy")

EXCECOES: dict[str, frozenset[str]] = {
    "executor/lancador.py": frozenset({"chamada posix_spawn()"}),
    "executor/sites.py": frozenset({"chamada startfile()"}),
}
"""As duas únicas aberturas, nomeadas (ADR-0028): abrir um app **do registro autorizado pelo
dono**, com `argv` do `.desktop` e sem shell; e abrir uma URL validada com o "abrir com o padrão"
do Windows. Qualquer outro arquivo do executor que crie processo cai neste teste."""


def arquivos(pacote: str) -> list[Path]:
    return sorted((RAIZ / "src" / "jarvis" / pacote).rglob("*.py"))


def achados(arquivo: Path) -> list[str]:
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
    problemas: list[str] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            problemas += [
                f"import {a.name}" for a in no.names if a.name.split(".")[0] in MODULOS_PROIBIDOS
            ]
        elif isinstance(no, ast.ImportFrom) and (no.module or "").split(".")[0] in {
            *MODULOS_PROIBIDOS,
            "os",
        }:
            problemas += [
                f"from {no.module} import {a.name}"
                for a in no.names
                if a.name in CHAMADAS_PROIBIDAS or no.module in MODULOS_PROIBIDOS
            ]
        elif isinstance(no, ast.Call):
            alvo = no.func
            nome = (
                alvo.id
                if isinstance(alvo, ast.Name)
                else alvo.attr
                if isinstance(alvo, ast.Attribute)
                else ""
            )
            if nome in CHAMADAS_PROIBIDAS:
                problemas.append(f"chamada {nome}()")
    return problemas


def _sem_excecao(arquivo: Path) -> list[str]:
    relativo = arquivo.relative_to(RAIZ / "src" / "jarvis").as_posix()
    permitidos = EXCECOES.get(relativo, frozenset())
    return [p for p in achados(arquivo) if p not in permitidos]


@pytest.mark.parametrize("pacote", PACOTES_SEM_SHELL)
def test_pacote_nao_tem_caminho_para_shell(pacote: str) -> None:
    encontrados = {a.name: _sem_excecao(a) for a in arquivos(pacote)}

    assert arquivos(pacote), f"jarvis.{pacote} não tem arquivo nenhum — varredura vazia não vale"
    assert all(not v for v in encontrados.values()), encontrados


def test_a_varredura_pega_um_shell_plantado(tmp_path: Path) -> None:
    """Se a varredura não acusar isto, ela não serve para o aceite."""
    alvo = tmp_path / "ruim.py"
    alvo.write_text(
        "import subprocess as sp\nfrom os import system\n\n\n"
        "def f(cmd: str) -> None:\n    sp.run(cmd)\n    system(cmd)\n    eval(cmd)\n",
        encoding="utf-8",
    )

    problemas = achados(alvo)

    assert "import subprocess" in problemas
    assert "from os import system" in problemas
    assert "chamada eval()" in problemas
    assert "chamada system()" in problemas


def test_as_excecoes_existem_e_nao_vao_alem_do_nomeado() -> None:
    """A exceção tem de existir (senão a lista envelheceu) e não pode ter mais nada junto."""
    for relativo, permitidos in EXCECOES.items():
        arquivo = RAIZ / "src" / "jarvis" / relativo
        assert set(achados(arquivo)) == set(permitidos), relativo


def test_a_varredura_pega_processo_criado_por_fora_do_subprocess(tmp_path: Path) -> None:
    alvo = tmp_path / "ruim.py"
    alvo.write_text(
        "import os\n\n\ndef f() -> None:\n    os.posix_spawn('/bin/sh', ['sh'], {})\n"
        "    os.execv('/bin/sh', ['sh'])\n    os.fork()\n",
        encoding="utf-8",
    )
    problemas = achados(alvo)
    assert {"chamada posix_spawn()", "chamada execv()", "chamada fork()"} <= set(problemas)
