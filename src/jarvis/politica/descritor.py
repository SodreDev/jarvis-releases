"""Abrir sob a raiz **por descritor**, não por string (SPEC §5.5; cartão F0-06).

A falha a evitar é TOCTOU: checar o caminho e depois abrir permite trocar um componente por
link simbólico no meio. Por isso a raiz é aberta **uma vez**, tudo acontece relativo a esse
descritor e a decisão vale sobre o objeto aberto, com identidade conferida.

Linux: `openat2` com `RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS |
RESOLVE_NO_XDEV`; quando a chamada não existe (kernel < 5.6), a travessia é componente a
componente com `O_NOFOLLOW` e `dir_fd`, conferindo o device a cada passo — mais lenta, mesma
garantia contra link simbólico e contra ponto de montagem.

Windows: handle com `FILE_FLAG_OPEN_REPARSE_POINT` + `GetFinalPathNameByHandleW`, conferindo
o prefixo da raiz e a identidade (volume + índice do arquivo). **Escrito e revisado, nunca
executado** — esta máquina é Linux (ver docs/notas-executor-F0.md).
"""

from __future__ import annotations

import contextlib
import ctypes
import errno
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Self

RESOLVE_NO_XDEV: Final = 0x01
RESOLVE_NO_MAGICLINKS: Final = 0x02
RESOLVE_NO_SYMLINKS: Final = 0x04
RESOLVE_BENEATH: Final = 0x08
SYS_OPENAT2: Final = 437

RESOLVE_DA_POLITICA: Final = (
    RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS | RESOLVE_NO_XDEV
)

FILE_FLAG_BACKUP_SEMANTICS: Final = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT: Final = 0x00200000
FILE_SHARE_READ: Final = 0x00000001
GENERIC_READ: Final = 0x80000000
OPEN_EXISTING: Final = 3


class AberturaRecusada(OSError):
    """Caminho recusado na abertura: fora da raiz, link simbólico, hardlink ou raiz trocada."""


@dataclass(frozen=True, slots=True)
class Identidade:
    """Identidade do objeto aberto: `device:inode` no POSIX, `volume:file_id` no Windows."""

    device: int
    inode: int

    def __str__(self) -> str:
        return f"{self.device}:{self.inode}"


@dataclass(slots=True)
class Aberto:
    """Objeto aberto sob a raiz. Quem fecha é quem abriu."""

    fd: int
    identidade: Identidade
    relativo: str
    nlink: int

    def fechar(self) -> None:
        with contextlib.suppress(OSError):
            os.close(self.fd)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()


class _OpenHow(ctypes.Structure):
    _fields_ = (
        ("flags", ctypes.c_uint64),
        ("mode", ctypes.c_uint64),
        ("resolve", ctypes.c_uint64),
    )


_LIBC: ctypes.CDLL | None = None


def _libc() -> ctypes.CDLL | None:
    global _LIBC
    if _LIBC is None and sys.platform != "win32":
        try:
            _LIBC = ctypes.CDLL(None, use_errno=True)
        except OSError:  # pragma: no cover - sistema sem libc carregável
            return None
    return _LIBC


def openat2_disponivel() -> bool:
    """`openat2` existe neste kernel? (Linux 5.6+; sem ele a travessia é por componente.)"""
    if sys.platform != "linux":
        return False
    libc = _libc()
    if libc is None:
        return False
    try:
        with abrir_raiz(Path.cwd()) as raiz:
            return raiz._abrir_openat2(".", escrever=False, diretorio=True) is not None
    except (AberturaRecusada, OSError):
        return False


