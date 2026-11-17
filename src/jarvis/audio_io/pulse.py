"""Gravar e tocar PCM num dispositivo nomeado do PipeWire/PulseAudio, por `parec` e `pacat`
(ADR-0074, fatia B): o ASR da chamada grava a fonte do outro lado e o microfone real; a voz do
Jarvis na chamada toca no sink da mistura (`jarvis_mix`) e, com fone, também na saída do dono.

Sem shell: `argv` fixo deste módulo, o dispositivo é um nome do servidor (validado). PCM s16le
mono a `TAXA_PADRAO`. Os dois **recusam sob CI** (`proibir_dispositivo_em_ci`): a suíte nunca
toca nem grava áudio do dono — os testes usam as interfaces com fakes. **Não provado na máquina
real.**"""

from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import IO, Final, Protocol

from jarvis.audio_io.ambiente import proibir_dispositivo_em_ci
from jarvis.audio_io.quadro import BYTES_POR_QUADRO, TAXA_PADRAO

NOME_DE_DISPOSITIVO: Final = re.compile(r"[A-Za-z0-9_.:@-]{1,200}")


class Gravador(Protocol):
    """Quadros de 20 ms de um dispositivo, até `fechar`."""

    def quadros(self, dispositivo: str) -> Iterator[bytes]: ...

    def fechar(self) -> None: ...


class Tocador(Protocol):
    """Toca PCM num dispositivo e volta quando acabou (ou quando `parar` cortou)."""

    def tocar(self, pcm: bytes, dispositivo: str) -> None: ...

    def parar(self) -> None: ...


def _dispositivo(nome: str) -> str:
    if not NOME_DE_DISPOSITIVO.fullmatch(nome):
        raise ValueError("nome de dispositivo fora do formato do servidor de áudio")
    return nome


def _programa(nome: str) -> str:
    caminho = shutil.which(nome)
    if caminho is None:
        raise FileNotFoundError(f"{nome} não está instalado (pacote pulseaudio-utils)")
    return caminho


@dataclass(slots=True)
class GravadorPorParec:
    taxa: int = TAXA_PADRAO
    _processo: subprocess.Popen[bytes] | None = None

    def quadros(self, dispositivo: str) -> Iterator[bytes]:
        proibir_dispositivo_em_ci()
        self._processo = subprocess.Popen(  # noqa: S603 — argv fixo, sem shell
            [
                _programa("parec"),
                f"--device={_dispositivo(dispositivo)}",
                "--format=s16le",
                f"--rate={self.taxa}",
                "--channels=1",
                "--raw",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        saida: IO[bytes] | None = self._processo.stdout
        if saida is None:
            return
        while True:
            bloco = saida.read(BYTES_POR_QUADRO)
            if len(bloco) < BYTES_POR_QUADRO:
                return
            yield bloco

    def fechar(self) -> None:
        if self._processo is not None:
            with contextlib.suppress(Exception):
                self._processo.terminate()
                self._processo.wait(timeout=2)
            self._processo = None


@dataclass(slots=True)
class TocadorPorPacat:
    taxa: int = TAXA_PADRAO
    _processos: list[subprocess.Popen[bytes]] = field(default_factory=list)
    _trava: threading.Lock = field(default_factory=threading.Lock)

    def tocar(self, pcm: bytes, dispositivo: str) -> None:
        proibir_dispositivo_em_ci()
        processo = subprocess.Popen(  # noqa: S603 — argv fixo, sem shell
            [
                _programa("pacat"),
                "--playback",
                f"--device={_dispositivo(dispositivo)}",
                "--format=s16le",
                f"--rate={self.taxa}",
                "--channels=1",
                "--raw",
            ],
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        with self._trava:
            self._processos.append(processo)
        try:
            with contextlib.suppress(BrokenPipeError):
                processo.communicate(pcm, timeout=120)
        finally:
            with self._trava:
                if processo in self._processos:
                    self._processos.remove(processo)

    def parar(self) -> None:
        with self._trava:
            vivos = list(self._processos)
        for processo in vivos:
            with contextlib.suppress(Exception):
                processo.terminate()


__all__ = ["Gravador", "GravadorPorParec", "Tocador", "TocadorPorPacat"]
