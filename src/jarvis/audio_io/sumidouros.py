"""Sumidouros de áudio: memória, arquivo e dispositivo real (cartão F1-01).

Quem conta `played_ms` conta **amostra consumida pelo sumidouro**, nunca amostra
enfileirada (§3.3, regra 2). Por isso o sumidouro é quem sabe quantas amostras saíram:
`amostras_consumidas` é a única fonte desse número, e os testes do F1-03 contam bytes aqui.

Neste cartão o sumidouro consome na hora. A fila com `epoch`, esvaziável no mesmo tick, é
o cartão F1-03 — e vai ser construída **em cima** desta interface, não no lugar dela.
"""

from __future__ import annotations

import wave
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from jarvis.audio_io.ambiente import proibir_dispositivo_em_ci
from jarvis.audio_io.erros import DispositivoIndisponivel
from jarvis.audio_io.quadro import BYTES_POR_AMOSTRA, CANAIS, TAXA_PADRAO


@runtime_checkable
class SumidouroDeAudio(Protocol):
    """Para onde vai o áudio que o assistente fala."""

    device_id: str
    taxa: int
    amostras_consumidas: int

    def abrir(self) -> None: ...

    def escrever(self, amostras: bytes) -> int:
        """Entrega bytes PCM16 e devolve quantas **amostras** foram consumidas."""
        ...

    def limpar(self) -> int:
        """Descarta o que ainda não saiu e devolve quantas amostras foram descartadas."""
        ...

    def fechar(self) -> None: ...


@dataclass(slots=True)
class SumidouroEmMemoria:
    """Guarda tudo o que saiu — é o que deixa o teste contar amostra em vez de confiar."""

    device_id: str = "memoria:0"
    taxa: int = TAXA_PADRAO
    amostras_consumidas: int = 0
    saida: bytearray = field(default_factory=bytearray, repr=False)

    def abrir(self) -> None:
        return None

    def escrever(self, amostras: bytes) -> int:
        self.saida.extend(amostras)
        consumidas = len(amostras) // BYTES_POR_AMOSTRA
        self.amostras_consumidas += consumidas
        return consumidas

    def limpar(self) -> int:
        return 0  # consome na hora: não existe nada enfileirado para descartar (F1-03)

    def fechar(self) -> None:
        return None


@dataclass(slots=True)
class SumidouroDeArquivo:
    """Escreve o que saiu num WAV PCM16 mono — útil para ouvir depois o que o teste gerou."""

    caminho: Path
    device_id: str = ""
    taxa: int = TAXA_PADRAO
    amostras_consumidas: int = 0
    _arquivo: wave.Wave_write | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.device_id:
            self.device_id = f"arquivo:{self.caminho.name}"

    def abrir(self) -> None:
        # O arquivo fica aberto entre `escrever` e `fechar`: o sumidouro é um fluxo,
        # não uma escrita única — `with` aqui fecharia antes do primeiro pedaço sair.
        arquivo = wave.open(str(self.caminho), "wb")  # noqa: SIM115
        arquivo.setnchannels(CANAIS)
        arquivo.setsampwidth(BYTES_POR_AMOSTRA)
        arquivo.setframerate(self.taxa)
        self._arquivo = arquivo

    def escrever(self, amostras: bytes) -> int:
        if self._arquivo is None:
            raise RuntimeError("sumidouro de arquivo não foi aberto")
        self._arquivo.writeframes(amostras)
        consumidas = len(amostras) // BYTES_POR_AMOSTRA
        self.amostras_consumidas += consumidas
        return consumidas

    def limpar(self) -> int:
        return 0

    def fechar(self) -> None:
        if self._arquivo is not None:
            self._arquivo.close()
            self._arquivo = None


@dataclass(slots=True)
class SumidouroDeDispositivo:
    """Playback real, pelo backend de `jarvis.audio_io.dispositivo`.

    **Não verificado, e é o ponto que mais importa:** a fila do driver não é a nossa fila.
    `escrever` volta quando o PortAudio **aceitou** as amostras, não quando o alto-falante
    tocou, e `limpar` aborta o fluxo sem conseguir dizer quantas amostras morreram no buffer
    do sistema — por isso devolve 0, que aqui significa "não sei". Cancelamento perceptível ao
    ouvido continua sendo o aceite do F1-16, de ouvido, na máquina do dono.
    """

    device_id: str = "dispositivo:padrao"
    taxa: int = TAXA_PADRAO
    amostras_consumidas: int = 0
    ambiente: Mapping[str, str] | None = None
    dispositivo: int | str | None = None
    _saida: object | None = field(default=None, repr=False)

    def abrir(self) -> None:
        from jarvis.audio_io.dispositivo import ReproducaoNoDispositivo

        proibir_dispositivo_em_ci(self.ambiente)
        saida = ReproducaoNoDispositivo(
            taxa=self.taxa, dispositivo=self.dispositivo, ambiente=self.ambiente
        )
        saida.abrir()
        self.device_id = saida.device_id
        self._saida = saida

    def _aberto(self) -> object:
        from jarvis.audio_io.dispositivo import ReproducaoNoDispositivo

        if not isinstance(self._saida, ReproducaoNoDispositivo):
            raise DispositivoIndisponivel("sumidouro de dispositivo não foi aberto")
        return self._saida

    def escrever(self, amostras: bytes) -> int:
        from jarvis.audio_io.dispositivo import ReproducaoNoDispositivo

        saida = self._aberto()
        assert isinstance(saida, ReproducaoNoDispositivo)
        consumidas = saida.escrever(amostras)
        self.amostras_consumidas = saida.amostras_consumidas
        return consumidas

    def limpar(self) -> int:
        from jarvis.audio_io.dispositivo import ReproducaoNoDispositivo

        if isinstance(self._saida, ReproducaoNoDispositivo):
            return self._saida.limpar()
        return 0

    def fechar(self) -> None:
        from jarvis.audio_io.dispositivo import ReproducaoNoDispositivo

        if isinstance(self._saida, ReproducaoNoDispositivo):
            self._saida.fechar()
        self._saida = None
