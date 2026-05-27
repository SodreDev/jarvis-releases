# -*- coding: utf-8 -*-
"""
ide.api — Rotinas FastAPI que estendem o dashboard.server com /ide/*.

Importar este módulo **uma única vez** após `dashboard.server.app` existir
para registrar as rotas e o WebSocket de terminal.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from dashboard.server import app
from ide import workspace, terminal

_REGISTERED = False
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def register() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True

    if os.path.isdir(_STATIC_DIR):
        app.mount("/ide/static", StaticFiles(directory=_STATIC_DIR), name="ide_static")

    @app.get("/ide", response_class=HTMLResponse)
    async def ide_index():
        path = os.path.join(_STATIC_DIR, "index.html")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                return HTMLResponse(fh.read())
        return HTMLResponse("<h1>JARVIS IDE</h1><p>frontend não encontrado.</p>")

    @app.get("/ide/api/projects")
    async def list_projects():
        return {"projects": workspace.list_projects()}

    @app.post("/ide/api/projects")
    async def create_project(req: Request):
        body = await req.json()
        return workspace.create_project(body.get("name", ""), description=body.get("description", ""))

    @app.delete("/ide/api/projects/{name}")
    async def delete_project(name: str):
        return {"ok": workspace.delete_project(name)}

    @app.get("/ide/api/tree/{project}")
    async def tree(project: str):
        return {"tree": workspace.list_tree(project)}

    @app.get("/ide/api/file/{project}")
    async def read_file_ep(project: str, path: str):
        try:
            return {"content": workspace.read_file(project, path)}
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/ide/api/file/{project}")
    async def write_file_ep(project: str, req: Request):
        body = await req.json()
        try:
            full = workspace.write_file(project, body.get("path", ""), body.get("content", ""))
            return {"ok": True, "path": full}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.delete("/ide/api/file/{project}")
    async def delete_file_ep(project: str, path: str):
        try:
            return {"ok": workspace.delete_file(project, path)}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.post("/ide/api/move/{project}")
    async def move_file_ep(project: str, req: Request):
        body = await req.json()
        try:
            new_path = workspace.move_file(project, body.get("src", ""), body.get("dst", ""))
            return {"ok": True, "path": new_path}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.post("/ide/api/mkdir/{project}")
    async def mkdir_ep(project: str, req: Request):
        body = await req.json()
        try:
            full = workspace.mkdir(project, body.get("path", ""))
            return {"ok": True, "path": full}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.post("/ide/api/explorer/{project}")
    async def explorer_ep(project: str, req: Request):
        body = await req.json()
        try:
            workspace.open_in_explorer(project, body.get("path", ""))
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    # ── Runner (executa projeto, detecta porta/localhost) ───────────────

    # slug → {process, port, output_lines}
    _runners: dict[str, dict] = {}

    @app.post("/ide/api/run/{project}")
    async def run_project_ep(project: str, req: Request):
        """Detecta o tipo de projeto e executa o entrypoint correto."""
        body = await req.json()
        proj_dir = workspace.project_dir(project)

        # Mata processo anterior se existir
        old = _runners.get(project)
        if old and old.get("process"):
            try:
                old["process"].terminate()
            except Exception:
                pass

        # Detecta entrypoint
        custom_cmd = body.get("cmd")  # override manual
        if custom_cmd:
            cmd = custom_cmd
        elif os.path.exists(os.path.join(proj_dir, "package.json")):
            cmd = "npm start" if os.path.exists(os.path.join(proj_dir, "node_modules")) else "npm install && npm start"
        elif os.path.exists(os.path.join(proj_dir, "requirements.txt")):
            venv_py = os.path.join(proj_dir, ".venv", "Scripts", "python.exe")
            py = venv_py if os.path.exists(venv_py) else sys.executable
            # Detecta main.py, app.py, server.py
            for entry in ("main.py", "app.py", "server.py", "run.py"):
                if os.path.exists(os.path.join(proj_dir, entry)):
                    cmd = f'"{py}" {entry}'
                    break
            else:
                cmd = f'"{py}" -m flask run'
        elif os.path.exists(os.path.join(proj_dir, "index.html")):
            # Serve HTML estático com Python http.server
            import random
            port = random.randint(7000, 7999)
            cmd = f'"{sys.executable}" -m http.server {port}'
            _runners[project] = {"port": port, "process": None, "output": []}
        else:
            return JSONResponse({"ok": False, "error": "Não consegui detectar o tipo de projeto."}, status_code=400)

        try:
            proc = subprocess.Popen(
                cmd, cwd=proj_dir, shell=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            info = _runners.setdefault(project, {"port": None, "process": None, "output": []})
            info["process"] = proc
            info["output"] = []

            async def _watch():
                loop = asyncio.get_event_loop()
                port_found = info.get("port")
                for line in proc.stdout:  # type: ignore[union-attr]
                    info["output"].append(line.rstrip())
                    if not port_found:
                        m = re.search(r"(?:port|localhost)[:\s]+(\d{2,5})", line, re.I)
                        if m:
                            info["port"] = int(m.group(1))
                            port_found = info["port"]

            asyncio.create_task(_watch())
            return {"ok": True, "pid": proc.pid}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.get("/ide/api/run/{project}/status")
    async def run_status_ep(project: str):
        info = _runners.get(project)
        if not info:
            return {"running": False}
        proc = info.get("process")
        running = proc is not None and proc.poll() is None
        return {
            "running": running,
            "port": info.get("port"),
            "url": f"http://localhost:{info['port']}" if info.get("port") else None,
            "output": info.get("output", [])[-50:],
        }

    @app.post("/ide/api/run/{project}/stop")
    async def run_stop_ep(project: str):
        info = _runners.get(project)
        if info and info.get("process"):
            try:
                info["process"].terminate()
                info["process"] = None
            except Exception as e:
                return {"ok": False, "error": str(e)}
        return {"ok": True}

    # ── Multi-terminal: sessões nomeadas ────────────────────────────────

    @app.websocket("/ide/ws/terminal/{project}/{term_id}")
    async def terminal_ws_named(ws: WebSocket, project: str, term_id: str):
        """Terminal nomeado — usa `term_id` como chave de sessão,
        permitindo múltiplos terminais simultâneos no mesmo projeto."""
        await ws.accept()
        proj_path = workspace.project_dir(project, create=True)
        # Usa chave composta para isolar sessões
        sess_key = f"{proj_path}::{term_id}"
        sess = terminal.get_session(sess_key, cwd=proj_path)
        loop = asyncio.get_event_loop()

        def _on_data(data: bytes):
            try:
                asyncio.run_coroutine_threadsafe(
                    ws.send_text(data.decode("utf-8", errors="replace")), loop
                )
            except Exception:
                pass

        try:
            await ws.send_text(sess.buffer().decode("utf-8", errors="replace"))
        except Exception:
            pass

        sess.add_listener(_on_data)
        try:
            while True:
                msg = await ws.receive_text()
                sess.write(msg)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            sess.remove_listener(_on_data)

    @app.websocket("/ide/ws/terminal/{project}")
    async def terminal_ws(ws: WebSocket, project: str):
        await ws.accept()
        proj_path = workspace.project_dir(project, create=True)
        sess = terminal.get_session(proj_path)
        loop = asyncio.get_event_loop()

        def _on_data(data: bytes):
            try:
                asyncio.run_coroutine_threadsafe(
                    ws.send_text(data.decode("utf-8", errors="replace")), loop
                )
            except Exception:
                pass

        # Envia buffer histórico
        try:
            await ws.send_text(sess.buffer().decode("utf-8", errors="replace"))
        except Exception:
            pass

        sess.add_listener(_on_data)
        try:
            while True:
                msg = await ws.receive_text()
                sess.write(msg)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            sess.remove_listener(_on_data)


__all__ = ["register"]
