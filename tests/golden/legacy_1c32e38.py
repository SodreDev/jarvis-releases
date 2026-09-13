"""Oráculo golden: cópia LITERAL de trechos do commit `1c32e38` (baseline
2.7.0, antes do port Linux), embrulhada em funções que recebem `environ`/
`home` injetados em vez de ler `os.environ`/`Path.home()` direto.

NUNCA editar este arquivo fora de uma emenda do arquiteto (ver
docs/linux-port/FILA-fase1-executor.md, linha 12) — é o oráculo contra o
qual os testes C/K de F1-02, F1-03 e F1-07 comparam o comportamento novo.

Fontes:
- `git show 1c32e38:jarvis/config/paths.py` — `_appdata_root()` e as
  funções públicas `user_config_dir`, `user_data_dir`, `credentials_dir`,
  `logs_dir` (idênticas em HEAD; nada mudou até aqui).
- `git show 1c32e38:main.py`, âncoras `_wv_storage = os.path.join(`
  (`:2622`) e `_wv_data = os.path.join(` (`:13519`) — as duas expressões
  são literalmente iguais.
"""
from __future__ import annotations

import ntpath
from pathlib import Path


def legacy_appdata_root(environ: dict, home: str) -> Path:
    """`_appdata_root()` em 1c32e38, ramo `os.name == "nt"`.

    `os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")`
    — `or` trata APPDATA ausente OU vazio como "usar o padrão".
    """
    base = environ.get("APPDATA") or str(Path(home) / "AppData" / "Roaming")
    return Path(base) / "JARVIS"


def legacy_user_config_dir(environ: dict, home: str) -> Path:
    return legacy_appdata_root(environ, home)


def legacy_user_data_dir(environ: dict, home: str) -> Path:
    return legacy_appdata_root(environ, home) / "data"


def legacy_credentials_dir(environ: dict, home: str) -> Path:
    return legacy_appdata_root(environ, home) / "credentials"


def legacy_logs_dir(environ: dict, home: str) -> Path:
    return legacy_appdata_root(environ, home) / "logs"


def legacy_webview_storage(environ: dict, home: str) -> str:
    """`_wv_storage` (`main.py:2622`) e `_wv_data` (`main.py:13519`) em
    1c32e38 — as duas expressões são idênticas:

    `os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
    "JARVIS", "webview_data")`

    Usa `.get(chave, padrão)` de 2 argumentos: só cai no padrão (`home`)
    se a chave estiver AUSENTE — APPDATA vazio ("") permanece vazio. Essa
    semântica é diferente da de `legacy_appdata_root` (que usa `or`) e as
    duas devem ser preservadas separadamente (ver SPEC F1-02).

    `ntpath` em vez de `os.path`/`pathlib` porque, no Windows real,
    `os.path is ntpath` — reproduzimos isso explicitamente para o teste
    rodar de forma determinística também em host Linux.
    """
    return ntpath.join(environ.get("APPDATA", home), "JARVIS", "webview_data")


__all__ = [
    "legacy_appdata_root",
    "legacy_user_config_dir",
    "legacy_user_data_dir",
    "legacy_credentials_dir",
    "legacy_logs_dir",
    "legacy_webview_storage",
]
