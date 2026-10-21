"""O host nativo: o que o navegador lança, e a única ponte entre a extensão e o Jarvis.

Lado do navegador, só `stdin`/`stdout` (quadros do Native Messaging). Lado do Jarvis, um socket
**Unix** em `$XDG_RUNTIME_DIR/jarvis/navegador/` (pasta 0700, socket 0600, par conferido por
`SO_PEERCRED`). Não existe soquete de rede aqui — o teste `test_sem_rede` confere o código.

O host não decide nada: valida o vocabulário (`protocolo`), espera a resposta da extensão com
prazo e devolve. Política, risco e confirmação do dono moram no Jarvis. O estado também: o service
worker da extensão dorme, e o host vive e morre com o navegador.

A extensão também fala por conta própria: quando o dono aperta PARAR (na faixa da página ou no
botão da barra), ela manda um **evento**. O host o valida e o escreve em quem assinou
(`eventos.assinar`): uma conexão que o Jarvis deixa aberta enquanto controla alguma aba.
"""

from __future__ import annotations

import contextlib
import os
import socket
import stat
import struct
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from jarvis.navegador.protocolo import (
    ASSINAR,
    ID_FIREFOX,
    LIMITE_DA_RESPOSTA,
    LIMITE_DO_PEDIDO,
    ORIGEM_CHROMIUM,
    PedidoDaPonte,
    PedidoInvalido,
    validar_evento,
    validar_pedido,
    validar_resposta,
)
from jarvis.navegador.quadro import Escritor, Leitor, QuadroInvalido, escrever_quadro, ler_quadro

PRAZO_S: Final = 25.0
MAXIMO_EM_VOO: Final = 8
MAXIMO_DE_ASSINANTES: Final = 4
"""Conexões que esperam eventos (o Jarvis controlando abas): cada uma ocupa uma vaga de conexão."""
PRAZO_PARA_RESPONDER_S: Final = 2.0
"""Ao fechar, quanto o host espera quem já foi acordado com o "navegador_fechado" escrever a
resposta antes de derrubar a conexão. Normalmente leva milissegundos; o teto só cobre um Jarvis
que parou de ler."""
SUBPASTA: Final = Path("jarvis") / "navegador"


def pasta_dos_sockets(ambiente: Mapping[str, str], uid: int) -> Path:
    """`$XDG_RUNTIME_DIR` (ou `/run/user/<uid>`) — nunca `/tmp`, que outros usuários enxergam."""
    base = ambiente.get("XDG_RUNTIME_DIR") or f"/run/user/{uid}"
    return Path(base) / SUBPASTA


def erro_da_ponte(identificador: str | None, codigo: str, mensagem: str) -> dict[str, Any]:
    return {"id": identificador, "ok": False, "error": {"codigo": codigo, "mensagem": mensagem}}


class _Espera:
    __slots__ = ("evento", "resposta")

    def __init__(self) -> None:
        self.evento = threading.Event()
        self.resposta: dict[str, Any] | None = None


