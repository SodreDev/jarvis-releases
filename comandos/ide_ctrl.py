# -*- coding: utf-8 -*-
"""comandos.ide_ctrl — Fachada da IDE para o JARVIS."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from typing import Optional

# slug → {process, port, output}  — projetos em execução
_runners: dict[str, dict] = {}


def abrir_ide(*, open_browser: bool = True, projeto: Optional[str] = None,
              arquivo: Optional[str] = None) -> str:
    """Sobe painel+IDE e abre /ide no navegador.

    Se `projeto` e/ou `arquivo` forem informados, gera deep-link
    `/ide?project=X&open=Y` para o frontend abrir automaticamente.
    """
    from dashboard.server import start_dashboard, open_in_browser, url as _url
    from ide.api import register
    from urllib.parse import urlencode
    start_dashboard()
    register()
    full = _url() + "ide"
    qs = {}
    if projeto: qs["project"] = projeto
    if arquivo: qs["open"] = arquivo
    if qs:
        full += "?" + urlencode(qs)
    if open_browser:
        open_in_browser(full)
    return full


def iniciar_projeto(descricao: str, *, nome: Optional[str] = None, kind: Optional[str] = None,
                    abrir: bool = True) -> dict:
    from ide.project_planner import iniciar_projeto as _ip
    info = _ip(descricao, nome=nome, kind=kind)
    if abrir:
        abrir_ide(open_browser=True)
    return info


def listar_projetos() -> list:
    from ide import workspace
    return workspace.list_projects()


def deletar_projeto(nome: str) -> bool:
    """Deleta projeto por slug exato ou por correspondência parcial de palavras."""
    from ide import workspace
    # 1. Tentativa exata
    if workspace.delete_project(nome):
        return True
    # 2. Fuzzy: encontra slug cujas palavras contenham os termos da query
    nome_norm = nome.lower().replace("_", " ").replace("-", " ")
    termos = [t for t in nome_norm.split() if len(t) > 3]
    if not termos:
        return False
    for proj in workspace.list_projects():
        slug = proj.get("slug", "")
        slug_clean = slug.replace("_", " ").replace("-", " ")
        if any(t in slug_clean for t in termos):
            return workspace.delete_project(slug)
    return False


def criar_pasta(projeto: str, caminho: str) -> str:
    """Cria uma pasta dentro do projeto. Retorna o caminho absoluto criado."""
    from ide import workspace
    return workspace.mkdir(projeto, caminho)


def mover_arquivo(projeto: str, src: str, dst: str) -> str:
    """Move ou renomeia um arquivo dentro do projeto. Retorna o novo caminho."""
    from ide import workspace
    return workspace.move_file(projeto, src, dst)


def abrir_explorador(projeto: str, caminho: str = "") -> None:
    """Abre a pasta do projeto (ou subcaminho) no Windows Explorer."""
    from ide import workspace
    workspace.open_in_explorer(projeto, caminho)


def executar_projeto(projeto: str, cmd_override: Optional[str] = None) -> dict:
    """Detecta o entrypoint do projeto e executa em background.

    Retorna ``{"ok": True, "pid": int, "url": str|None}`` ou
    ``{"ok": False, "error": str}``.
    """
    from ide import workspace
    import random

    proj_dir = workspace.project_dir(projeto)
    if not os.path.isdir(proj_dir):
        return {"ok": False, "error": f"Projeto '{projeto}' não encontrado."}

    # Encerra processo anterior se houver
    parar_projeto(projeto)

    if cmd_override:
        cmd = cmd_override
        port: Optional[int] = None
    elif os.path.exists(os.path.join(proj_dir, "package.json")):
        has_modules = os.path.exists(os.path.join(proj_dir, "node_modules"))
        cmd = "npm start" if has_modules else "npm install && npm start"
        port = 3000
    elif os.path.exists(os.path.join(proj_dir, "requirements.txt")):
        venv_py = os.path.join(proj_dir, ".venv", "Scripts", "python.exe")
        py = venv_py if os.path.exists(venv_py) else sys.executable
        for entry in ("main.py", "app.py", "server.py", "run.py"):
            if os.path.exists(os.path.join(proj_dir, entry)):
                cmd = f'"{py}" {entry}'
                break
        else:
            cmd = f'"{py}" -m flask run'
        port = None
    elif os.path.exists(os.path.join(proj_dir, "index.html")):
        port = random.randint(7000, 7999)
        cmd = f'"{sys.executable}" -m http.server {port}'
    else:
        return {"ok": False, "error": "Tipo de projeto não detectado (sem package.json, requirements.txt ou index.html)."}

    try:
        proc = subprocess.Popen(
            cmd, cwd=proj_dir, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        info: dict = {"process": proc, "port": port, "output": []}
        _runners[projeto] = info

        def _watch() -> None:
            for line in proc.stdout:  # type: ignore[union-attr]
                info["output"].append(line.rstrip())
                if not info.get("port"):
                    m = re.search(r"(?:port|localhost)[:\s]+(\d{2,5})", line, re.I)
                    if m:
                        info["port"] = int(m.group(1))

        threading.Thread(target=_watch, daemon=True).start()
        url = f"http://localhost:{port}" if port else None
        return {"ok": True, "pid": proc.pid, "url": url}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def parar_projeto(projeto: str) -> bool:
    """Encerra o processo do projeto em execução. Retorna True se havia algo rodando."""
    info = _runners.get(projeto)
    if info and info.get("process"):
        try:
            info["process"].terminate()
            info["process"] = None
            return True
        except Exception:
            pass
    return False


def status_projeto(projeto: str) -> dict:
    """Retorna o status de execução do projeto."""
    info = _runners.get(projeto)
    if not info:
        return {"running": False, "port": None, "url": None}
    proc = info.get("process")
    running = proc is not None and proc.poll() is None
    p = info.get("port")
    return {
        "running": running,
        "port": p,
        "url": f"http://localhost:{p}" if p else None,
        "output_tail": info.get("output", [])[-20:],
    }


__all__ = [
    "abrir_ide", "iniciar_projeto", "listar_projetos", "deletar_projeto",
    "criar_pasta", "mover_arquivo", "abrir_explorador",
    "executar_projeto", "parar_projeto", "status_projeto",
]
