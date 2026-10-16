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
import stat
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
ARQUIVO_ENDERECO: Final = "endereco-do-barramento.txt"
"""Onde o servidor anota o endereço quando ele não cabe na pasta de sessão (ver `endereco`)."""
PREFIXO_DA_PASTA_CURTA: Final = "jarvis-sock-"
TAMANHO_MAXIMO: Final = 4 * 1024 * 1024
"""Teto do quadro. Payload grande vai por referência (`payload_ref`), não pelo barramento."""


class ErroDeIPC(RuntimeError):
    """Conexão, handshake ou quadro inválido."""


LIMITE_SUN_PATH: Final = 100
"""`sockaddr_un.sun_path` tem ~108 bytes; acima disso o bind falha com nome longo demais."""


def _digest(raiz: Path) -> str:
    return hashlib.sha256(str(raiz.resolve()).encode("utf-8")).hexdigest()[:16]


def endereco(raiz: Path) -> tuple[str, str]:
    """Endereço e família do barramento **para quem conecta**.

    Linux: socket na pasta de execução, que já é 0700. Quando o caminho dela não cabe em
    `sun_path` (pasta temporária de teste, por exemplo), o socket mora numa pasta privada
    criada pelo servidor, e o endereço dela está anotado em `ARQUIVO_ENDERECO` na raiz —
    ler o ponteiro é o único jeito, porque o nome da pasta é **aleatório** de propósito
    (ver `criar_endereco`). Sem ponteiro, o barramento não subiu, e isso é erro, não palpite.
    Windows: named pipe com nome derivado da pasta, porque pipe não vive no sistema de arquivos.
    """
    if sys.platform == "win32":
        return rf"\\.\pipe\jarvis-{_digest(raiz)}", "AF_PIPE"
    caminho = raiz / ARQUIVO_SOCKET
    if len(str(caminho)) <= LIMITE_SUN_PATH:
        return str(caminho), "AF_UNIX"
    ponteiro = raiz / ARQUIVO_ENDERECO
    try:
        anotado = ponteiro.read_text(encoding="utf-8").strip()
    except OSError as erro:
        raise ErroDeIPC(
            f"barramento não iniciado: o caminho de {raiz} não cabe em sun_path e falta "
            f"{ponteiro.name} com o endereço da pasta privada"
        ) from erro
    if not anotado:
        raise ErroDeIPC(f"barramento não iniciado: {ponteiro.name} está vazio")
    return anotado, "AF_UNIX"


def criar_endereco(raiz: Path) -> tuple[str, str]:
    """Endereço do barramento **para quem escuta**, criando a pasta privada se precisar.

    Por que não `gettempdir()/jarvis-<hash do caminho>.sock`, que era o que estava aqui:

    * o nome era **previsível** — um usuário local calculava o hash e pré-criava o arquivo,
      e o `bind` do servidor falhava com `EADDRINUSE`: negação de serviço na subida;
    * o arquivo nascia **fora** de qualquer pasta 0700, então entre `unlink` e `bind` havia
      corrida na pasta temporária (que tem *sticky bit*, mas é escrita por todos), e entre
      `bind` e `chmod` o socket existia com a umask do processo (0022 por padrão).

    `mkdtemp` resolve as três coisas de uma vez: cria a pasta **atomicamente**, com nome
    aleatório e modo 0700 **independente da umask**. O socket nasce dentro dela, então a
    proteção é da pasta e não da janela de `chmod`; o `chmod 0600` do socket continua, como
    segunda linha. O endereço escolhido fica anotado na raiz para quem conecta (`endereco`).
    """
    if sys.platform == "win32":  # pragma: no cover - named pipe não tem caminho de arquivo
        return endereco(raiz)
    caminho = raiz / ARQUIVO_SOCKET
    if len(str(caminho)) <= LIMITE_SUN_PATH:
        return str(caminho), "AF_UNIX"
    ponteiro = raiz / ARQUIVO_ENDERECO
    anterior = _pasta_privada_reutilizavel(ponteiro)
    if anterior is not None:
        return str(anterior), "AF_UNIX"
    pasta = Path(tempfile.mkdtemp(prefix=PREFIXO_DA_PASTA_CURTA))
    alvo = pasta / ARQUIVO_SOCKET
    if len(str(alvo)) > LIMITE_SUN_PATH:  # pragma: no cover - TMPDIR exótico
        pasta.rmdir()
        raise ErroDeIPC(
            f"nem a pasta temporária cabe em sun_path ({len(str(alvo))} bytes): "
            "aponte TMPDIR para um caminho curto"
        )
    ponteiro.write_text(str(alvo), encoding="utf-8")
    if sys.platform != "win32":
        ponteiro.chmod(0o600)
    return str(alvo), "AF_UNIX"


def _pasta_privada_reutilizavel(ponteiro: Path) -> Path | None:
    """O desvio anotado ainda serve? Só se a pasta for nossa, 0700 e nossa dona.

    Reiniciar o `agentd` na mesma sessão tem de reaproveitar o endereço (os outros processos
    guardaram o ponteiro), mas reaproveitar o que outro usuário criou no lugar seria aceitar
    exatamente o ataque que o nome aleatório evita.
    """
    try:
        anotado = Path(ponteiro.read_text(encoding="utf-8").strip())
    except OSError:
        return None
    pasta = anotado.parent
    if anotado.name != ARQUIVO_SOCKET or not pasta.name.startswith(PREFIXO_DA_PASTA_CURTA):
        return None
    try:
        info = pasta.stat()
    except OSError:
        return None
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        return None
    return anotado


def remover_endereco(raiz: Path) -> None:
    """Desfaz o desvio: apaga os sockets da pasta privada, a pasta e o ponteiro.

    A pasta privada guarda o socket do barramento e o do canal de áudio (ADR-0015), que
    mora ao lado. Só os `.sock` de dentro dela são removidos, um por um, e só depois de
    `_pasta_privada_reutilizavel` confirmar que a pasta é nossa — nada de remoção recursiva.
    """
    ponteiro = raiz / ARQUIVO_ENDERECO
    anotado = _pasta_privada_reutilizavel(ponteiro)
    if anotado is not None:
        with suppress(OSError):
            for dentro in anotado.parent.iterdir():
                if dentro.is_socket() or dentro.suffix == ".sock":
                    dentro.unlink(missing_ok=True)
        with suppress(OSError):
            anotado.parent.rmdir()  # falha de propósito se sobrou algo que não é nosso
    with suppress(OSError):
        ponteiro.unlink(missing_ok=True)


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
        alvo, familia = criar_endereco(raiz)
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
        remover_endereco(self.raiz)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()


def conectar(raiz: Path, nome: str, *, tentativas: int = 50, espera: float = 0.1) -> Canal:
    """Conecta ao barramento e se registra. Espera o corretor subir, sem laço cego."""
    chave = ler_chave(raiz)
    ultimo: Exception | None = None
    for _ in range(tentativas):
        try:
            # O endereço é resolvido a cada tentativa: com raiz comprida ele vem do ponteiro
            # que o servidor escreve, e esperar por ele é a mesma espera de esperar o socket.
            alvo, familia = endereco(raiz)
            canal = Canal(Client(alvo, family=familia, authkey=chave), nome=nome)
        except (OSError, ErroDeIPC) as erro:
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