@dataclass(slots=True)
class RaizAberta:
    """Raiz autorizada, aberta uma vez. Toda abertura é relativa a este descritor."""

    caminho: Path
    fd: int
    identidade: Identidade
    forcar_fallback: bool = False
    """Liga a travessia componente a componente mesmo onde `openat2` existe (para o teste)."""

    def fechar(self) -> None:
        with contextlib.suppress(OSError):
            os.close(self.fd)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.fechar()

    # --- conferência de identidade ------------------------------------------------
    def ainda_e_a_mesma(self) -> bool:
        """O caminho da raiz ainda aponta para o objeto que foi autorizado?

        Pega raiz renomeada, apagada e ponto de montagem trocado: o descritor continua
        válido (aponta para o inode antigo), mas o caminho passou a ser outra coisa.
        """
        try:
            atual = self.caminho.stat()
        except OSError:
            return False
        return Identidade(atual.st_dev, atual.st_ino) == self.identidade

    # --- abertura -----------------------------------------------------------------
    def abrir(
        self,
        relativo: str,
        *,
        escrever: bool = False,
        diretorio: bool = False,
        permitir_hardlink: bool = False,
    ) -> Aberto:
        """Abre `relativo` sob a raiz, ou recusa. `relativo` já vem canonicalizado."""
        if not self.ainda_e_a_mesma():
            raise AberturaRecusada(f"raiz {self.caminho} não é mais o objeto autorizado")
        if relativo.startswith(("/", "\\")) or ".." in Path(relativo).parts:
            raise AberturaRecusada(f"caminho não é relativo à raiz: {relativo!r}")
        alvo = relativo.strip("/") or "."

        fd = None if self.forcar_fallback else self._abrir_openat2(alvo, escrever, diretorio)
        if fd is None:
            fd = self._abrir_componente_a_componente(alvo, escrever, diretorio)

        info = os.fstat(fd)
        identidade = Identidade(info.st_dev, info.st_ino)
        if identidade.device != self.identidade.device:
            os.close(fd)
            raise AberturaRecusada(f"{relativo!r} está em outro sistema de arquivos")
        nlink = info.st_nlink
        if not permitir_hardlink and not diretorio and nlink > 1:
            os.close(fd)
            raise AberturaRecusada(
                f"{relativo!r} tem {nlink} nomes (hardlink): o mesmo arquivo pode estar fora "
                "da raiz, e caminho não prova conteúdo"
            )
        return Aberto(fd=fd, identidade=identidade, relativo=alvo, nlink=nlink)

    def _abrir_openat2(self, alvo: str, escrever: bool, diretorio: bool) -> int | None:
        libc = _libc()
        if libc is None or sys.platform != "linux":
            return None
        flags = os.O_RDWR if escrever else os.O_RDONLY
        if diretorio:
            flags = os.O_RDONLY | os.O_DIRECTORY
        how = _OpenHow(flags=flags | os.O_CLOEXEC, mode=0, resolve=RESOLVE_DA_POLITICA)
        ctypes.set_errno(0)
        fd = libc.syscall(
            ctypes.c_long(SYS_OPENAT2),
            ctypes.c_int(self.fd),
            alvo.encode("utf-8"),
            ctypes.byref(how),
            ctypes.c_size_t(ctypes.sizeof(how)),
        )
        if fd >= 0:
            return int(fd)
        erro = ctypes.get_errno()
        if erro in (errno.ENOSYS, errno.EINVAL, errno.EPERM):
            return None  # kernel sem openat2 (ou bloqueado por seccomp): usa o outro caminho
        raise AberturaRecusada(f"{alvo!r}: {os.strerror(erro)} (openat2)")

    def _abrir_componente_a_componente(self, alvo: str, escrever: bool, diretorio: bool) -> int:
        """Travessia POSIX com `O_NOFOLLOW` e `dir_fd`: link simbólico falha, não escapa."""
        partes = [p for p in Path(alvo).parts if p not in (".", "")]
        atual = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=self.fd)
        try:
            for i, parte in enumerate(partes):
                ultimo = i == len(partes) - 1
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
                if not ultimo or diretorio:
                    flags |= os.O_DIRECTORY
                elif escrever:
                    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
                try:
                    proximo = os.open(parte, flags, dir_fd=atual)
                except OSError as erro:
                    raise AberturaRecusada(f"{alvo!r} em {parte!r}: {erro.strerror}") from erro
                info = os.fstat(proximo)
                if info.st_dev != self.identidade.device:
                    os.close(proximo)
                    raise AberturaRecusada(f"{parte!r} atravessa ponto de montagem")
                os.close(atual)
                atual = proximo
            return atual
        except BaseException:
            os.close(atual)
            raise


def abrir_raiz(caminho: Path) -> RaizAberta:
    """Abre a raiz uma vez e guarda a identidade dela (§5.5: a raiz é aberta no grant)."""
    if sys.platform == "win32":  # pragma: no cover - não executado nesta máquina
        return _abrir_raiz_windows(caminho)
    try:
        fd = os.open(caminho, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError as erro:
        raise AberturaRecusada(f"raiz {caminho} não abriu: {erro.strerror}") from erro
    info = os.fstat(fd)
    return RaizAberta(caminho=caminho, fd=fd, identidade=Identidade(info.st_dev, info.st_ino))


def _abrir_raiz_windows(caminho: Path) -> RaizAberta:  # pragma: no cover - ver docstring
    """Raiz no Windows: handle sem seguir reparse point, identidade por volume + file id.

    **Não executado nesta máquina.** O `fd` devolvido é o do `os.open` com
    `O_NOFOLLOW` indisponível no Windows, então a garantia real vem da conferência de
    `GetFinalPathNameByHandleW` em `caminho_final_do_handle`, aplicada em cada abertura.
    """
    fd = os.open(caminho, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    info = os.fstat(fd)
    return RaizAberta(caminho=caminho, fd=fd, identidade=Identidade(info.st_dev, info.st_ino))


def caminho_final_do_handle(caminho: Path) -> str:  # pragma: no cover - só Windows
    """`GetFinalPathNameByHandleW`: o caminho real por trás de junções e links do Windows."""
    if sys.platform != "win32":
        raise AberturaRecusada("GetFinalPathNameByHandleW só existe no Windows")
    # mypy analisa com a plataforma desta máquina (Linux) e vê o resto como inalcançável.
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[unreachable]
    handle = kernel32.CreateFileW(
        str(caminho),
        GENERIC_READ,
        FILE_SHARE_READ,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
        None,
    )
    if handle == -1:
        raise AberturaRecusada(f"{caminho}: erro {ctypes.get_last_error()} em CreateFileW")
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        tamanho = kernel32.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if tamanho == 0:
            raise AberturaRecusada(
                f"{caminho}: erro {ctypes.get_last_error()} em GetFinalPathNameByHandleW"
            )
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)