class Ponte:
    """Leva o pedido ao navegador e espera a resposta de **mesmo id**, com prazo."""

    def __init__(
        self, para_o_navegador: Escritor, *, prazo_s: float = PRAZO_S, maximo: int = MAXIMO_EM_VOO
    ) -> None:
        self._saida = para_o_navegador
        self._prazo_s = prazo_s
        self._maximo = maximo
        self._trava = threading.Lock()
        self._escrita = threading.Lock()
        self._esperas: dict[str, _Espera] = {}
        self._fechada = False
        self._assinantes: list[Escritor] = []
        self._escrita_dos_eventos = threading.Lock()

    def pedir(self, pedido: PedidoDaPonte) -> dict[str, Any]:
        espera = _Espera()
        with self._trava:
            if self._fechada:
                return erro_da_ponte(pedido.id, "navegador_fechado", "o navegador foi fechado")
            if pedido.id in self._esperas:
                return erro_da_ponte(pedido.id, "pedido_repetido", "esse id já está em voo")
            if len(self._esperas) >= self._maximo:
                return erro_da_ponte(pedido.id, "ocupado", "pedidos demais em voo")
            self._esperas[pedido.id] = espera
        try:
            with self._escrita:
                escrever_quadro(self._saida, pedido.como_objeto(), LIMITE_DO_PEDIDO)
        except (OSError, ValueError):
            self._esquecer(pedido.id)
            return erro_da_ponte(pedido.id, "navegador_fechado", "não falei com o navegador")
        if not espera.evento.wait(self._prazo_s):
            self._esquecer(pedido.id)
            return erro_da_ponte(pedido.id, "tempo_esgotado", "a extensão não respondeu a tempo")
        self._esquecer(pedido.id)
        return espera.resposta or erro_da_ponte(pedido.id, "navegador_fechado", "sem resposta")

    def entregar(self, resposta: dict[str, Any]) -> None:
        """Uma resposta da extensão. Id que ninguém espera é descartado."""
        with self._trava:
            espera = self._esperas.get(str(resposta.get("id")))
        if espera is not None:
            espera.resposta = resposta
            espera.evento.set()

    def encerrar(self) -> None:
        """O navegador saiu: ninguém mais responde, e quem espera é avisado já."""
        with self._trava:
            self._fechada = True
            esperas = list(self._esperas.items())
            self._assinantes.clear()
        for identificador, espera in esperas:
            espera.resposta = erro_da_ponte(
                identificador, "navegador_fechado", "o navegador foi fechado"
            )
            espera.evento.set()

    def assinar(self, fluxo: Escritor) -> bool:
        """Quem quer os eventos da extensão (o PARAR do dono). Falso se já há assinantes demais."""
        with self._trava:
            if self._fechada or len(self._assinantes) >= MAXIMO_DE_ASSINANTES:
                return False
            self._assinantes.append(fluxo)
            return True

    def desassinar(self, fluxo: Escritor) -> None:
        with self._trava:
            if fluxo in self._assinantes:
                self._assinantes.remove(fluxo)

    def publicar(self, evento: dict[str, Any]) -> int:
        """Escreve o evento em cada assinante; quem não recebe sai da lista. Devolve quantos
        receberam."""
        with self._trava:
            assinantes = list(self._assinantes)
        entregues = 0
        for fluxo in assinantes:
            try:
                with self._escrita_dos_eventos:
                    escrever_quadro(fluxo, evento, LIMITE_DA_RESPOSTA)
                entregues += 1
            except (OSError, ValueError):
                self.desassinar(fluxo)
        return entregues

    def _esquecer(self, identificador: str) -> None:
        with self._trava:
            self._esperas.pop(identificador, None)


def _par_e_nosso(conexao: socket.socket, uid: int) -> bool:
    opcao = getattr(socket, "SO_PEERCRED", None)
    if opcao is None:  # sem SO_PEERCRED o que protege é a pasta 0700
        return True
    credencial = conexao.getsockopt(socket.SOL_SOCKET, opcao, struct.calcsize("3i"))
    _pid, uid_do_par, _gid = struct.unpack("3i", credencial)
    return bool(uid_do_par == uid)


