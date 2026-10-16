"""Abertura de dispositivo real de áudio, atrás dos adaptadores do F1-01.

O F1-01 deixou `FonteDeDispositivo` e `SumidouroDeDispositivo` declarados e recusando com
motivo — "a captura de dispositivo entra com o hardware do dono". Este módulo é esse backend,
e ele entra **atrás** da mesma interface: nada do laço de voz sabe que existe placa de som.

**Biblioteca:** `sounddevice` (MIT), que fala com o **PortAudio** (licença MIT com pedidos não
vinculantes). No Linux o PortAudio é biblioteca do sistema e **não** vem na roda do PyPI — por
isso a recusa separa dois casos que parecem um só: "o extra não está instalado" e "o extra
está, mas falta a biblioteca do sistema". A segunda é a mais comum, e a mensagem diz o comando.

**O que este backend NÃO resolve, e está dito aqui porque é o que o dono vai medir:** a fila do
driver não é a nossa fila. `escrever` devolve quando o PortAudio **aceitou** as amostras, não
quando o alto-falante tocou, e `limpar` aborta o fluxo sem conseguir dizer quantas amostras
morreram no buffer do sistema. Então, com dispositivo real, `amostras_consumidas` é "entregue
ao driver", e o barge-in perceptível ao ouvido continua sendo o aceite do F1-16, na máquina do
dono, de ouvido. Aqui a latência é reduzida pelo que dá: bloco de 20 ms e `latency="low"`.

**Nada disto roda sob `CI=1`:** `proibir_dispositivo_em_ci` continua sendo a primeira linha de
`abrir`, como no F1-01.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from jarvis.audio_io.ambiente import proibir_dispositivo_em_ci
from jarvis.audio_io.erros import DispositivoIndisponivel
from jarvis.audio_io.quadro import (
    AMOSTRAS_POR_QUADRO,
    BYTES_POR_AMOSTRA,
    CANAIS,
    TAXA_PADRAO,
    Quadro,
)
from jarvis.relogio import Relogio, RelogioDoSistema

LATENCIA: Final = "low"
TIPO_DE_AMOSTRA: Final = "int16"
"""PCM16, o mesmo do contrato de quadro (F1-01): sem conversão no caminho."""


class BibliotecaDeAudioAusente(DispositivoIndisponivel):
    """Falta o `sounddevice` (extra) ou o PortAudio (biblioteca do sistema)."""


def importar_sounddevice() -> Any:
    """O `sounddevice`, ou uma recusa que diz **qual** das duas coisas falta.

    `import sounddevice` levanta `OSError('PortAudio library not found')` quando o pacote
    Python está instalado e a biblioteca do sistema não — e um `ImportError` genérico faria o
    dono reinstalar o pacote certo pelo motivo errado.
    """
    try:
        import sounddevice
    except ImportError as erro:
        raise BibliotecaDeAudioAusente(
            "sounddevice não está instalado: é o extra que abre o dispositivo real "
            "(`uv sync --group dispositivo`)"
        ) from erro
    except OSError as erro:
        raise BibliotecaDeAudioAusente(
            f"o sounddevice está instalado, mas o PortAudio do sistema não foi encontrado "
            f"({erro}). No Fedora/Nobara: `sudo dnf install portaudio`; no Debian/Ubuntu: "
            "`sudo apt install libportaudio2`. Enquanto isso, o modo texto (`--texto`) e o "
            "backend de arquivo continuam funcionando"
        ) from erro
    return sounddevice


@dataclass(frozen=True, slots=True)
class Dispositivo:
    """Um dispositivo como o sistema o descreve — para o `--diagnostico` listar."""

    indice: int
    nome: str
    entradas: int
    saidas: int
    taxa_padrao: float
    padrao_de_entrada: bool = False
    padrao_de_saida: bool = False

    @property
    def captura(self) -> bool:
        return self.entradas > 0

    @property
    def reproducao(self) -> bool:
        return self.saidas > 0

    def __str__(self) -> str:
        papeis = []
        if self.captura:
            papeis.append(f"entrada×{self.entradas}")
        if self.reproducao:
            papeis.append(f"saída×{self.saidas}")
        marca = []
        if self.padrao_de_entrada:
            marca.append("padrão de entrada")
        if self.padrao_de_saida:
            marca.append("padrão de saída")
        sufixo = f" [{', '.join(marca)}]" if marca else ""
        return (
            f"{self.indice}: {self.nome} ({', '.join(papeis)}, {self.taxa_padrao:.0f} Hz){sufixo}"
        )


def listar_dispositivos(ambiente: Mapping[str, str] | None = None) -> tuple[Dispositivo, ...]:
    """Os dispositivos do sistema. Recusa sob CI, como qualquer caminho de dispositivo real."""
    proibir_dispositivo_em_ci(ambiente)
    sounddevice = importar_sounddevice()
    try:
        entrada_padrao, saida_padrao = sounddevice.default.device
        achados = list(sounddevice.query_devices())
    except Exception as erro:  # o PortAudio levanta tipos próprios, fora da nossa hierarquia
        raise DispositivoIndisponivel(f"não deu para listar dispositivos: {erro}") from None
    return tuple(
        Dispositivo(
            indice=indice,
            nome=str(bruto.get("name", "?")),
            entradas=int(bruto.get("max_input_channels", 0)),
            saidas=int(bruto.get("max_output_channels", 0)),
            taxa_padrao=float(bruto.get("default_samplerate", 0.0)),
            padrao_de_entrada=indice == entrada_padrao,
            padrao_de_saida=indice == saida_padrao,
        )
        for indice, bruto in enumerate(achados)
    )


def _abrir_fluxo(construtor: Any, **argumentos: Any) -> Any:
    try:
        fluxo = construtor(**argumentos)
        fluxo.start()
    except Exception as erro:  # o PortAudio levanta tipos próprios, fora da nossa hierarquia
        raise DispositivoIndisponivel(
            f"não deu para abrir o dispositivo ({erro}). Confira o nome/índice no "
            "`jarvis-voz --diagnostico` e se outro programa está segurando a placa"
        ) from None
    return fluxo


@dataclass(slots=True)
class CapturaDoDispositivo:
    """Microfone real entregando quadros de 20 ms, no ritmo do próprio dispositivo.

    Não usa `relogio.dormir`: quem ritma é o `read` bloqueante do PortAudio. O `Relogio`
    continua injetado porque o **carimbo** do quadro tem de vir da mesma fonte de tempo do
    resto do caminho (é com ele que o F1-10 mede barge-in).
    """

    relogio: Relogio = field(default_factory=RelogioDoSistema)
    device_id: str = "dispositivo:padrao"
    taxa: int = TAXA_PADRAO
    dispositivo: int | str | None = None
    ambiente: Mapping[str, str] | None = None
    estouros: int = 0
    """Quantas vezes o driver avisou que perdeu amostra (buffer estourado). Número que o
    diagnóstico mostra: estouro é perda de áudio do dono, não detalhe de implementação."""
    _fluxo: Any = field(default=None, repr=False)

    def abrir(self) -> None:
        proibir_dispositivo_em_ci(self.ambiente)
        sounddevice = importar_sounddevice()
        self._fluxo = _abrir_fluxo(
            sounddevice.RawInputStream,
            samplerate=self.taxa,
            blocksize=AMOSTRAS_POR_QUADRO,
            dtype=TIPO_DE_AMOSTRA,
            channels=CANAIS,
            device=self.dispositivo,
            latency=LATENCIA,
        )
        if self.dispositivo is not None:
            self.device_id = f"dispositivo:{self.dispositivo}"

    def quadros(self) -> Iterator[Quadro]:
        if self._fluxo is None:
            raise DispositivoIndisponivel("a captura do dispositivo não foi aberta")
        indice = 0
        while self._fluxo is not None:
            dados, estourou = self._fluxo.read(AMOSTRAS_POR_QUADRO)
            if estourou:
                self.estouros += 1
            amostras = bytes(dados)
            if len(amostras) < AMOSTRAS_POR_QUADRO * BYTES_POR_AMOSTRA:
                amostras += bytes(AMOSTRAS_POR_QUADRO * BYTES_POR_AMOSTRA - len(amostras))
            yield Quadro(
                indice=indice,
                amostras=amostras,
                ts_mono_ns=self.relogio.mono_ns(),
                taxa=self.taxa,
            )
            indice += 1

    def fechar(self) -> None:
        fluxo, self._fluxo = self._fluxo, None
        if fluxo is not None:
            fluxo.stop()
            fluxo.close()


@dataclass(slots=True)
class ReproducaoNoDispositivo:
    """Alto-falante real. `amostras_consumidas` é "entregue ao driver", e isso está declarado.

    `limpar` aborta o fluxo — é o que descarta o que o sistema ainda não tocou — e devolve
    **0**, porque o PortAudio não diz quantas amostras morreram no buffer dele. Zero aqui
    significa "não sei", e quem precisa do número de verdade é o F1-16, de ouvido e com
    cronômetro na máquina do dono.
    """

    device_id: str = "dispositivo:padrao"
    taxa: int = TAXA_PADRAO
    amostras_consumidas: int = 0
    dispositivo: int | str | None = None
    ambiente: Mapping[str, str] | None = None
    abortos: int = 0
    _fluxo: Any = field(default=None, repr=False)

    def abrir(self) -> None:
        proibir_dispositivo_em_ci(self.ambiente)
        sounddevice = importar_sounddevice()
        self._fluxo = _abrir_fluxo(
            sounddevice.RawOutputStream,
            samplerate=self.taxa,
            blocksize=AMOSTRAS_POR_QUADRO,
            dtype=TIPO_DE_AMOSTRA,
            channels=CANAIS,
            device=self.dispositivo,
            latency=LATENCIA,
        )
        if self.dispositivo is not None:
            self.device_id = f"dispositivo:{self.dispositivo}"

    def escrever(self, amostras: bytes) -> int:
        if self._fluxo is None:
            raise DispositivoIndisponivel("a reprodução no dispositivo não foi aberta")
        self._fluxo.write(amostras)
        consumidas = len(amostras) // BYTES_POR_AMOSTRA
        self.amostras_consumidas += consumidas
        return consumidas

    def limpar(self) -> int:
        """Aborta o que o driver ainda não tocou e reabre o fluxo para o próximo turno."""
        if self._fluxo is None:
            return 0
        self.abortos += 1
        self._fluxo.abort()
        self._fluxo.start()
        return 0

    def fechar(self) -> None:
        fluxo, self._fluxo = self._fluxo, None
        if fluxo is not None:
            fluxo.stop()
            fluxo.close()


def nomes_de_dispositivo(dispositivos: Sequence[Dispositivo]) -> tuple[str, ...]:
    return tuple(str(d) for d in dispositivos)
