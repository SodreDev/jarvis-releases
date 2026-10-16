"""Fontes de áudio: arquivo, sintética e dispositivo real (cartão F1-01).

A interface é a mesma para as três, e é ela que faz a F1 inteira ser testável sem
microfone: `audio-io` fala com `FonteDeAudio`, não com a placa de som.

As duas fontes de teste **ritmam** a entrega pelo `Relogio` injetado — `dormir(20 ms)` antes
de cada quadro. Com o relógio do sistema isso é tempo real; com o falso, é tempo virtual, e
a trilha de eventos sai idêntica em toda execução (aceite (b) e (c) do cartão).
"""

from __future__ import annotations

import wave
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from jarvis.audio_io.ambiente import proibir_dispositivo_em_ci
from jarvis.audio_io.erros import DispositivoIndisponivel, FormatoNaoSuportado
from jarvis.audio_io.quadro import (
    BYTES_POR_AMOSTRA,
    BYTES_POR_QUADRO,
    CANAIS,
    MS_POR_QUADRO,
    TAXA_PADRAO,
    Quadro,
)
from jarvis.audio_io.sintese import ROTEIRO_PADRAO, Trecho, gerar
from jarvis.relogio import Relogio

SEGUNDOS_POR_QUADRO = MS_POR_QUADRO / 1000.0


@runtime_checkable
class FonteDeAudio(Protocol):
    """De onde vêm os quadros de 20 ms. Implementação não decide turno nem fala com LLM."""

    device_id: str
    taxa: int

    def abrir(self) -> None:
        """Prepara a fonte. Recusa aqui o que não dá para entregar (formato, CI, driver)."""
        ...

    def quadros(self) -> Iterator[Quadro]:
        """Quadros de 20 ms, em ordem, com o carimbo do relógio injetado."""
        ...

    def fechar(self) -> None: ...


def _ler_wav(caminho: Path) -> tuple[bytes, int]:
    """PCM16 mono 16 kHz inteiro, ou recusa explicando o que estava errado."""
    with wave.open(str(caminho), "rb") as arquivo:
        canais = arquivo.getnchannels()
        largura = arquivo.getsampwidth()
        taxa = arquivo.getframerate()
        if canais != CANAIS or largura != BYTES_POR_AMOSTRA or taxa != TAXA_PADRAO:
            raise FormatoNaoSuportado(
                f"{caminho.name}: {canais} canal(is), {largura * 8} bits, {taxa} Hz; "
                f"o contrato do caminho de captura é {CANAIS} canal, "
                f"{BYTES_POR_AMOSTRA * 8} bits, {TAXA_PADRAO} Hz"
            )
        return arquivo.readframes(arquivo.getnframes()), taxa


@dataclass(slots=True)
class FonteDeArquivo:
    """Lê um WAV do corpus e entrega em quadros de 20 ms (o último, completado com zeros)."""

    caminho: Path
    relogio: Relogio
    device_id: str = ""
    taxa: int = TAXA_PADRAO
    limite_quadros: int | None = None
    _amostras: bytes = field(default=b"", repr=False)

    def __post_init__(self) -> None:
        if not self.device_id:
            self.device_id = f"arquivo:{self.caminho.name}"

    def abrir(self) -> None:
        self._amostras, self.taxa = _ler_wav(self.caminho)

    def quadros(self) -> Iterator[Quadro]:
        for indice, inicio in enumerate(range(0, len(self._amostras), BYTES_POR_QUADRO)):
            if self.limite_quadros is not None and indice >= self.limite_quadros:
                return
            pedaco = self._amostras[inicio : inicio + BYTES_POR_QUADRO]
            if len(pedaco) < BYTES_POR_QUADRO:
                pedaco += bytes(BYTES_POR_QUADRO - len(pedaco))
            self.relogio.dormir(SEGUNDOS_POR_QUADRO)
            yield Quadro(
                indice=indice, amostras=pedaco, ts_mono_ns=self.relogio.mono_ns(), taxa=self.taxa
            )

    def fechar(self) -> None:
        self._amostras = b""


@dataclass(slots=True)
class FonteSintetica:
    """Gera o roteiro na abertura (determinístico pela semente) e entrega em quadros."""

    relogio: Relogio
    semente: int = 0
    roteiro: Sequence[Trecho] = ROTEIRO_PADRAO
    device_id: str = ""
    taxa: int = TAXA_PADRAO
    _amostras: bytes = field(default=b"", repr=False)

    def __post_init__(self) -> None:
        if not self.device_id:
            self.device_id = f"sintetico:{self.semente}"

    def abrir(self) -> None:
        self._amostras = gerar(self.roteiro, semente=self.semente, taxa=self.taxa)

    def amostras(self) -> bytes:
        """O sinal inteiro — usado por quem precisa da referência (eco, F1-04)."""
        return self._amostras

    def quadros(self) -> Iterator[Quadro]:
        for indice, inicio in enumerate(range(0, len(self._amostras), BYTES_POR_QUADRO)):
            pedaco = self._amostras[inicio : inicio + BYTES_POR_QUADRO]
            if len(pedaco) < BYTES_POR_QUADRO:
                pedaco += bytes(BYTES_POR_QUADRO - len(pedaco))
            self.relogio.dormir(SEGUNDOS_POR_QUADRO)
            yield Quadro(
                indice=indice, amostras=pedaco, ts_mono_ns=self.relogio.mono_ns(), taxa=self.taxa
            )

    def fechar(self) -> None:
        self._amostras = b""


@dataclass(slots=True)
class FonteDeDispositivo:
    """Captura real, pelo backend de `jarvis.audio_io.dispositivo` (sounddevice/PortAudio).

    **Não verificado:** nenhum dispositivo real foi aberto **nesta máquina** — não há placa de
    som aqui, e o PortAudio nem está instalado. O código existe, tem a recusa separada por
    motivo (extra ausente × biblioteca do sistema ausente) e só o microfone do dono fecha o
    caminho (F1-16). Até lá, "funciona" é afirmação dele, não nossa.

    A ponte é fina de propósito: o que o `audio-io` conhece continua sendo `FonteDeAudio`, e
    quem abre a placa é um módulo que só existe com o extra instalado.
    """

    relogio: Relogio
    device_id: str = "dispositivo:padrao"
    taxa: int = TAXA_PADRAO
    ambiente: Mapping[str, str] | None = None
    dispositivo: int | str | None = None
    """Índice ou nome, como o `--diagnostico` lista. `None` = o padrão do sistema."""
    _captura: object | None = field(default=None, repr=False)

    def abrir(self) -> None:
        from jarvis.audio_io.dispositivo import CapturaDoDispositivo

        proibir_dispositivo_em_ci(self.ambiente)
        captura = CapturaDoDispositivo(
            relogio=self.relogio,
            taxa=self.taxa,
            dispositivo=self.dispositivo,
            ambiente=self.ambiente,
        )
        captura.abrir()
        self.device_id = captura.device_id
        self._captura = captura

    def quadros(self) -> Iterator[Quadro]:
        from jarvis.audio_io.dispositivo import CapturaDoDispositivo

        if not isinstance(self._captura, CapturaDoDispositivo):
            raise DispositivoIndisponivel("fonte de dispositivo não foi aberta")
        yield from self._captura.quadros()

    def fechar(self) -> None:
        from jarvis.audio_io.dispositivo import CapturaDoDispositivo

        if isinstance(self._captura, CapturaDoDispositivo):
            self._captura.fechar()
        self._captura = None
