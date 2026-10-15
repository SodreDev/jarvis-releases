"""VAD barato atrás de interface: histerese configurável e o `silero-vad` (cartão F1-05).

O evento mais importante do sistema é "começou a falar". Ele tem de sair rápido e **sem
esperar ninguém** — nem ASR, nem S2 (§3.3 regra 1). Por isso o VAD mora no `audio-io`, atrás
da mesma interface que o F1-01 criou para fonte e sumidouro: o `silero-vad` (MIT, verificado na
porta de licença) é a implementação do produto, e o limiar de energia continua existindo para
o CI, que não tem o peso do modelo.

**Histerese, e por que ela é assimétrica.** Ligar custa 1 quadro (20 ms): atrasar o
`speech_started` é atrasar o barge-in, que é o SLO-2. Desligar custa 10 quadros mais o
*hangover* (200 ms por padrão): desligar cedo picaria a fala do dono em pedaços a cada pausa
entre palavras. A assimetria é a política, e está em dado, não em `if` espalhado.

**A janela do modelo não é o nosso quadro.** O `silero-vad` exige 512 amostras a 16 kHz
(32 ms) e nosso quadro é 320 (20 ms). O VAD acumula e roda o modelo quando dá, então uma
decisão pode atrasar até uma janela. Isso é inerente ao modelo e entra no piso do SLO-1 — está
medido em `docs/medicoes/f1-05-vad.md`, não escondido.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable

from jarvis.audio_io.erros import ErroDeAudio
from jarvis.audio_io.quadro import (
    MS_POR_QUADRO,
    TAXA_PADRAO,
    Quadro,
    como_int16,
)

JANELA_SILERO: Final = 512
"""Amostras por inferência a 16 kHz: exigência do modelo (a F0-04 mediu com esta janela)."""
CONTEXTO_SILERO: Final = 64
"""O v5 recebe 64 amostras do bloco anterior ANTES da janela (entrada de 576).

