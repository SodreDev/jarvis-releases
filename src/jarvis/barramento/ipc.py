"""IPC local autenticado entre os sete processos (SPEC §2, ADR-0007).

Três decisões que valem para os dois sistemas:

* **Endereço por sistema, não porta de rede.** Socket de domínio Unix em `AF_UNIX` no Linux
  (dentro de uma pasta só do dono, modo 0700) e named pipe `AF_PIPE` no Windows. Nada escuta
  em TCP: um barramento de desktop não precisa ser alcançável pela rede.
* **Autenticação por segredo de arquivo.** `multiprocessing.connection` faz desafio e resposta
  com HMAC a partir de uma `authkey`; a chave é gerada por sessão, gravada com permissão
  restrita e nunca viaja no `argv`.
* **JSON, nunca pickle.** `send`/`recv` do `multiprocessing` serializam com pickle, o que
  transforma qualquer processo comprometido em execução de código no vizinho. Aqui só se usa
  `send_bytes`/`recv_bytes` com JSON — o barramento carrega dado, não objeto.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass
from multiprocessing.connection import Client, Connection, Listener
from pathlib import Path
from typing import Any, Final, Self

ARQUIVO_CHAVE: Final = "authkey"
ARQUIVO_SOCKET: Final = "barramento.sock"
TAMANHO_MAXIMO: Final = 4 * 1024 * 1024
"""Teto do quadro. Payload grande vai por referência (`payload_ref`), não pelo barramento."""


class ErroDeIPC(RuntimeError):
    """Conexão, handshake ou quadro inválido."""


LIMITE_SUN_PATH: Final = 100
"""`sockaddr_un.sun_path` tem ~108 bytes; acima disso o bind falha com nome longo demais."""


def _digest(raiz: Path) -> str:
    return hashlib.sha256(str(raiz.resolve()).encode("utf-8")).hexdigest()[:16]


def endereco(raiz: Path) -> tuple[str, str]:
    """Endereço e família do barramento para esta máquina.

    Linux: socket na pasta de execução. Quando o caminho dela é comprido (pasta temporária
    de teste, por exemplo), o socket vai para a pasta temporária do sistema com nome derivado
    por hash — é o limite de `sun_path`, não escolha nossa.
    Windows: named pipe com nome derivado da pasta, porque pipe não vive no sistema de arquivos.
    """
    if sys.platform == "win32":
        return rf"\\.\pipe\jarvis-{_digest(raiz)}", "AF_PIPE"
    caminho = raiz / ARQUIVO_SOCKET
    if len(str(caminho)) > LIMITE_SUN_PATH:
        caminho = Path(tempfile.gettempdir()) / f"jarvis-{_digest(raiz)}.sock"
    return str(caminho), "AF_UNIX"


def preparar_raiz(raiz: Path) -> bytes:
    """Cria a pasta de execução e a chave da sessão. Devolve a chave."""
    raiz.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        raiz.chmod(0o700)
    arquivo = raiz / ARQUIVO_CHAVE
    if not arquivo.exists():
        arquivo.write_bytes(secrets.token_bytes(32))
        if sys.platform != "win32":
            arquivo.chmod(0o600)
    return arquivo.read_bytes()


def ler_chave(raiz: Path) -> bytes:
    arquivo = raiz / ARQUIVO_CHAVE
    if not arquivo.exists():
        raise ErroDeIPC(f"barramento não iniciado: falta {arquivo}")
    return arquivo.read_bytes()


@dataclass(slots=True)
class Canal:
    """Um lado da conversa. Só troca JSON."""

    conexao: Connection
    nome: str = "?"

    def enviar(self, mensagem: dict[str, Any]) -> None:
        dados = json.dumps(mensagem, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(dados) > TAMANHO_MAXIMO:
            raise ErroDeIPC(f"quadro de {len(dados)} bytes passa do teto de {TAMANHO_MAXIMO}")
        self.conexao.send_bytes(dados)

    def receber(self, timeout: float | None = None) -> dict[str, Any] | None:
        """Próxima mensagem, ou `None` se o tempo acabou ou o outro lado fechou."""
        if timeout is not None and not self.conexao.poll(timeout):
            return None
        try:
            dados = self.conexao.recv_bytes(maxlength=TAMANHO_MAXIMO)
        except (EOFError, OSError):
            return None
        mensagem: Any = json.loads(dados.decode("utf-8"))
        if not isinstance(mensagem, dict):
            raise ErroDeIPC(f"quadro não é objeto: {type(mensagem).__name__}")
        return mensagem

    def fechar(self) -> None:
        with suppress(OSError):
            self.conexao.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()


class ServidorDoBarramento:
    """Ponto de escuta do corretor (vive no `agentd`)."""

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz
        chave = preparar_raiz(raiz)
        alvo, familia = endereco(raiz)
        if familia == "AF_UNIX":
            Path(str(alvo)).unlink(missing_ok=True)
        self._listener = Listener(alvo, family=familia, authkey=chave)
        if familia == "AF_UNIX":
            Path(str(alvo)).chmod(0o600)
        (raiz / "pronto").write_text(str(os.getpid()), encoding="utf-8")

    def aceitar(self) -> Canal:
        return Canal(self._listener.accept())

    def fechar(self) -> None:
        with suppress(OSError):
            self._listener.close()
        (self.raiz / "pronto").unlink(missing_ok=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()


def conectar(raiz: Path, nome: str, *, tentativas: int = 50, espera: float = 0.1) -> Canal:
    """Conecta ao barramento e se registra. Espera o corretor subir, sem laço cego."""
    alvo, familia = endereco(raiz)
    chave = ler_chave(raiz)
    ultimo: Exception | None = None
    for _ in range(tentativas):
        try:
            canal = Canal(Client(alvo, family=familia, authkey=chave), nome=nome)
        except OSError as erro:
            ultimo = erro
            time.sleep(espera)
            continue
        canal.enviar({"registro": nome})
        return canal
    raise ErroDeIPC(f"{nome} não conseguiu conectar ao barramento em {raiz}: {ultimo}")


def quadros(canal: Canal, *, timeout: float | None = None) -> Iterator[dict[str, Any]]:
    """Itera as mensagens até o outro lado fechar (ou o tempo acabar)."""
    while True:
        mensagem = canal.receber(timeout=timeout)
        if mensagem is None:
            return
        yield mensagem
