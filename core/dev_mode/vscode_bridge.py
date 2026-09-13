# core/dev_mode/vscode_bridge.py — WebSocket server para comunicação Jarvis ↔ VSCode.
#
# Protocolo JSON:
#   Jarvis → VSCode:  {"type": "prompt", "id": "<uuid>", "prompt": "...", "intent": "...", "autonomous": true}
#   VSCode → Jarvis:  {"type": "ack", "id": "<uuid>", "status": "received|executing|done|error", "message": "..."}
#
# O servidor só roda enquanto o Dev Mode está ativo (on-demand).
# Thread-safe: a API pública pode ser chamada de qualquer thread.

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from typing import Any

_ws_module = None


def _get_websockets():
    """Lazy-import do módulo websockets para não forçar instalação global."""
    global _ws_module
    if _ws_module is None:
        import websockets
        _ws_module = websockets
    return _ws_module


class VSCodeBridge:
    """WebSocket server para enviar prompts ao VSCode e receber acks."""

    def __init__(self, port: int = 6589, host: str = "127.0.0.1") -> None:
        self._host = host
        self._port = port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: Any = None  # websockets.serve object
        self._thread: threading.Thread | None = None
        self._clients: set = set()
        self._lock = threading.Lock()
        self._running = False
        # Callbacks para acks recebidos: {msg_id: asyncio.Future}
        self._pending_acks: dict[str, asyncio.Future] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Inicia o WebSocket server em uma thread daemon separada."""
        if self._running:
            print("[DEV BRIDGE] Servidor já está rodando.")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="DevBridge-WS")
        self._thread.start()
        print(f"[DEV BRIDGE] Servidor WebSocket iniciando em ws://{self._host}:{self._port}")

    def stop(self) -> None:
        """Para o WebSocket server e desconecta todos os clientes."""
        if not self._running:
            return

        self._running = False

        if self._loop and not self._loop.is_closed():
            # Agenda o shutdown no event loop
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        self._thread = None
        self._server = None
        self._loop = None
        print("[DEV BRIDGE] Servidor WebSocket parado.")

    # ── API pública (thread-safe) ─────────────────────────────────────────────

    def send_prompt(self, prompt: str, intent: str, *, autonomous: bool = True) -> bool:
        """Envia um prompt para o primeiro cliente VSCode conectado.

        Args:
            prompt: Prompt estruturado completo.
            intent: Tipo de intent (feature_request, refactor, debug, etc.).
            autonomous: Se o Copilot deve executar sem pedir aprovação.

        Returns:
            True se enviou com sucesso, False se nenhum cliente conectado ou erro.
        """
        if not self._running or not self._loop:
            print("[DEV BRIDGE] Servidor não está rodando.")
            return False

        with self._lock:
            if not self._clients:
                print("[DEV BRIDGE] Nenhum cliente VSCode conectado.")
                return False

        msg_id = str(uuid.uuid4())
        message = json.dumps({
            "type": "prompt",
            "id": msg_id,
            "prompt": prompt,
            "intent": intent,
            "autonomous": autonomous,
        }, ensure_ascii=False)

        future = asyncio.run_coroutine_threadsafe(
            self._broadcast(message), self._loop
        )

        try:
            # Aguarda até 10s pelo envio
            result = future.result(timeout=10)
            if result:
                print(f"[DEV BRIDGE] Prompt enviado (id={msg_id[:8]}…, intent={intent})")
            return result
        except Exception as e:
            print(f"[DEV BRIDGE] Erro ao enviar prompt: {e}")
            return False

    def is_connected(self) -> bool:
        """Retorna True se há pelo menos um cliente VSCode conectado."""
        with self._lock:
            return len(self._clients) > 0

    @property
    def client_count(self) -> int:
        """Número de clientes VSCode conectados."""
        with self._lock:
            return len(self._clients)

    @property
    def running(self) -> bool:
        return self._running

    # ── Internals ─────────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Roda o event loop asyncio na thread dedicada."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:
            if self._running:
                print(f"[DEV BRIDGE] Erro no event loop: {e}")
        finally:
            self._loop.close()

    async def _serve(self) -> None:
        """Inicia o servidor WebSocket e mantém rodando."""
        ws = _get_websockets()
        async with ws.serve(
            self._handler,
            self._host,
            self._port,
            ping_interval=30,
            ping_timeout=10,
        ) as server:
            self._server = server
            print(f"[DEV BRIDGE] WebSocket ouvindo em ws://{self._host}:{self._port}")
            # Mantém rodando enquanto _running é True
            while self._running:
                await asyncio.sleep(0.5)

    async def _handler(self, websocket) -> None:
        """Handler de conexão — registra cliente, processa mensagens, limpa ao desconectar."""
        remote = getattr(websocket, "remote_address", ("?", 0))
        print(f"[DEV BRIDGE] VSCode conectado: {remote}")

        with self._lock:
            self._clients.add(websocket)
        try:
            async for raw_message in websocket:
                try:
                    data = json.loads(raw_message)
                    await self._process_message(data, websocket)
                except json.JSONDecodeError:
                    print(f"[DEV BRIDGE] Mensagem inválida (não-JSON): {raw_message[:80]}")
        except Exception as e:
            ws = _get_websockets()
            if not isinstance(e, ws.exceptions.ConnectionClosed):
                print(f"[DEV BRIDGE] Erro na conexão: {e}")
        finally:
            with self._lock:
                self._clients.discard(websocket)
            print(f"[DEV BRIDGE] VSCode desconectado: {remote}")

    async def _process_message(self, data: dict, websocket) -> None:
        """Processa mensagens recebidas do VSCode."""
        msg_type = data.get("type", "")

        if msg_type == "ack":
            msg_id = data.get("id", "")
            status = data.get("status", "unknown")
            message = data.get("message", "")
            print(f"[DEV BRIDGE] ACK recebido: id={msg_id[:8]}…, status={status}, msg={message[:60]}")

            # Resolve future pendente se existir
            future = self._pending_acks.pop(msg_id, None)
            if future and not future.done():
                future.set_result(data)

        elif msg_type == "status":
            # VSCode reportando seu estado
            print(f"[DEV BRIDGE] Status do VSCode: {data.get('message', '')}")

        elif msg_type == "ping":
            # Responde com pong
            await websocket.send(json.dumps({"type": "pong"}))

        else:
            print(f"[DEV BRIDGE] Tipo de mensagem desconhecido: {msg_type}")

    async def _broadcast(self, message: str) -> bool:
        """Envia mensagem para todos os clientes conectados."""
        ws = _get_websockets()
        with self._lock:
            clients = list(self._clients)

        if not clients:
            return False

        sent = False
        for client in clients:
            try:
                await client.send(message)
                sent = True
            except ws.exceptions.ConnectionClosed:
                with self._lock:
                    self._clients.discard(client)
            except Exception as e:
                print(f"[DEV BRIDGE] Erro ao enviar para cliente: {e}")

        return sent

    async def _shutdown(self) -> None:
        """Fecha todas as conexões e para o servidor."""
        ws = _get_websockets()
        with self._lock:
            clients = list(self._clients)
            self._clients.clear()

        # Envia mensagem de shutdown para cada cliente
        shutdown_msg = json.dumps({"type": "shutdown", "message": "Dev Mode desativado"})
        for client in clients:
            try:
                await client.send(shutdown_msg)
                await client.close()
            except Exception:
                pass

        if self._server:
            self._server.close()
