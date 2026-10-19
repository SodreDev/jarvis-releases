"""Limite de taxa e interruptor de parada global da entrada virtual.

O limite impede rajada (loop do modelo, página que o induz): no máximo `maximo` ações a cada
`janela_s` segundos. O interruptor é do **dono**: qualquer um pode pará-lo (botão, atalho, ou o
arquivo `PARADA` na pasta da entrada — `touch` basta), mas **só ele solta** — nenhuma tool tem o
poder de `liberar`, e nada que o modelo escreva chega aqui.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Final

MAXIMO_PADRAO: Final = 40
JANELA_PADRAO_S: Final = 60.0
ARQUIVO_DE_PARADA: Final = "PARADA"


class LimiteDeTaxa:
    def __init__(
        self,
        maximo: int = MAXIMO_PADRAO,
        janela_s: float = JANELA_PADRAO_S,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._maximo = maximo
        self._janela_s = janela_s
        self._relogio = relogio
        self._instantes: deque[float] = deque()
        self._trava = threading.Lock()

    def tentar(self) -> float:
        """Registra uma ação e devolve 0, ou quantos segundos faltam para poder agir."""
        with self._trava:
            agora = self._relogio()
            while self._instantes and agora - self._instantes[0] >= self._janela_s:
                self._instantes.popleft()
            if len(self._instantes) >= self._maximo:
                return self._janela_s - (agora - self._instantes[0])
            self._instantes.append(agora)
            return 0.0


class Interruptor:
    def __init__(self, pasta: Path | None = None) -> None:
        self._parado = threading.Event()
        self._arquivo = pasta / ARQUIVO_DE_PARADA if pasta is not None else None
        self._ao_parar: list[Callable[[], None]] = []
        self.motivo = ""

    def ao_parar(self, chamada: Callable[[], None]) -> None:
        """Registra o que fazer na parada (fechar a sessão do portal, destruir o `uinput`)."""
        self._ao_parar.append(chamada)

    @property
    def parado(self) -> bool:
        if self._parado.is_set():
            return True
        if self._arquivo is not None and self._arquivo.exists():
            self.parar("arquivo PARADA na pasta da entrada")
            return True
        return False

    def parar(self, motivo: str = "o dono mandou parar") -> None:
        if not self._parado.is_set():
            self.motivo = motivo
            self._parado.set()
        for chamada in self._ao_parar:
            with contextlib.suppress(Exception):  # parar nunca falha por causa de um backend
                chamada()

    def liberar(self) -> None:
        """Só a janela do dono chama isto; nenhuma tool o alcança."""
        if self._arquivo is not None:
            self._arquivo.unlink(missing_ok=True)
        self._parado.clear()
        self.motivo = ""
