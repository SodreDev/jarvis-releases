"""Um servidor de TTS falso, com rotas por caminho, em porta efêmera de `127.0.0.1`.

O `servidor_falso.ServicoFalso` responde o mesmo roteiro a qualquer caminho; aqui o endpoint
configurável precisa de rotas diferentes ao mesmo tempo (síntese, stream, vozes, um 404 no stream,
um 302). Nada de rede de verdade: só `127.0.0.1`, porta escolhida pelo sistema.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Final, Self

ESPERA_DE_PARADA_S: Final = 5.0


@dataclass
class Rota:
    status: int = 200
    corpo: bytes = b""
    tipo: str = "application/octet-stream"
    pedacos: int = 1
    pausa_s: float = 0.0
    atraso_s: float = 0.0
    chunked: bool = False
    cabecalhos: dict[str, str] = field(default_factory=dict)


@dataclass
class PedidoVisto:
    metodo: str
    caminho: str
    cabecalhos: dict[str, str]
    corpo: bytes

    def cabecalho(self, nome: str) -> str:
        return next((v for k, v in self.cabecalhos.items() if k.lower() == nome.lower()), "")


@dataclass
class EndpointFalso:
    rotas: dict[str, Rota] = field(default_factory=dict)
    pedidos: list[PedidoVisto] = field(default_factory=list)
    _servidor: ThreadingHTTPServer | None = field(default=None, repr=False)
    _fio: threading.Thread | None = field(default=None, repr=False)

    @property
    def base(self) -> str:
        assert self._servidor is not None
        return f"http://127.0.0.1:{self._servidor.server_address[1]}"

    @property
    def porta(self) -> int:
        assert self._servidor is not None
        return int(self._servidor.server_address[1])

    def de(self, caminho: str) -> list[PedidoVisto]:
        return [p for p in self.pedidos if p.caminho.split("?")[0] == caminho]

    def __enter__(self) -> Self:
        dono = self

        class Tratador(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _responder(self, metodo: str) -> None:
                tamanho = int(self.headers.get("Content-Length", "0") or 0)
                corpo = self.rfile.read(tamanho) if tamanho else b""
                dono.pedidos.append(
                    PedidoVisto(metodo, self.path, dict(self.headers.items()), corpo)
                )
                rota = dono.rotas.get(self.path.split("?")[0], Rota(status=404, corpo=b"nada"))
                if rota.atraso_s:
                    time.sleep(rota.atraso_s)
                self.send_response(rota.status)
                self.send_header("Content-Type", rota.tipo)
                for nome, valor in rota.cabecalhos.items():
                    self.send_header(nome, valor)
                if rota.chunked:
                    self.send_header("Transfer-Encoding", "chunked")
                else:
                    self.send_header("Content-Length", str(len(rota.corpo)))
                self.end_headers()
                passo = max(1, len(rota.corpo) // max(1, rota.pedacos))
                try:
                    for inicio in range(0, len(rota.corpo), passo):
                        pedaco = rota.corpo[inicio : inicio + passo]
                        if rota.chunked:
                            self.wfile.write(f"{len(pedaco):x}\r\n".encode() + pedaco + b"\r\n")
                        else:
                            self.wfile.write(pedaco)
                        self.wfile.flush()
                        if rota.pausa_s:
                            time.sleep(rota.pausa_s)
                    if rota.chunked:
                        self.wfile.write(b"0\r\n\r\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return  # o cliente desistiu no meio: é o que o teste de cancelamento provoca

            def do_POST(self) -> None:
                self._responder("POST")

            def do_PUT(self) -> None:
                self._responder("PUT")

            def do_GET(self) -> None:
                self._responder("GET")

            def log_message(self, formato: str, *args: object) -> None:
                """Silêncio: o teste de vazamento de chave olha a saída."""

        self._servidor = ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
        self._servidor.daemon_threads = True
        self._fio = threading.Thread(target=self._servidor.serve_forever, daemon=True)
        self._fio.start()
        return self

    def __exit__(
        self,
        tipo: type[BaseException] | None,
        erro: BaseException | None,
        pilha: TracebackType | None,
    ) -> None:
        if self._servidor is not None:
            self._servidor.shutdown()
            self._servidor.server_close()
        if self._fio is not None:
            self._fio.join(timeout=ESPERA_DE_PARADA_S)
            assert not self._fio.is_alive(), "o servidor falso não parou"
