"""Reserva: entrada virtual por um dispositivo `uinput` do kernel — **só se o dono a ligou**.

Quando serve: sessão X11 (o portal do Plasma não faz `RemoteDesktop` em X11) ou compositor sem
portal. Como é kernel, vale para qualquer sessão e **não pede consentimento a ninguém**: por isso é
desligada por padrão (`entrada_uinput`), exige que o **dono** dê acesso a `/dev/uinput` (regra de
udev/ACL ou grupo — o Jarvis nunca pede privilégio nem muda permissão) e o dispositivo criado leva o
nome «Jarvis (entrada virtual)», visível em `libinput list-devices`.

Implementação com a biblioteca padrão (`fcntl.ioctl` + `struct`): sem dependência nova, sem
licença nova. Os números dos `ioctl` saem da fórmula `_IOC` do kernel e os códigos de tecla de
`linux/input-event-codes.h` (conferidos no header desta máquina em 2026-10-18); a recomendação da
documentação do kernel (<https://docs.kernel.org/input/uinput.html>) é usar `UI_DEV_SETUP`, que é o
que se faz aqui. Texto digitado por posição de tecla é **dependente de layout**: o backend recusa o
que não tem a mesma posição em US e ABNT2 (ver `teclas.teclas_do_uinput`).

Limite conhecido: `uinput` só move **relativo** (REL_X/REL_Y), como o portal nesta fatia.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import struct
import threading
import time
from collections.abc import Callable
from typing import Final

from jarvis.entrada import teclas
from jarvis.entrada.porta import BOTOES, EntradaIndisponivel

CAMINHO_PADRAO: Final = "/dev/uinput"
NOME_DO_DISPOSITIVO: Final = b"Jarvis (entrada virtual)"
EV_SYN, EV_KEY, EV_REL = 0x00, 0x01, 0x02
SYN_REPORT: Final = 0
REL_X, REL_Y = 0x00, 0x01
BTN_DO_BOTAO: Final = {"esquerdo": 0x110, "direito": 0x111, "meio": 0x112}
BUS_VIRTUAL: Final = 0x06
PAUSA_S: Final = 0.008
PASSO_DO_PONTEIRO: Final = 50

_IOC_WRITE, _IOC_NONE = 1, 0


def _ioc(direcao: int, tipo: str, numero: int, tamanho: int) -> int:
    """`_IOC` do kernel: direção (2 bits), tamanho (14), tipo (8), número (8)."""
    return (direcao << 30) | (tamanho << 16) | (ord(tipo) << 8) | numero


TAMANHO_DO_SETUP: Final = struct.calcsize("=HHHH80sI")
UI_DEV_CREATE: Final = _ioc(_IOC_NONE, "U", 1, 0)
UI_DEV_DESTROY: Final = _ioc(_IOC_NONE, "U", 2, 0)
UI_DEV_SETUP: Final = _ioc(_IOC_WRITE, "U", 3, TAMANHO_DO_SETUP)
UI_SET_EVBIT: Final = _ioc(_IOC_WRITE, "U", 100, 4)
UI_SET_KEYBIT: Final = _ioc(_IOC_WRITE, "U", 101, 4)
UI_SET_RELBIT: Final = _ioc(_IOC_WRITE, "U", 102, 4)
FORMATO_DO_EVENTO: Final = "llHHi"
"""`struct input_event` com os tamanhos NATIVOS (sem `=`): `timeval` (2 longs), tipo, código, valor.
São 24 bytes em 64 bits, que é o que o kernel lê aqui."""


class Dispositivo:
    """A parte que toca o kernel. Os testes a trocam por um falso que grava `ioctl` e `write`."""

    def __init__(self, caminho: str = CAMINHO_PADRAO) -> None:
        self.caminho = caminho
        self._fd = -1

    def abrir(self) -> None:
        try:
            self._fd = os.open(self.caminho, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as erro:
            raise EntradaIndisponivel(
                f"sem acesso a {self.caminho} ({erro.strerror}): o dono precisa liberar o "
                "uinput para o seu usuário (regra de udev) antes de ligar a reserva"
            ) from None

    def ioctl(self, pedido: int, argumento: int | bytes = 0) -> None:
        fcntl.ioctl(self._fd, pedido, argumento)

    def escrever(self, dados: bytes) -> None:
        os.write(self._fd, dados)

    def fechar(self) -> None:
        if self._fd >= 0:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = -1


class EntradaPorUinput:
    nome = "uinput"

    def __init__(
        self,
        dispositivo: Dispositivo | None = None,
        *,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._dispositivo = dispositivo or Dispositivo()
        self._dormir = dormir
        self._trava = threading.RLock()
        self._criado = False

    def abrir(self) -> None:
        with self._trava:
            if self._criado:
                return
            d = self._dispositivo
            d.abrir()
            try:
                d.ioctl(UI_SET_EVBIT, EV_KEY)
                d.ioctl(UI_SET_EVBIT, EV_REL)
                d.ioctl(UI_SET_EVBIT, EV_SYN)
                for codigo in self._codigos_de_teclas():
                    d.ioctl(UI_SET_KEYBIT, codigo)
                for botao in BTN_DO_BOTAO.values():
                    d.ioctl(UI_SET_KEYBIT, botao)
                d.ioctl(UI_SET_RELBIT, REL_X)
                d.ioctl(UI_SET_RELBIT, REL_Y)
                setup = struct.pack(
                    "=HHHH80sI", BUS_VIRTUAL, 0x4A56, 0x0001, 1, NOME_DO_DISPOSITIVO, 0
                )
                d.ioctl(UI_DEV_SETUP, setup)
                d.ioctl(UI_DEV_CREATE)
            except OSError as erro:
                d.fechar()
                raise EntradaIndisponivel(f"o kernel recusou criar o dispositivo: {erro}") from None
            self._criado = True
            self._dormir(0.2)  # o desktop leva um instante para enxergar o dispositivo novo

    @staticmethod
    def _codigos_de_teclas() -> list[int]:
        codigos = {
            *teclas.CODIGO_DE_NOME.values(),
            *teclas.CODIGO_DO_MODIFICADOR.values(),
            *teclas.CODIGO_DE_LETRA.values(),
            *teclas.CODIGO_DE_DIGITO.values(),
            *teclas.CODIGO_DE_PONTUACAO.values(),
        }
        return sorted(codigos)

    def fechar(self) -> None:
        with self._trava:
            if self._criado:
                with contextlib.suppress(OSError):
                    self._dispositivo.ioctl(UI_DEV_DESTROY)
            self._dispositivo.fechar()
            self._criado = False

    # --- eventos --------------------------------------------------------------------------
    def _evento(self, tipo: int, codigo: int, valor: int) -> None:
        self._dispositivo.escrever(struct.pack(FORMATO_DO_EVENTO, 0, 0, tipo, codigo, valor))

    def _sincronizar(self) -> None:
        self._evento(EV_SYN, SYN_REPORT, 0)

    def _tecla(self, codigo: int, apertada: bool) -> None:
        self._evento(EV_KEY, codigo, 1 if apertada else 0)
        self._sincronizar()
        self._dormir(PAUSA_S)

    def mover(self, dx: int, dy: int) -> None:
        with self._trava:
            self.abrir()
            passos = max(1, -(-max(abs(dx), abs(dy)) // PASSO_DO_PONTEIRO))
            for i in range(passos):
                parte_x = dx * (i + 1) // passos - dx * i // passos
                parte_y = dy * (i + 1) // passos - dy * i // passos
                self._evento(EV_REL, REL_X, parte_x)
                self._evento(EV_REL, REL_Y, parte_y)
                self._sincronizar()
                self._dormir(PAUSA_S)

    def clicar(self, botao: str, vezes: int) -> None:
        if botao not in BOTOES:
            raise ValueError(f"botão {botao!r} desconhecido")
        with self._trava:
            self.abrir()
            for _ in range(vezes):
                self._tecla(BTN_DO_BOTAO[botao], True)
                self._tecla(BTN_DO_BOTAO[botao], False)
                self._dormir(PAUSA_S * 4)

    def digitar(self, texto: str) -> None:
        with self._trava:
            # Converte tudo antes de tocar no teclado: texto impossível não sai pela metade.
            sequencia = [teclas.teclas_do_uinput(c) for c in teclas.validar_texto(texto)]
            self.abrir()
            for codigo, com_shift in sequencia:
                if com_shift:
                    self._tecla(teclas.CODIGO_DO_MODIFICADOR["shift"], True)
                self._tecla(codigo, True)
                self._tecla(codigo, False)
                if com_shift:
                    self._tecla(teclas.CODIGO_DO_MODIFICADOR["shift"], False)

    def pressionar(self, modificadores: tuple[str, ...], tecla: str) -> None:
        with self._trava:
            self.abrir()
            apertados: list[int] = []
            try:
                for m in modificadores:
                    codigo = teclas.CODIGO_DO_MODIFICADOR[m]
                    self._tecla(codigo, True)
                    apertados.append(codigo)
                codigo_da_tecla = teclas.codigo_da_tecla(tecla)
                self._tecla(codigo_da_tecla, True)
                self._tecla(codigo_da_tecla, False)
            finally:  # nunca deixa modificador preso
                for codigo in reversed(apertados):
                    with contextlib.suppress(OSError):
                        self._tecla(codigo, False)
