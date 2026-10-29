"""Um POST com a resposta em stream (SSE), cancelável e com prazo nosso (ADR-0025, ADR-0056).

O `ClienteHttp` da voz lê o corpo inteiro antes de devolver; um motor de conversa precisa de cada
linha quando ela chega. A leitura bloqueante fica num fio próprio, que entrega as linhas numa
fila; quem consome espera em fatias de `INTERVALO_DE_CONSULTA_S` olhando o cancelamento e o prazo.
No cancelamento, no prazo e quando quem consome desiste, o socket é **fechado** — o fio acorda
do `readline`, e o serviço vê a conexão cair (parar de ler não basta: ADR-0025, regra 2).

As regras da nuvem continuam as da ADR-0017: a chave vai só no cabeçalho, a base não local é
proibida sob `CI=1`, e o detalhe de erro passa por `redigir` antes de virar texto.
"""

from __future__ import annotations

import contextlib
import queue
import socket
import ssl
import threading
import time
from collections.abc import Generator, Iterable, Mapping
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from typing import Final
from urllib.parse import urlparse

from jarvis.s2.motor import INTERVALO_DE_CONSULTA_S
from jarvis.voz.chaves import Chave, redigir
from jarvis.voz.interface import Cancelado
from jarvis.voz.nuvem import (
    AGENTE_DO_USUARIO,
    STATUS_QUE_VIRAM_DEGRADACAO,
    ErroDoServico,
    ServicoRecusou,
    proibir_nuvem_real_em_ci,
)

LIMITE_DA_LINHA: Final = 1024 * 1024
"""Uma linha de SSE maior que isto não é evento de texto: é resposta estranha."""
LIMITE_DO_ERRO: Final = 2000


class StreamCancelado(Exception):
    """Quem pediu cancelou: a conexão já foi fechada."""


class StreamSemPrazo(Exception):
    """O prazo nosso acabou antes do fim: a conexão já foi fechada."""


@dataclass(frozen=True, slots=True)
class _Fim:
    erro: BaseException | None = None


def _conexao(url: str, prazo_s: float) -> tuple[HTTPConnection, str]:
    partes = urlparse(url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise ErroDoServico(f"esquema {partes.scheme!r} ou servidor vazio")
    caminho = partes.path or "/"
    if partes.query:
        caminho += "?" + partes.query
    if partes.scheme == "https":
        return (
            HTTPSConnection(
                partes.hostname,
                partes.port or 443,
                timeout=prazo_s,
                context=ssl.create_default_context(),
            ),
            caminho,
        )
    return HTTPConnection(partes.hostname, partes.port or 80, timeout=prazo_s), caminho


def _fechar(conexao: HTTPConnection) -> None:
    """Derruba o socket (acorda o fio que está no `readline`) e fecha a conexão."""
    sock = conexao.sock
    if sock is not None:
        with contextlib.suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)
    with contextlib.suppress(OSError):
        conexao.close()


def linhas(
    url: str,
    *,
    corpo: bytes,
    chave: Chave | None,
    cancelado: Cancelado,
    prazo_s: float,
    cabecalho_da_chave: str = "Authorization",
    prefixo_da_chave: str = "Bearer ",
    cabecalhos: Mapping[str, str] | None = None,
    ambiente: Mapping[str, str] | None = None,
) -> Generator[str, None, None]:
    """As linhas da resposta, na ordem, sem o fim de linha. Levanta `StreamCancelado`,
    `StreamSemPrazo`, `ServicoRecusou` (4xx: chave, modelo, plano) ou `ErroDoServico` (rede, 5xx,
    429). `chave` vazia = servidor sem autenticação (um roteador local)."""
    proibir_nuvem_real_em_ci(url, ambiente)
    if cancelado():
        raise StreamCancelado
    conexao, caminho = _conexao(url, prazo_s)
    fila: queue.Queue[str | _Fim] = queue.Queue()
    cabecalhos_do_pedido = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": AGENTE_DO_USUARIO,
        **(cabecalhos or {}),
    }
    if chave is not None:
        # A chave vai **no cabeçalho**: nunca na URL (fica em log de proxy), nunca no corpo.
        cabecalhos_do_pedido[cabecalho_da_chave] = f"{prefixo_da_chave}{chave.usar()}"
    segredos = [chave] if chave is not None else []

    def ler() -> None:
        try:
            conexao.request("POST", caminho, body=corpo, headers=cabecalhos_do_pedido)
            resposta = conexao.getresponse()
            if resposta.status >= 400:
                detalhe = redigir(
                    resposta.read(LIMITE_DO_ERRO).decode("utf-8", "replace"), segredos
                ).strip()
                status = resposta.status
                if status in STATUS_QUE_VIRAM_DEGRADACAO or status >= 500:
                    fila.put(_Fim(ErroDoServico(f"{status} do serviço: {detalhe}")))
                else:
                    fila.put(
                        _Fim(
                            ServicoRecusou(
                                f"o serviço recusou o pedido ({status}): {detalhe}. Isto não é "
                                "falta de rede — confira a chave, o plano e o modelo"
                            )
                        )
                    )
                return
            while True:
                bruta = resposta.readline(LIMITE_DA_LINHA)
                if not bruta:
                    break
                fila.put(bruta.decode("utf-8", "replace").rstrip("\r\n"))
            fila.put(_Fim())
        except (OSError, HTTPException, ValueError) as erro:
            texto = redigir(f"não deu para falar com o serviço: {erro}", segredos)
            fila.put(_Fim(ErroDoServico(texto)))

    fio = threading.Thread(target=ler, name="jarvis-stream", daemon=True)
    fio.start()
    limite = time.monotonic() + prazo_s
    try:
        while True:
            if cancelado():
                raise StreamCancelado
            if time.monotonic() > limite:
                raise StreamSemPrazo
            try:
                item = fila.get(timeout=INTERVALO_DE_CONSULTA_S)
            except queue.Empty:
                continue
            if isinstance(item, _Fim):
                if item.erro is not None:
                    raise item.erro
                return
            yield item
    finally:
        _fechar(conexao)


def eventos_sse(linhas_do_stream: Iterable[str]) -> Generator[str, None, None]:
    """Os `data:` de um stream SSE, um por evento (várias linhas `data:` se juntam com `\\n`).
    Comentário (`: OPENROUTER PROCESSING`) e outros campos são ignorados; `[DONE]` encerra."""
    dados: list[str] = []
    for linha in linhas_do_stream:
        if not linha:
            if dados:
                evento = "\n".join(dados)
                dados = []
                if evento == "[DONE]":
                    return
                yield evento
            continue
        if linha.startswith(":"):
            continue
        campo, _, valor = linha.partition(":")
        if campo == "data":
            dados.append(valor[1:] if valor.startswith(" ") else valor)
    if dados and "\n".join(dados) != "[DONE]":
        yield "\n".join(dados)


__all__ = ["StreamCancelado", "StreamSemPrazo", "eventos_sse", "linhas"]
