"""Um servidor MCP de mentira por stdio (JSON-RPC por linhas), para os testes do cliente (ADR-0052).

Não toca rede: responde `initialize`, `tools/list` e `tools/call` de uma lista fixa. Rode-o como
processo filho com `[sys.executable, "-I", __file__]`.
"""

from __future__ import annotations

import json
import sys

TOOLS = [
    {
        "name": "list_console_messages",
        "description": "lê o console da aba e devolve as mensagens",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "evaluate_script",
        "description": "roda um script na página e devolve o valor",
        "inputSchema": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
    {
        "name": "navigate_page",
        "description": "navega a aba para uma URL",
        "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}},
    },
    {"name": "shell_exec", "description": "roda um comando (proibida de promover)"},
]


def _resposta(pedido: dict) -> dict | None:
    metodo = pedido.get("method")
    ident = pedido.get("id")
    if metodo == "initialize":
        return {"jsonrpc": "2.0", "id": ident, "result": {"protocolVersion": "2025-06-18"}}
    if metodo == "notifications/initialized":
        return None  # notificação: sem resposta
    if metodo == "tools/list":
        return {"jsonrpc": "2.0", "id": ident, "result": {"tools": TOOLS}}
    if metodo == "tools/call":
        args = (pedido.get("params") or {}).get("arguments", {})
        texto = f"eco: {json.dumps(args, ensure_ascii=False)}"
        return {
            "jsonrpc": "2.0",
            "id": ident,
            "result": {"content": [{"type": "text", "text": texto}]},
        }
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": "método ausente"}}


def principal() -> int:
    for linha in sys.stdin:
        linha = linha.strip()
        if not linha:
            continue
        try:
            pedido = json.loads(linha)
        except ValueError:
            continue
        resposta = _resposta(pedido)
        if resposta is not None:
            sys.stdout.write(json.dumps(resposta, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
