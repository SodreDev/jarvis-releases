"""Conexão persistente com a nuvem (2026-10-21, ADR-0045: «precisa ser muito rápido»).

O `urlopen` abria DNS, TCP e TLS a cada lote de fala e a cada transcrição. Com um servidor
HTTP/1.1 de verdade, local (nada sai da máquina), prova-se: o segundo pedido reaproveita a conexão;
a leitura cancelada fecha a conexão (sobraria corpo em voo); a conexão que o servidor derrubou não é
reaproveitada (e nenhum POST é repetido); erro 4xx sobe como antes; e o `aquecer` abre a conexão
sem pedido nenhum, que o primeiro pedido então usa.
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from jarvis.voz.chaves import Chave
from jarvis.voz.nuvem import ClienteHttp, ConexoesPersistentes, Resposta


class _Servidor(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Tratador)
        self.conexoes = 0
        self.pedidos = 0
        self.fechar_depois = False

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"


class _Tratador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _Servidor

    def setup(self) -> None:
        super().setup()
        self.server.conexoes += 1

    def log_message(self, *_: object) -> None:
        return

    def do_POST(self) -> None:
        tamanho = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(tamanho)
        self.server.pedidos += 1
        if self.path.startswith("/erro"):
            corpo = b'{"erro": "nao"}'
            self.send_response(401)
        else:
            corpo = b"x" * (64 * 1024 if self.path.startswith("/grande") else 16)
            self.send_response(200)
        self.send_header("Content-Length", str(len(corpo)))
        if self.server.fechar_depois:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(corpo)


@pytest.fixture
def servidor() -> Iterator[_Servidor]:
    servidor = _Servidor()
    linha = threading.Thread(target=servidor.serve_forever, daemon=True)
    linha.start()
    try:
        yield servidor
    finally:
        servidor.shutdown()
        servidor.server_close()


CHAVE = Chave("TESTE_CHAVE", "valor-de-teste")


def _postar(cliente: ClienteHttp, caminho: str = "/fala", **extra: Any) -> Resposta:
    return cliente.postar(
        caminho, corpo=b"{}", tipo_do_corpo="application/json", chave=CHAVE, **extra
    )


def test_o_segundo_pedido_reaproveita_a_conexao(servidor: _Servidor) -> None:
    conexoes = ConexoesPersistentes()
    cliente = ClienteHttp(base=servidor.base, abrir=conexoes)

    primeira = _postar(cliente)
    segunda = _postar(cliente)

    assert primeira.corpo == b"x" * 16 and segunda.corpo == b"x" * 16
    assert servidor.pedidos == 2 and servidor.conexoes == 1
    assert (conexoes.abertas, conexoes.reaproveitadas) == (1, 1)
    conexoes.fechar()


def test_a_leitura_cancelada_fecha_a_conexao(servidor: _Servidor) -> None:
    conexoes = ConexoesPersistentes()
    cliente = ClienteHttp(base=servidor.base, abrir=conexoes)
    lidos = iter([False, True])  # deixa a primeira leitura, cancela na segunda

    cancelada = _postar(cliente, "/grande", cancelado=lambda: next(lidos, True))
    depois = _postar(cliente)

    assert cancelada.cancelada is True
    assert depois.corpo == b"x" * 16
    assert servidor.conexoes == 2, "a conexão com corpo em voo não volta para o pool"
    conexoes.fechar()


def test_a_conexao_que_o_servidor_derrubou_nao_e_reaproveitada(servidor: _Servidor) -> None:
    conexoes = ConexoesPersistentes()
    cliente = ClienteHttp(base=servidor.base, abrir=conexoes)
    servidor.fechar_depois = True

    _postar(cliente)
    _postar(cliente)

    assert servidor.pedidos == 2 and servidor.conexoes == 2, "nenhum POST repetido"
    assert conexoes.reaproveitadas == 0
    conexoes.fechar()


def test_conexao_parada_demais_e_fechada_em_vez_de_reaproveitada(servidor: _Servidor) -> None:
    agora = [0.0]
    conexoes = ConexoesPersistentes(ociosa_ate_s=30.0, relogio=lambda: agora[0])
    cliente = ClienteHttp(base=servidor.base, abrir=conexoes)

    _postar(cliente)
    agora[0] = 31.0
    _postar(cliente)

    assert servidor.conexoes == 2 and conexoes.reaproveitadas == 0
    conexoes.fechar()


def test_erro_do_servico_sobe_como_antes(servidor: _Servidor) -> None:
    conexoes = ConexoesPersistentes()
    pedido = urllib.request.Request(  # noqa: S310 — http do servidor local do teste
        f"{servidor.base}/erro", data=b"{}", method="POST"
    )

    with pytest.raises(urllib.error.HTTPError) as erro:
        conexoes(pedido, timeout=5.0)

    assert erro.value.code == 401 and b"nao" in erro.value.read()
    conexoes.fechar()


def test_aquecer_abre_a_conexao_sem_pedido_e_o_primeiro_pedido_a_usa(
    servidor: _Servidor,
) -> None:
    conexoes = ConexoesPersistentes()
    cliente = ClienteHttp(base=servidor.base, abrir=conexoes)

    assert cliente.aquecer() is True
    assert servidor.pedidos == 0, "aquecer não manda dado nenhum"
    _postar(cliente)

    assert servidor.conexoes == 1 and conexoes.reaproveitadas == 1
    conexoes.fechar()


def test_aquecer_sob_ci_continua_proibido_para_a_nuvem_de_verdade() -> None:
    cliente = ClienteHttp(base="https://api.groq.com/openai/v1", ambiente={"CI": "1"})
    with pytest.raises(Exception, match="CI"):
        cliente.aquecer()
