"""ASR incremental: parcial utilizável cedo, com estabilidade medida (cartão F1-06).

**Como se faz incremental com modelo que não é streaming.** O `whisper` transcreve um bloco,
não um fluxo. A estratégia aqui é a de janela crescente com **acordo de prefixo**: a cada passo
(200 ms por padrão) transcreve-se o áudio do turno **inteiro até agora** e compara-se com a
hipótese anterior. O que as duas já dizem igual é prefixo estável; o resto ainda vai mudar.
`stability` é essa fração — número medido, não constante inventada.

**"Utilizável" é definido antes de medir** (aceite (b) do cartão): um parcial é utilizável
quando `stability >= ESTABILIDADE_MINIMA` (0,6). O SLO-3 é o tempo até o **primeiro** parcial
utilizável, e mudar esse limiar depois de ver o resultado seria escolher o número.

**Coalescing (§3.4).** O transcritor publica um parcial por passo; quem derruba dez parciais a
uma hipótese é o barramento (`PartialTranscript` está em `TIPOS_COALESCIVEIS`, F0-02), e o `s2`
produz **uma** revisão de estado. O transcritor não tenta ser esperto sozinho.

A ordem com o `Cancel` não é problema deste módulo: a `Percepcao` (F1-05) já garante que o
`Cancel` sai primeiro, e o transcritor só é chamado depois — com o epoch novo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Protocol, runtime_checkable

from jarvis.audio_io.quadro import BYTES_POR_AMOSTRA, TAXA_PADRAO, Quadro
from jarvis.barramento.contrato import validar
from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust
from jarvis.corpus.metricas import acordo_de_prefixo, palavras

PASSO_PADRAO_MS: Final = 200.0
ESTABILIDADE_MINIMA: Final = 0.6
"""Limiar de "utilizável" do SLO-3, escrito **antes** de medir (aceite (b) do F1-06)."""
IDIOMA: Final = "pt-BR"


@runtime_checkable
class MotorDeAsr(Protocol):
    """Transcreve um bloco de áudio. Quem é incremental é o `TranscritorIncremental`."""

    nome: str
    modelo: str
    licenca: str

    def transcrever(self, amostras: bytes) -> tuple[str, float]:
        """Texto e confiança em [0, 1] para o bloco inteiro."""
        ...


@dataclass(slots=True)
class MotorDeReferencia:
    """Oráculo: devolve o texto do rótulo na proporção do áudio já ouvido.

    **É oráculo, não ASR.** Serve para o CI exercitar o encanamento (passos, estabilidade,
    coalescing, SLO-3 de software) sem baixar modelo nenhum, e para o F1-07 ter texto sem
    carregar o custo do ASR em cada varredura. WER de oráculo é zero por construção, e nenhum
    relatório pode apresentá-lo como WER de ASR.
    """

    texto: str
    duracao_ms: float
    nome: str = "oráculo-do-rótulo@1"
    modelo: str = "(nenhum)"
    licenca: str = "não se aplica (texto do próprio corpus)"

    def transcrever(self, amostras: bytes) -> tuple[str, float]:
        if self.duracao_ms <= 0:
            return self.texto, 1.0
        ouvido_ms = 1000.0 * (len(amostras) // BYTES_POR_AMOSTRA) / TAXA_PADRAO
        fracao = max(0.0, min(1.0, ouvido_ms / self.duracao_ms))
        todas = palavras(self.texto)
        quantas = round(fracao * len(todas))
        return " ".join(todas[:quantas]), 1.0


@dataclass(slots=True)
class MotorWhisper:
    """`whisper` rodando em CTranslate2 (`faster-whisper`, MIT).

    O peso **não** é versionado. Modelo e licença vão no relatório: `openai/whisper-*` é
    Apache-2.0 e **não** exige atribuição no produto — ao contrário do `parakeet` (CC-BY-4.0),
    que exige e tem porta de licença para isso.
    """

    tamanho: str = "small"
    pasta: str = ""
    idioma: str = "pt"
    beam: int = 1
    nome: str = ""
    modelo: str = ""
    licenca: str = "Apache-2.0"
    _modelo: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.nome:
            self.nome = f"faster-whisper@{self.tamanho}"
        if not self.modelo:
            self.modelo = f"openai/whisper-{self.tamanho}"

    def abrir(self) -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as erro:  # pragma: no cover — ambiente sem o grupo `asr`
            raise RuntimeError(
                "faster-whisper não está instalado: é o runtime de medição do ASR (grupo "
                "opcional `asr`). Rode `uv sync --group asr`."
            ) from erro
        self._modelo = WhisperModel(
            self.tamanho,
            device="cpu",
            compute_type="int8",
            download_root=self.pasta or None,
        )

    def transcrever(self, amostras: bytes) -> tuple[str, float]:
        import numpy as np

        if self._modelo is None:
            self.abrir()
        audio = np.frombuffer(amostras, dtype="<i2").astype(np.float32) / 32768.0
        trechos, _ = self._modelo.transcribe(
            audio, language=self.idioma, beam_size=self.beam, vad_filter=False
        )
        partes = list(trechos)
        texto = " ".join(t.text for t in partes).strip()
        if not partes:
            return "", 0.0
        # avg_logprob é logaritmo de probabilidade média por token; exp traz para [0, 1].
        media = sum(float(t.avg_logprob) for t in partes) / len(partes)
        return texto, float(min(1.0, max(0.0, 2.718281828**media)))


@dataclass(frozen=True, slots=True)
class Passo:
    """Um passo do transcritor, para medição (não é evento do barramento)."""

    t_fim_ms: float
    texto: str
    estabilidade: float
    utilizavel: bool


@dataclass(slots=True)
class TranscritorIncremental:
    """Acumula quadros, transcreve por passo e publica `PartialTranscript`/`FinalTranscript`."""

    motor: MotorDeAsr
    passo_ms: float = PASSO_PADRAO_MS
    estabilidade_minima: float = ESTABILIDADE_MINIMA
    idioma: str = IDIOMA
    nome: str = ""
    session_id: str = ""
    epoch: int = 0
    passos: list[Passo] = field(default_factory=list)
    _audio: bytearray = field(default_factory=bytearray, repr=False)
    _ultimo_texto: str = field(default="", repr=False)
    _ms_do_ultimo_passo: float = field(default=0.0, repr=False)

    def __post_init__(self) -> None:
        if not self.nome:
            self.nome = f"incremental+{self.motor.nome}"

    @property
    def ouvido_ms(self) -> float:
        return 1000.0 * (len(self._audio) // BYTES_POR_AMOSTRA) / TAXA_PADRAO

    def comecar(self, *, session_id: str, epoch: int) -> list[Envelope]:
        """Turno novo: zera o áudio e a hipótese. Nenhum evento sai antes de ouvir algo."""
        self.session_id = session_id
        self.epoch = epoch
        self._audio = bytearray()
        self._ultimo_texto = ""
        self._ms_do_ultimo_passo = 0.0
        self.passos = []
        return []

    def ouvir(self, quadro: Quadro) -> list[Envelope]:
        """Um quadro de 20 ms. Publica um parcial quando fecha um passo."""
        self._audio.extend(quadro.amostras)
        if self.ouvido_ms - self._ms_do_ultimo_passo < self.passo_ms:
            return []
        self._ms_do_ultimo_passo = self.ouvido_ms
        texto, _ = self.motor.transcrever(bytes(self._audio))
        estabilidade = acordo_de_prefixo(self._ultimo_texto, texto)
        self._ultimo_texto = texto
        if not texto:
            return []
        self.passos.append(
            Passo(
                t_fim_ms=self.ouvido_ms,
                texto=texto,
                estabilidade=estabilidade,
                utilizavel=estabilidade >= self.estabilidade_minima,
            )
        )
        return [self._parcial(texto, estabilidade)]

    def fechar(self) -> list[Envelope]:
        """Fim do turno: transcreve o que falta e publica o `FinalTranscript` com confiança."""
        if not self._audio:
            return []
        texto, confianca = self.motor.transcrever(bytes(self._audio))
        if not texto:
            return []
        return [self._final(texto, confianca)]

    def primeiro_utilizavel_ms(self) -> float | None:
        """SLO-3: fim do áudio do primeiro parcial com estabilidade suficiente."""
        return next((p.t_fim_ms for p in self.passos if p.utilizavel), None)

    def _parcial(self, texto: str, estabilidade: float) -> Envelope:
        return validar(
            Envelope(
                session_id=self.session_id,
                epoch=self.epoch,
                source="agentd",
                trust=Trust.USER_VOICE,
                priority=Prioridade.P1,
                type=Tipo.PARTIAL_TRANSCRIPT,
                payload={
                    "text": texto,
                    "stability": round(estabilidade, 3),
                    "t_start_ms": 0,
                    "t_end_ms": int(self.ouvido_ms),
                    "lang": self.idioma,
                },
            )
        )

    def _final(self, texto: str, confianca: float) -> Envelope:
        return validar(
            Envelope(
                session_id=self.session_id,
                epoch=self.epoch,
                source="agentd",
                trust=Trust.USER_VOICE,
                priority=Prioridade.P1,
                type=Tipo.FINAL_TRANSCRIPT,
                payload={
                    "text": texto,
                    "confidence": round(confianca, 3),
                    "t_start_ms": 0,
                    "t_end_ms": int(self.ouvido_ms),
                },
            )
        )
