"""Tecla solta no terminal, sem bloquear o laço de áudio.

**O limite honesto, dito antes de tudo:** terminal não entrega evento de *tecla solta*. O
`audio-io` sabe fazer PTT de verdade (segura a tecla, abre a fonte; solta, fecha — F1-13),
porque lá quem manda é a `ui` gráfica escrevendo o arquivo de pedido. No terminal só dá para
saber que uma tecla **foi apertada**. Então o PTT daqui é **alternado**: barra abre, barra
fecha. É a mesma semântica do arquivo de pedido (`pressionado` verdadeiro ou falso), com a
diferença de que quem alterna é uma tecla e não um dedo segurando.

Isso está no `docs/COMO-TESTAR.md` com essas palavras, porque é diferença que o dono vai
sentir na primeira vez que usar.

A leitura é **não bloqueante**: o laço de voz não pode parar para esperar tecla, senão o
barge-in deixa de existir. No POSIX isso é `termios` em modo cru com `select`; no Windows é
`msvcrt.kbhit`. Fora de terminal (saída redirecionada, teste), o teclado "não tem tecla" em
vez de explodir.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

ESPACO: Final = " "
ESC: Final = "\x1b"
CTRL_C: Final = "\x03"


@runtime_checkable
class Teclado(Protocol):
    """ "Alguma tecla foi apertada desde a última vez?" — e nada mais que isso."""

    def tecla(self) -> str | None: ...


@dataclass(slots=True)
class TecladoFalso:
    """O teclado dos testes: uma fila de teclas, consumida uma por chamada."""

    teclas: list[str] = field(default_factory=list)
    lidas: list[str] = field(default_factory=list)

    def tecla(self) -> str | None:
        if not self.teclas:
            return None
        proxima = self.teclas.pop(0)
        self.lidas.append(proxima)
        return proxima


@dataclass(slots=True)
class TecladoMudo:
    """Nunca tem tecla. É o que o modo sem terminal usa, em vez de falhar."""

    def tecla(self) -> str | None:
        return None


@dataclass(slots=True)
class TecladoDoTerminal:
    """Lê uma tecla do terminal sem bloquear. Precisa de `preparado()` em volta do laço."""

    entrada: object = field(default_factory=lambda: sys.stdin)

    def descritor(self) -> int | None:
        """O descritor do terminal, ou `None` quando a entrada não é um terminal."""
        try:
            descritor = self.entrada.fileno()  # type: ignore[attr-defined]
        except (AttributeError, OSError, ValueError):
            return None
        return int(descritor) if os.isatty(descritor) else None

    def tecla(self) -> str | None:
        if os.name == "nt":  # pragma: no cover — caminho do Windows, sem CI aqui
            # `msvcrt` só existe no Windows, e o mypy roda em Linux: o módulo é resolvido em
            # tempo de execução para o tipo não depender do sistema em que o CI está.
            import importlib

            msvcrt = importlib.import_module("msvcrt")
            if not msvcrt.kbhit():
                return None
            return str(msvcrt.getwch())
        import select

        descritor = self.descritor()
        if descritor is None:
            return None
        pronto, _, _ = select.select([descritor], [], [], 0)
        if not pronto:
            return None
        lido = os.read(descritor, 1)
        return lido.decode("utf-8", "replace") if lido else None


@contextmanager
def preparado(teclado: Teclado) -> Iterator[Teclado]:
    """Põe o terminal em modo cru enquanto o laço roda, e **sempre** devolve como estava.

    Sem isto, cada tecla só chegaria depois de um Enter — e o dono ia apertar a barra para
    interromper o Jarvis sem nada acontecer. O `finally` é obrigatório: um terminal deixado em
    modo cru é um terminal que o dono tem de fechar na mão.
    """
    if os.name == "nt" or not isinstance(teclado, TecladoDoTerminal):  # pragma: no cover
        yield teclado
        return
    import termios
    import tty

    descritor = teclado.descritor()
    if descritor is None:
        yield teclado
        return
    antes = termios.tcgetattr(descritor)
    try:
        tty.setcbreak(descritor)
        yield teclado
    finally:
        termios.tcsetattr(descritor, termios.TCSADRAIN, antes)


def teclado_do_ambiente(interativo: bool | None = None) -> Teclado:
    """O teclado real quando há terminal; o mudo quando não há (teste, saída redirecionada)."""
    if interativo is None:
        interativo = sys.stdin.isatty() if hasattr(sys.stdin, "isatty") else False
    return TecladoDoTerminal() if interativo else TecladoMudo()


TECLAS_DE_SAIDA: Final[Sequence[str]] = (ESC, CTRL_C, "q")