Isso não está no formato do ONNX (a entrada é dinâmica): está no wrapper oficial do
silero-vad, e descobrir custou uma medição errada — sem o contexto, a probabilidade fica
em 0,001 para fala de verdade, e o VAD simplesmente nunca dispara."""
AMPLITUDE: Final = 32768.0
PASTA_MODELOS_PADRAO: Final = Path.home() / ".cache" / "jarvis" / "modelos"
ARQUIVO_SILERO: Final = "silero_vad.onnx"
URL_SILERO: Final = (
    "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"
)


class ModeloIndisponivel(ErroDeAudio):
    """Falta o peso do VAD ou o runtime. A mensagem diz exatamente o que fazer."""


@runtime_checkable
class Vad(Protocol):
    """Diz quando o estado de fala muda. Não decide turno (§2) — isso é o cartão F1-07."""

    nome: str
    falando: bool | None
    ultima_probabilidade: float

    def ver(self, quadro: Quadro) -> bool | None:
        """Novo estado quando ele muda; `None` quando nada mudou."""
        ...


@dataclass(frozen=True, slots=True)
class Histerese:
    """A política de ligar e desligar, em dado.

    `quadros_para_ligar = 1` porque `speech_started` é o gatilho do barge-in (SLO-2) e cada
    quadro de espera é 20 ms de resposta a mais. `quadros_para_desligar` e `hangover_ms` são
    grandes porque pausa entre palavras não é fim de fala — e fim de **turno** é outra coisa,
    decidida por outro componente (F1-07).
    """

    limiar: float = 0.5
    quadros_para_ligar: int = 1
    quadros_para_desligar: int = 10
    hangover_ms: float = 200.0

    @property
    def quadros_de_hangover(self) -> int:
        return round(self.hangover_ms / MS_POR_QUADRO)

    @property
    def quadros_para_silencio(self) -> int:
        return self.quadros_para_desligar + self.quadros_de_hangover


@dataclass(slots=True)
class MaquinaDeHisterese:
    """Conta quadros acima e abaixo do limiar. É a mesma para qualquer fonte de probabilidade."""

    histerese: Histerese = field(default_factory=Histerese)
    falando: bool | None = None
    acima: int = 0
    abaixo: int = 0

    def ver(self, probabilidade: float) -> bool | None:
        if probabilidade >= self.histerese.limiar:
            self.acima += 1
            self.abaixo = 0
        else:
            self.abaixo += 1
            self.acima = 0

        if self.falando is not True and self.acima >= self.histerese.quadros_para_ligar:
            self.falando = True
            return True
        if self.falando is not False and self.abaixo >= self.histerese.quadros_para_silencio:
            self.falando = False
            return False
        return None


@dataclass(slots=True)
class VadDeEnergia:
    """Limiar de energia com histerese: é o VAD do CI, que não tem o peso do modelo.

    Não devolve probabilidade de verdade — devolve 0 ou 1 e deixa a histerese fazer o resto.
    Todo relatório que usar este VAD diz o nome dele (`nome` vai no relatório e no CSV).
    """

    limiar_db: float = -45.0
    histerese: Histerese = field(default_factory=Histerese)
    nome: str = "energia@1"
    ultima_probabilidade: float = 0.0
    _maquina: MaquinaDeHisterese = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._maquina = MaquinaDeHisterese(histerese=self.histerese)

    @property
    def falando(self) -> bool | None:
        return self._maquina.falando

    @falando.setter
    def falando(self, valor: bool | None) -> None:
        self._maquina.falando = valor

    def ver(self, quadro: Quadro) -> bool | None:
        self.ultima_probabilidade = 1.0 if quadro.energia_db >= self.limiar_db else 0.0
        return self._maquina.ver(self.ultima_probabilidade)


@dataclass(slots=True)
class VadSilero:
    """`silero-vad` v5 em ONNX (MIT), com janela de 512 amostras e estado recorrente.

    O peso **não** é versionado no repositório (2,3 MB, mas a regra do projeto é modelo fora do
    git). Falta o arquivo ou o runtime? `abrir` recusa dizendo de onde baixar — nunca devolve
    "não há fala" fingindo que mediu.
    """

    caminho: Path = field(default_factory=lambda: PASTA_MODELOS_PADRAO / ARQUIVO_SILERO)
    histerese: Histerese = field(default_factory=Histerese)
    taxa: int = TAXA_PADRAO
    nome: str = "silero-vad@v5"
    ultima_probabilidade: float = 0.0
    janelas: int = 0
    _sessao: Any = field(default=None, repr=False)
    _estado: Any = field(default=None, repr=False)
    _contexto: Any = field(default=None, repr=False)
    _buffer: array[int] = field(default_factory=lambda: array("h"), repr=False)
    _maquina: MaquinaDeHisterese = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._maquina = MaquinaDeHisterese(histerese=self.histerese)

    @property
    def falando(self) -> bool | None:
        return self._maquina.falando

    @falando.setter
    def falando(self, valor: bool | None) -> None:
        self._maquina.falando = valor

    @property
    def aberto(self) -> bool:
        return self._sessao is not None

    def abrir(self) -> None:
        if not self.caminho.exists():
            raise ModeloIndisponivel(
                f"o peso do VAD não está em {self.caminho}. Modelo não é versionado: baixe "
                f"{URL_SILERO} (MIT, registrado em licenses/modelos.toml) para essa pasta."
            )
        try:
            import numpy as np
            import onnxruntime as ort
        except ImportError as erro:  # pragma: no cover — ambiente sem o runtime
            raise ModeloIndisponivel(
                "onnxruntime não está instalado: é o runtime do silero-vad. "
                "Rode `uv sync` (ele está nas dependências do projeto)."
            ) from erro
        opcoes = ort.SessionOptions()
        opcoes.inter_op_num_threads = 1
        opcoes.intra_op_num_threads = 1
        self._sessao = ort.InferenceSession(
            str(self.caminho), sess_options=opcoes, providers=["CPUExecutionProvider"]
        )
        self._estado = np.zeros((2, 1, 128), dtype=np.float32)
        self._contexto = np.zeros((1, CONTEXTO_SILERO), dtype=np.float32)
        self._buffer = array("h")

    def zerar(self) -> None:
        """Esquece o estado recorrente (troca de sessão, ou fim de uma medição)."""
        import numpy as np

        self._estado = np.zeros((2, 1, 128), dtype=np.float32)
        self._contexto = np.zeros((1, CONTEXTO_SILERO), dtype=np.float32)
        self._buffer = array("h")
        self._maquina = MaquinaDeHisterese(histerese=self.histerese)

    def ver(self, quadro: Quadro) -> bool | None:
        """Acumula o quadro e roda o modelo nas janelas de 512 que couberem."""
        import numpy as np

        if self._sessao is None:
            self.abrir()
        self._buffer.extend(como_int16(quadro.amostras))

        mudanca: bool | None = None
        rodou = False
        while len(self._buffer) >= JANELA_SILERO:
            janela = np.asarray(self._buffer[:JANELA_SILERO], dtype=np.float32) / AMPLITUDE
            del self._buffer[:JANELA_SILERO]
            entrada = np.concatenate([self._contexto, janela.reshape(1, -1)], axis=1)
            self._contexto = entrada[:, -CONTEXTO_SILERO:]
            saida, self._estado = self._sessao.run(
                None,
                {
                    "input": entrada,
                    "state": self._estado,
                    "sr": np.array(self.taxa, dtype=np.int64),
                },
            )
            self.ultima_probabilidade = float(saida[0][0])
            self.janelas += 1
            rodou = True
            resultado = self._maquina.ver(self.ultima_probabilidade)
            if resultado is not None:
                mudanca = resultado
        if not rodou:
            # Quadro que não completou janela: ninguém decide nada, e isso é o atraso
            # inerente do modelo (32 ms de janela contra 20 ms de quadro).
            return None
        return mudanca


def vad_do_ambiente(*, caminho: Path | None = None, histerese: Histerese | None = None) -> Vad:
    """`silero-vad` quando o peso existe; limiar de energia quando não, com o nome certo.

    Quem publica número olha `vad.nome`: nunca se compara um piso de energia com um piso de
    silero como se fossem a mesma coisa.
    """
    alvo = caminho or (PASTA_MODELOS_PADRAO / ARQUIVO_SILERO)
    politica = histerese or Histerese()
    if alvo.exists():
        return VadSilero(caminho=alvo, histerese=politica)
    return VadDeEnergia(histerese=politica)
