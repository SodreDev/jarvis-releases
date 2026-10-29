"""O cliente MCP por stdio (ADR-0052): JSON-RPC 2.0 por linhas, sem rede do nosso lado.

O servidor é um processo filho que o dono configurou (`mcp.toml`); o cliente faz o aperto de mão
(`initialize` → `notifications/initialized`), lista as tools (`tools/list`) e as chama
(`tools/call`), com prazo. A identidade do servidor é **pinada** por hash do comando: mudou, o
gestor suspende até o dono reconfirmar. Tudo que volta é dado (`untrusted`), nunca ordem.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from jarvis.mcp.config import ServidorMcp

VERSAO_DO_PROTOCOLO: Final = "2025-06-18"
PRAZO_PADRAO_S: Final = 30.0


class ErroMcp(RuntimeError):
    """O servidor MCP falhou, não respondeu a tempo, ou devolveu erro JSON-RPC."""


class Transporte(Protocol):
    """Troca mensagens JSON-RPC com um servidor. O stdio é o de produção; os testes injetam um
    duplo em processo, sem subir processo nenhum."""

    def pedir(self, mensagem: Mapping[str, Any], *, prazo_s: float) -> dict[str, Any]: ...
    def notificar(self, mensagem: Mapping[str, Any]) -> None: ...
    def fechar(self) -> None: ...


def identidade(servidor: ServidorMcp) -> str:
    """O pino de identidade: hash do comando. Mudou o comando, muda o pino (ADR-0010/0023)."""
    return hashlib.sha256("\x00".join(servidor.comando).encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True)
class TransporteStdio:
    """Um servidor MCP como processo filho, JSON-RPC por linhas no stdin/stdout (sem rede nossa)."""

    comando: Sequence[str]
    ambiente: Mapping[str, str] | None = None
    _processo: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _subir(self) -> subprocess.Popen[bytes]:
        if self._processo is not None and self._processo.poll() is None:
            return self._processo
        # argv sem shell, executável do comando que o DONO configurou (ADR-0052); sem env extra.
        self._processo = subprocess.Popen(  # noqa: S603
            list(self.comando),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=dict(self.ambiente) if self.ambiente is not None else None,
            start_new_session=True,
        )
        return self._processo

    def pedir(self, mensagem: Mapping[str, Any], *, prazo_s: float) -> dict[str, Any]:
        with self._lock:
            processo = self._subir()
            assert processo.stdin is not None and processo.stdout is not None
            linha = (json.dumps(mensagem, ensure_ascii=False) + "\n").encode("utf-8")
            try:
                processo.stdin.write(linha)
                processo.stdin.flush()
            except (BrokenPipeError, OSError) as erro:
                raise ErroMcp(f"o servidor MCP fechou o stdin: {erro}") from None
            resultado: list[dict[str, Any]] = []

            def ler() -> None:
                bruta = processo.stdout.readline()  # type: ignore[union-attr]
                if bruta:
                    try:
                        resultado.append(json.loads(bruta))
                    except ValueError:
                        resultado.append({"error": {"message": "resposta não é JSON"}})

            fio = threading.Thread(target=ler, daemon=True)
            fio.start()
            fio.join(prazo_s)
            if fio.is_alive() or not resultado:
                raise ErroMcp("o servidor MCP não respondeu a tempo")
            return resultado[0]

    def notificar(self, mensagem: Mapping[str, Any]) -> None:
        with self._lock:
            processo = self._subir()
            assert processo.stdin is not None
            try:
                processo.stdin.write((json.dumps(mensagem, ensure_ascii=False) + "\n").encode())
                processo.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def fechar(self) -> None:
        if self._processo is not None and self._processo.poll() is None:
            self._processo.terminate()
            try:
                self._processo.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._processo.kill()
        self._processo = None


@dataclass(slots=True)
class ClienteMcp:
    """O aperto de mão, a lista de tools e a chamada. Sem estado entre servidores."""

    transporte: Transporte
    prazo_s: float = PRAZO_PADRAO_S
    _id: int = 0
    _pronto: bool = False

    def _proximo_id(self) -> int:
        self._id += 1
        return self._id

    def _chamar(self, metodo: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        pedido = {"jsonrpc": "2.0", "id": self._proximo_id(), "method": metodo}
        if params is not None:
            pedido["params"] = params
        resposta = self.transporte.pedir(pedido, prazo_s=self.prazo_s)
        if "error" in resposta:
            erro = resposta["error"] or {}
            raise ErroMcp(str(erro.get("message", "erro do servidor MCP"))[:300])
        resultado = resposta.get("result")
        return resultado if isinstance(resultado, dict) else {}

    def iniciar(self) -> None:
        if self._pronto:
            return
        self._chamar(
            "initialize",
            {
                "protocolVersion": VERSAO_DO_PROTOCOLO,
                "capabilities": {},
                "clientInfo": {"name": "jarvis", "version": "0.1"},
            },
        )
        self.transporte.notificar({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._pronto = True

    def listar_tools(self) -> list[dict[str, Any]]:
        self.iniciar()
        resultado = self._chamar("tools/list")
        tools = resultado.get("tools", [])
        return [t for t in tools if isinstance(t, dict)] if isinstance(tools, list) else []

    def chamar_tool(self, nome: str, argumentos: Mapping[str, Any]) -> dict[str, Any]:
        """Chama `tools/call` e devolve o resultado **como dado**. O servidor pode marcar
        `isError`: isso é o conteúdo da resposta, não uma ordem nem uma exceção nossa."""
        self.iniciar()
        return self._chamar("tools/call", {"name": nome, "arguments": dict(argumentos)})

    def fechar(self) -> None:
        self.transporte.fechar()
