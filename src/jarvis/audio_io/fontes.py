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
    """Captura real. Só fora do CI, e hoje só existe como adaptador declarado.

    **Não verificado:** nenhum dispositivo real foi aberto por este código. O backend real
    (PipeWire/WASAPI por meio de uma biblioteca permissiva) entra com o microfone do dono,
    nos cartões F1-13 e F1-16. Até lá, `abrir` recusa com motivo em vez de devolver silêncio
    e fingir que capturou.
    """

    relogio: Relogio
    device_id: str = "dispositivo:padrao"
    taxa: int = TAXA_PADRAO
    ambiente: Mapping[str, str] | None = None

    def abrir(self) -> None:
        proibir_dispositivo_em_ci(self.ambiente)
        raise DispositivoIndisponivel(
            "backend de captura real não implementado neste cartão (F1-01): a captura de "
            "dispositivo entra com o hardware do dono (F1-13/F1-16). Use arquivo ou sintetico."
        )

    def quadros(self) -> Iterator[Quadro]:
        """Nunca entrega quadro: `abrir` recusa antes de chegar aqui."""
        raise DispositivoIndisponivel("fonte de dispositivo não foi aberta")

    def fechar(self) -> None:
        return None