def atender(
    conexao: socket.socket,
    ponte: Ponte,
    uid: int,
    prazo_s: float = PRAZO_S,
    ao_assinar: Callable[[socket.socket], None] | None = None,
) -> None:
    """Um pedido por conexão: ler, validar, levar ao navegador, devolver. A assinatura de eventos
    é a exceção: a conexão fica aberta, recebendo eventos, até o Jarvis fechá-la — e
    `ao_assinar` fica sabendo qual conexão virou assinatura (é a que precisa ser acordada quando
    o navegador sai)."""
    conexao.settimeout(prazo_s + 5)
    try:
        if not _par_e_nosso(conexao, uid):
            return
        with conexao.makefile("rwb") as fluxo:
            try:
                bruto = ler_quadro(fluxo, LIMITE_DO_PEDIDO)
                if bruto is None:
                    return
                pedido = validar_pedido(bruto)
                if pedido.method == ASSINAR:
                    if ao_assinar is not None:
                        ao_assinar(conexao)
                    _assinar(conexao, fluxo, pedido, ponte)
                    return
                resposta = ponte.pedir(pedido)
            except (QuadroInvalido, PedidoInvalido) as erro:
                resposta = erro_da_ponte(None, "pedido_invalido", str(erro))
            escrever_quadro(fluxo, resposta, LIMITE_DA_RESPOSTA)
    except (OSError, QuadroInvalido):
        return
    finally:
        with contextlib.suppress(OSError):
            conexao.close()


def _assinar(conexao: socket.socket, fluxo: Any, pedido: PedidoDaPonte, ponte: Ponte) -> None:
    if not ponte.assinar(fluxo):
        escrever_quadro(
            fluxo, erro_da_ponte(pedido.id, "ocupado", "assinantes demais"), LIMITE_DA_RESPOSTA
        )
        return
    try:
        escrever_quadro(
            fluxo, {"id": pedido.id, "ok": True, "result": {"assinado": True}}, LIMITE_DA_RESPOSTA
        )
        # Fica até o Jarvis fechar a conexão (ou o navegador sair e fechar o socket).
        conexao.settimeout(None)
        while conexao.recv(64):
            pass
    finally:
        ponte.desassinar(fluxo)


def _preparar_pasta(pasta: Path, uid: int) -> None:
    pasta.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    pasta.mkdir(mode=0o700, exist_ok=True)
    estado = pasta.lstat()
    if not stat.S_ISDIR(estado.st_mode) or estado.st_uid != uid or estado.st_mode & 0o077:
        raise PermissionError(f"{pasta} tem de ser uma pasta do dono, sem acesso a mais ninguém")


class Servidor:
    """O socket Unix onde o Jarvis bate. Fechar apaga o arquivo."""

    def __init__(self, caminho: Path, ponte: Ponte, uid: int) -> None:
        _preparar_pasta(caminho.parent, uid)
        self.caminho = caminho
        self._ponte = ponte
        self._uid = uid
        self._vagas = threading.BoundedSemaphore(MAXIMO_EM_VOO)
        self._trava_das_conexoes = threading.Lock()
        self._mudou = threading.Condition(self._trava_das_conexoes)
        self._conexoes: set[socket.socket] = set()
        self._assinaturas: set[socket.socket] = set()
        """As conexões que esperam eventos: só elas ficam presas no `recv` quando o navegador
        sai."""
        self._soquete = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        antes = os.umask(0o177)
        try:
            self._soquete.bind(str(caminho))
        finally:
            os.umask(antes)
        self._soquete.listen(MAXIMO_EM_VOO)
        self._fio = threading.Thread(target=self._aceitar, name="jarvis-host", daemon=True)

    def iniciar(self) -> None:
        self._fio.start()

    def _aceitar(self) -> None:
        while True:
            try:
                conexao, _ = self._soquete.accept()
            except OSError:
                return
            if not self._vagas.acquire(blocking=False):
                conexao.close()
                continue
            threading.Thread(target=self._atender, args=(conexao,), daemon=True).start()

    def _atender(self, conexao: socket.socket) -> None:
        with self._trava_das_conexoes:
            self._conexoes.add(conexao)
        try:
            atender(conexao, self._ponte, self._uid, ao_assinar=self._assinou)
        finally:
            with self._mudou:
                self._conexoes.discard(conexao)
                self._assinaturas.discard(conexao)
                self._mudou.notify_all()
            self._vagas.release()

    def _assinou(self, conexao: socket.socket) -> None:
        with self._trava_das_conexoes:
            self._assinaturas.add(conexao)

    def fechar(self, prazo_s: float = PRAZO_PARA_RESPONDER_S) -> None:
        """Para de aceitar, acorda quem espera eventos e deixa quem espera resposta terminar.

        Quem esperava a resposta de um pedido já foi acordado pela ponte (`Ponte.encerrar`) e está
        escrevendo o "navegador_fechado". Derrubar essa conexão junto com as assinaturas fazia o
        Jarvis ler "o host fechou sem responder" no lugar do motivo, sempre que o fio que atende
        demorava a rodar (achado com o `verificar.py` sob carga, 2026-10-21). Por isso só as
        assinaturas caem já; o resto tem `prazo_s` para responder e fechar sozinho.
        """
        with contextlib.suppress(OSError):
            self._soquete.close()
        with contextlib.suppress(OSError):
            self.caminho.unlink()
        with self._trava_das_conexoes:
            assinaturas = list(self._assinaturas)
        _derrubar(assinaturas)  # acorda quem espera eventos: o navegador saiu
        fim = time.monotonic() + prazo_s
        with self._mudou:
            while (resta := fim - time.monotonic()) > 0 and self._conexoes - self._assinaturas:
                self._mudou.wait(resta)
            abertas = list(self._conexoes)
        _derrubar(abertas)  # quem não respondeu no prazo (o Jarvis parou de ler)


