"""Um serviço de nuvem falso, em porta efêmera, para o teste exercitar o caminho inteiro.

Por que servidor de verdade em vez de `urlopen` falsificado: o que precisa de prova aqui é o
**encanamento** — cabeçalho montado, corpo multipart aceito, resposta lida por pedaços,
cancelamento no meio do corpo, prazo nosso. Um duplo de `urlopen` provaria que o nosso código
chama o nosso código.

A porta é **efêmera** (`porta=0`, o sistema escolhe): nada de porta fixa que colide com outra
suíte, e nada de rede externa — o servidor só escuta em `127.0.0.1`.

O que ele registra (`pedidos`) é o que o teste inspeciona: caminho, cabeçalhos e corpo. É
também onde se confere que a chave chegou **no cabeçalho** e em lugar nenhum mais.
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
class Pedido:
    """Um pedido como o servidor o viu."""

    caminho: str
    cabecalhos: dict[str, str]
    corpo: bytes

    def cabecalho(self, nome: str) -> str:
        """Busca sem diferenciar maiúscula: o `urllib` manda `Xi-api-key` para `xi-api-key`,
        e um teste que compara a chave literal passaria a medir a capitalização do cliente."""
        procurado = nome.lower()
        for chave, valor in self.cabecalhos.items():
            if chave.lower() == procurado:
                return valor
        return ""

    def tem_cabecalho(self, nome: str) -> bool:
        return any(chave.lower() == nome.lower() for chave in self.cabecalhos)

    @property
    def autorizacao(self) -> str:
        return self.cabecalho("Authorization")

    def campo(self, nome: str) -> str:
        """O valor de um campo `multipart`, sem montar um analisador inteiro."""
        marca = f'name="{nome}"\r\n\r\n'.encode()
        inicio = self.corpo.find(marca)
        if inicio < 0:
            return ""
        inicio += len(marca)
        fim = self.corpo.find(b"\r\n--", inicio)
        return self.corpo[inicio:fim].decode("utf-8", "replace")


@dataclass
class Roteiro:
    """O que o servidor responde. Um roteiro por teste, não um servidor por caso."""

    status: int = 200
    corpo: bytes = b"{}"
    tipo: str = "application/json"
    pedacos: int = 1
    """Em quantos pedaços o corpo sai. >1 com `pausa_s` é o que deixa o cancelamento
    acontecer **no meio** do corpo, que é o caso que importa."""
    pausa_s: float = 0.0
    atraso_antes_do_cabecalho_s: float = 0.0
    """Atraso antes de responder: é assim que se estoura o prazo nosso sem depender da rede."""


@dataclass
class ServicoFalso:
    """Sobe num fio de execução, devolve a base (`http://127.0.0.1:porta`) e para no fim."""

    roteiro: Roteiro = field(default_factory=Roteiro)
    pedidos: list[Pedido] = field(default_factory=list)
    _servidor: ThreadingHTTPServer | None = field(default=None, repr=False)
    _fio: threading.Thread | None = field(default=None, repr=False)

    @property
    def base(self) -> str:
        assert self._servidor is not None
        return f"http://127.0.0.1:{self._servidor.server_address[1]}"

    def __enter__(self) -> Self:
        dono = self

        class Tratador(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # o nome é exigido pelo BaseHTTPRequestHandler
                tamanho = int(self.headers.get("Content-Length", "0"))
                corpo = self.rfile.read(tamanho) if tamanho else b""
                dono.pedidos.append(
                    Pedido(
                        caminho=self.path,
                        cabecalhos={chave: valor for chave, valor in self.headers.items()},
                        corpo=corpo,
                    )
                )
                roteiro = dono.roteiro
                if roteiro.atraso_antes_do_cabecalho_s:
                    time.sleep(roteiro.atraso_antes_do_cabecalho_s)
                self.send_response(roteiro.status)
                self.send_header("Content-Type", roteiro.tipo)
                self.send_header("Content-Length", str(len(roteiro.corpo)))
                self.end_headers()
                tamanho_do_pedaco = max(1, len(roteiro.corpo) // max(1, roteiro.pedacos))
                for inicio in range(0, len(roteiro.corpo), tamanho_do_pedaco):
                    try:
                        self.wfile.write(roteiro.corpo[inicio : inicio + tamanho_do_pedaco])
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        # O cliente desistiu no meio do corpo: é exatamente o que o teste de
                        # cancelamento provoca, e não é falha do servidor.
                        return
                    if roteiro.pausa_s:
                        time.sleep(roteiro.pausa_s)

            def log_message(self, formato: str, *args: object) -> None:
                """Silêncio: o log do `http.server` escreveria o pedido no stderr do teste —
                e o teste de vazamento de chave varre justamente o stderr."""

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
