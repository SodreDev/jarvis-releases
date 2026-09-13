# -*- coding: utf-8 -*-
"""
dashboard.server — Painel web Stark do JARVIS (FastAPI + WebSocket).

Endpoints:
    GET  /              → frontend Stark estático
    GET  /api/state     → snapshot atual (monitors, cards, status)
    POST /api/cards     → adiciona um card (server-side push)
    DELETE /api/cards/{id}
    POST /api/window/move → move janela {hwnd|title, monitor, ratio, fullscreen, align}
    GET  /api/monitors  → lista monitores
    WS   /ws            → push em tempo-real (events bus → clientes)

Uso:
    from dashboard.server import start_dashboard, open_in_browser
    url = start_dashboard()           # roda em thread daemon, retorna URL
    open_in_browser(url)              # abre no navegador padrão

Cards podem ser publicados pelo resto do JARVIS:
    from dashboard.server import push_card
    push_card({"id": "weather", "title": "Tempo", "body": "23°C ensolarado"})
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import webbrowser
from typing import Any, Dict, List, Optional

_FASTAPI_OK = True
_FASTAPI_ERR: Optional[Exception] = None
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn
except Exception as exc:  # pragma: no cover
    _FASTAPI_OK = False
    _FASTAPI_ERR = exc
    # Stubs para evitar NameError nas definições de rotas abaixo
    FastAPI = None          # type: ignore[assignment]
    WebSocket = None        # type: ignore[assignment]
    WebSocketDisconnect = None  # type: ignore[assignment]
    Request = None          # type: ignore[assignment]
    HTMLResponse = None     # type: ignore[assignment]
    JSONResponse = None     # type: ignore[assignment]
    StaticFiles = None      # type: ignore[assignment]
    uvicorn = None          # type: ignore[assignment]

logger = logging.getLogger("jarvis.dashboard")

_HOST = "127.0.0.1"
_PORT = int(os.environ.get("JARVIS_DASHBOARD_PORT", "8765"))
_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# ─────────────────────────────────────────────────────────────────────────────
# Estado in-memory (singleton)
# ─────────────────────────────────────────────────────────────────────────────
_state_lock = threading.RLock()
_cards: Dict[str, Dict[str, Any]] = {}
_logs: List[Dict[str, Any]] = []
_clients: "set" = set()
_loop: Optional[asyncio.AbstractEventLoop] = None
_started = False

# Fila de comandos enviados pelo painel (chat → JARVIS)
_pending_cmds: List[Dict[str, Any]] = []
_cmd_lock = threading.Lock()


def _now_ms() -> int:
    return int(time.time() * 1000)


def push_card(card: Dict[str, Any]) -> None:
    """Adiciona/atualiza um card no painel."""
    cid = str(card.get("id") or f"c{_now_ms()}")
    card["id"] = cid
    card.setdefault("ts", _now_ms())
    with _state_lock:
        _cards[cid] = card
    _broadcast({"type": "card", "card": card})


def remove_card(card_id: str) -> bool:
    with _state_lock:
        if card_id in _cards:
            del _cards[card_id]
            _broadcast({"type": "card_remove", "id": card_id})
            return True
    return False


def push_chat(role: str, text: str) -> None:
    """Emite uma mensagem de chat no painel (role: 'user' | 'jarvis')."""
    push_log("chat", text, source=role)
    _broadcast({"type": "chat", "role": role, "text": text, "ts": _now_ms()})


def get_pending_cmd() -> Optional[Dict[str, Any]]:
    """Retorna e remove o próximo comando pendente do painel (ou None)."""
    with _cmd_lock:
        if _pending_cmds:
            return _pending_cmds.pop(0)
    return None


def push_log(level: str, msg: str, *, source: str = "jarvis") -> None:
    entry = {"ts": _now_ms(), "level": level, "msg": msg, "source": source}
    with _state_lock:
        _logs.append(entry)
        if len(_logs) > 500:
            del _logs[:-500]
    _broadcast({"type": "log", "entry": entry})


def _broadcast(payload: Dict[str, Any]) -> None:
    """Envia payload a todos os WebSockets conectados (thread-safe)."""
    if not _clients or _loop is None:
        return
    data = json.dumps(payload, default=str)

    async def _send_all():
        dead = []
        for ws in list(_clients):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _clients.discard(ws)

    try:
        asyncio.run_coroutine_threadsafe(_send_all(), _loop)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# App FastAPI (criado apenas se fastapi estiver disponível)
# ─────────────────────────────────────────────────────────────────────────────
if _FASTAPI_OK:
    app = FastAPI(title="JARVIS Stark Panel", docs_url=None, redoc_url=None)
    if os.path.isdir(_STATIC_DIR):
        app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
else:
    app = None  # type: ignore[assignment]


if _FASTAPI_OK:
    @app.get("/", response_class=HTMLResponse)
    async def index():
        path = os.path.join(_STATIC_DIR, "index.html")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                return HTMLResponse(fh.read())
        return HTMLResponse("<h1>JARVIS Stark Panel</h1><p>static/index.html não encontrado.</p>")

    @app.get("/api/state")
    async def get_state():
        try:
            from core import screens
            mons = [m.to_dict() for m in screens.list_monitors()]
        except Exception:
            mons = []
        with _state_lock:
            return {
                "monitors": mons,
                "cards": list(_cards.values()),
                "logs": _logs[-50:],
                "ts": _now_ms(),
            }

    @app.get("/api/monitors")
    async def get_monitors():
        try:
            from core import screens
            return {"monitors": [m.to_dict() for m in screens.list_monitors()]}
        except Exception as e:
            return JSONResponse({"error": str(e), "monitors": []}, status_code=500)

    def _read_brain() -> Dict[str, Any]:
        """Snapshot das CAMADAS da memória p/ o viewer do Cérebro (best-effort,
        barato: lê os .json/.npy persistidos; semeia a camada META 1x)."""
        out: Dict[str, Any] = {"layers": [], "stats": {}, "ts": _now_ms()}
        try:
            from jarvis.memory import layers as _lay
            snap = _lay.snapshot()
            out["layers"] = snap.get("layers", [])
        except Exception as e:
            out["layers_error"] = str(e)
        out["stats"] = {l["id"]: int(l.get("count", 0)) for l in out["layers"]}
        return out

    @app.get("/api/brain")
    async def get_brain():
        """Snapshot das memórias do JARVIS (para a aba Cérebro da dashboard)."""
        try:
            return await asyncio.get_event_loop().run_in_executor(None, _read_brain)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/api/brain/sync")
    async def post_brain_sync():
        """(Re)indexa as instruções das tools na camada de skills (carrega o MiniLM)."""
        def _do():
            try:
                from jarvis.memory import skills as _sk
                n = _sk.sync_from_registry()
                return {"ok": True, "indexed": n}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        res = await asyncio.get_event_loop().run_in_executor(None, _do)
        return JSONResponse(res)

    @app.get("/api/windows")
    async def get_windows():
        try:
            from core import screens
            ws = screens.list_windows()
            return {"windows": [{"hwnd": h, "title": t} for h, t in ws]}
        except Exception as e:
            return JSONResponse({"error": str(e), "windows": []}, status_code=500)

    @app.post("/api/cards")
    async def post_card(req: Request):
        body = await req.json()
        push_card(body)
        return {"ok": True, "id": body.get("id")}

    @app.delete("/api/cards/{card_id}")
    async def del_card(card_id: str):
        return {"ok": remove_card(card_id)}

    @app.post("/api/window/move")
    async def post_window_move(req: Request):
        body = await req.json()
        try:
            from core import screens
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
        mon = int(body.get("monitor", 0))
        fullscreen = bool(body.get("fullscreen", False))
        ratio = float(body.get("ratio", 1.0))
        align = str(body.get("align", "center"))
        hwnd = body.get("hwnd")
        title = body.get("title")
        if hwnd is not None:
            ok = screens.move_window(int(hwnd), mon, fullscreen=fullscreen, ratio=ratio, align=align)
        elif title:
            ok = screens.move_window_by_title(str(title), mon, fullscreen=fullscreen, ratio=ratio, align=align)
        else:
            return JSONResponse({"ok": False, "error": "missing hwnd/title"}, status_code=400)
        return {"ok": bool(ok)}

    @app.get("/painel", response_class=HTMLResponse)
    async def painel_page():
        """Serve o Painel Global rico (painel.html)."""
        path = os.path.join(_STATIC_DIR, "painel.html")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                return HTMLResponse(fh.read())
        return HTMLResponse("<h1>painel.html não encontrado</h1>", status_code=404)

    @app.get("/api/stocks")
    async def get_stocks(s: str = ""):
        """Retorna cotações em tempo real. s=PETR4.SA,VALE3.SA (símbolos yfinance)."""
        symbols = [x.strip() for x in s.split(",") if x.strip()]
        if not symbols:
            return JSONResponse({"quotes": {}}, status_code=400)
        try:
            import yfinance as yf
            quotes: Dict[str, Any] = {}
            for sym in symbols:
                try:
                    ticker = yf.Ticker(sym)
                    info = ticker.fast_info
                    price = float(getattr(info, "last_price", 0) or 0)
                    prev  = float(getattr(info, "previous_close", price) or price)
                    chg   = ((price - prev) / prev * 100) if prev else 0.0
                    quotes[sym] = {
                        "symbol": sym,
                        "price": round(price, 2),
                        "change_pct": round(chg, 2),
                        "name": getattr(info, "exchange", sym),
                    }
                except Exception:
                    quotes[sym] = {"symbol": sym, "price": 0, "change_pct": 0}
            return {"quotes": quotes, "ts": _now_ms()}
        except ImportError:
            return JSONResponse({"error": "yfinance não instalado", "quotes": {}}, status_code=500)
        except Exception as exc:
            return JSONResponse({"error": str(exc), "quotes": {}}, status_code=500)

    @app.post("/api/cmd")
    async def post_cmd(req: Request):
        """Recebe comando enviado pelo painel (chat sidebar → JARVIS)."""
        body = await req.json()
        cmd = str(body.get("cmd") or "").strip()
        if not cmd:
            return JSONResponse({"ok": False, "error": "cmd vazio"}, status_code=400)
        entry: Dict[str, Any] = {
            "cmd": cmd,
            "source": str(body.get("source", "painel")),
            "ts": int(body.get("ts", _now_ms())),
        }
        with _cmd_lock:
            _pending_cmds.append(entry)
            if len(_pending_cmds) > 50:
                del _pending_cmds[:-50]
        push_log("chat", cmd, source="user")
        _broadcast({"type": "chat", "role": "user", "text": cmd, "ts": entry["ts"]})
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        _clients.add(ws)
        try:
            await ws.send_text(json.dumps({"type": "snapshot", "state": (await get_state())}, default=str))
            while True:
                text = await ws.receive_text()
                try:
                    msg = json.loads(text)
                    if isinstance(msg, dict) and msg.get("type") == "cmd":
                        cmd_text = str(msg.get("cmd") or "").strip()
                        if cmd_text:
                            with _cmd_lock:
                                _pending_cmds.append({"cmd": cmd_text, "source": "painel_ws", "ts": _now_ms()})
                except Exception:
                    pass
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            _clients.discard(ws)


# ─────────────────────────────────────────────────────────────────────────────
# Lifecycle
# ─────────────────────────────────────────────────────────────────────────────
_server: Any = None  # uvicorn.Server when running
_thread: Optional[threading.Thread] = None


def _run_server():
    global _loop, _server
    config = uvicorn.Config(
        app, host=_HOST, port=_PORT, log_level="warning", access_log=False
    )
    _server = uvicorn.Server(config)
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    try:
        _loop.run_until_complete(_server.serve())
    except Exception as e:
        logger.exception("dashboard server crashed: %s", e)


def start_dashboard(*, open_browser: bool = False) -> str:
    """Inicia o servidor em thread daemon. Idempotente. Retorna a URL."""
    global _started, _thread
    if not _FASTAPI_OK:
        raise RuntimeError(
            "Painel indisponível: instale fastapi e uvicorn.\n"
            "  pip install fastapi uvicorn\n"
            f"  (Causa: {_FASTAPI_ERR})"
        )
    url = f"http://{_HOST}:{_PORT}/"
    if _started:
        if open_browser:
            open_in_browser(url)
        return url
    _thread = threading.Thread(target=_run_server, name="JarvisDashboard", daemon=True)
    _thread.start()
    _started = True
    # Espera o servidor abrir o socket (best-effort)
    for _ in range(50):
        if _loop is not None:
            break
        time.sleep(0.05)
    if open_browser:
        open_in_browser(url)
    return url


def stop_dashboard() -> None:
    global _started
    if _server is not None:
        try:
            _server.should_exit = True
        except Exception:
            pass
    _started = False


def open_in_browser(url: Optional[str] = None) -> bool:
    target = url or f"http://{_HOST}:{_PORT}/"
    try:
        return bool(webbrowser.open(target, new=2))
    except Exception:
        return False


def is_running() -> bool:
    return _started


def url(path: str = "/") -> str:
    return f"http://{_HOST}:{_PORT}{path}"


def url_painel() -> str:
    """URL do Painel Global rico."""
    return url("/painel")


__all__ = [
    "app",
    "start_dashboard",
    "stop_dashboard",
    "open_in_browser",
    "is_running",
    "url",
    "url_painel",
    "push_card",
    "remove_card",
    "push_log",
    "push_chat",
    "get_pending_cmd",
]