def _derrubar(conexoes: Sequence[socket.socket]) -> None:
    for conexao in conexoes:
        with contextlib.suppress(OSError):
            conexao.shutdown(socket.SHUT_RDWR)


def familia_do_navegador(argumentos: Sequence[str]) -> str | None:
    """`chromium` ou `firefox`, conforme o argumento que o navegador passou — e **só** se for a
    nossa extensão. O navegador já filtra pelo manifesto do host; aqui é a segunda fechadura."""
    if ORIGEM_CHROMIUM in argumentos:
        return "chromium"
    if ID_FIREFOX in argumentos:
        return "firefox"
    return None


def principal(
    argumentos: Sequence[str],
    entrada: Leitor,
    saida: Escritor,
    ambiente: Mapping[str, str],
    uid: int | None = None,
    prazo_s: float = PRAZO_S,
) -> int:
    """O laço do host. Devolve o código de saída: 0 quando o navegador fecha o `stdin`."""
    familia = familia_do_navegador(argumentos)
    if familia is None:
        print("jarvis-native-host: origem que não é a extensão do Jarvis", file=sys.stderr)
        return 2
    dono = os.getuid() if uid is None else uid
    ponte = Ponte(saida, prazo_s=prazo_s)
    caminho = pasta_dos_sockets(ambiente, dono) / f"{familia}-{os.getpid()}.sock"
    try:
        servidor = Servidor(caminho, ponte, dono)
    except OSError as erro:  # PermissionError é OSError
        print(f"jarvis-native-host: sem socket do Jarvis: {erro}", file=sys.stderr)
        return 3
    servidor.iniciar()
    try:
        while True:
            try:
                quadro = ler_quadro(entrada, LIMITE_DA_RESPOSTA)
            except QuadroInvalido as erro:
                print(f"jarvis-native-host: {erro}", file=sys.stderr)
                break
            if quadro is None:
                break
            try:
                if "evento" in quadro:
                    ponte.publicar(validar_evento(quadro))
                else:
                    ponte.entregar(validar_resposta(quadro))
            except PedidoInvalido:
                continue
    finally:
        ponte.encerrar()
        servidor.fechar()
    return 0


def main() -> int:  # pragma: no cover — liga o processo real
    if sys.argv[1:2] in (["--instalar"], ["--remover"]):  # nunca é o que um navegador passa
        from jarvis.navegador.instalar import main as instalar

        return instalar()
    return principal(sys.argv[1:], sys.stdin.buffer, sys.stdout.buffer, os.environ)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
