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

**A interface do motor mora em `jarvis.voz` desde a ADR-0017** e é reexportada aqui para o
código do F1-06 continuar importando do mesmo lugar. O que o motor é não mudou (um bloco
entra, texto e confiança saem); o que ele passou a declarar é `idioma`, `onde` (local ou
nuvem) e o `registrado` — o id pelo qual o portão de motores decide se ele pode rodar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from jarvis.audio_io.quadro import BYTES_POR_AMOSTRA, TAXA_PADRAO, Quadro
from jarvis.barramento.contrato import validar
from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust
from jarvis.corpus.metricas import acordo_de_prefixo, palavras
from jarvis.voz.interface import IDIOMA_PADRAO, Hipotese, MotorDeAsr, Onde
from jarvis.voz.registro import exigir_motor

PASSO_PADRAO_MS: Final = 200.0
ESTABILIDADE_MINIMA: Final = 0.6
"""Limiar de "utilizável" do SLO-3, escrito **antes** de medir (aceite (b) do F1-06)."""
IDIOMA: Final = IDIOMA_PADRAO

__all__ = [
    "ESTABILIDADE_MINIMA",
    "IDIOMA",
    "PASSO_PADRAO_MS",
    "Hipotese",
    "MotorDeAsr",
    "MotorDeReferencia",
    "MotorWhisper",
    "Passo",
    "TranscritorIncremental",
]


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
    idioma: str = IDIOMA_PADRAO
    onde: Onde = Onde.LOCAL
    registrado: str = "asr-oraculo"

    def transcrever(self, amostras: bytes) -> Hipotese:
        if self.duracao_ms <= 0:
            return Hipotese(self.texto, 1.0)
        ouvido_ms = 1000.0 * (len(amostras) // BYTES_POR_AMOSTRA) / TAXA_PADRAO
        fracao = max(0.0, min(1.0, ouvido_ms / self.duracao_ms))
        todas = palavras(self.texto)
        quantas = round(fracao * len(todas))
        return Hipotese(" ".join(todas[:quantas]), 1.0)


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
    onde: Onde = Onde.LOCAL
    registrado: str = "asr-whisper-local"
    """Id no `licenses/motores.toml`: é o portão que diz se este motor pode rodar."""
    dicas: str = ""
    """Palavras que o modelo deve preferir (`hotwords` do faster-whisper). Nome próprio é onde o
    whisper pequeno mais erra: "jarvis" sai "Dia 10" (medido em 2026-10-17 com a voz do piper);
    com a dica sai "Jarvis". Vazio = sem dica. A dica vai com inicial maiúscula: o modelo ignora
    "jarvis" em minúsculas (medido: "Diazis"), e só "Jarvis" muda a saída."""
    _modelo: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.nome:
            self.nome = f"faster-whisper@{self.tamanho}"
        if not self.modelo:
            self.modelo = f"openai/whisper-{self.tamanho}"

    def abrir(self) -> None:
        # O portão **antes** do runtime: motor não registrado não carrega, e a licença do
        # cliente (faster-whisper, MIT) é conferida no registro, não no que este código afirma.
        motor = exigir_motor(self.registrado)
        self.licenca = motor.licenca_do_cliente
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

    def transcrever(self, amostras: bytes) -> Hipotese:
        import numpy as np

        if self._modelo is None:
            self.abrir()
        audio = np.frombuffer(amostras, dtype="<i2").astype(np.float32) / 32768.0
        trechos, _ = self._modelo.transcribe(
            audio,
            language=self.idioma,
            beam_size=self.beam,
            vad_filter=False,
            hotwords=self._dicas_para_modelo() or None,
            initial_prompt=self._prompt_inicial() or None,
        )
        partes = list(trechos)
        texto = " ".join(t.text for t in partes).strip()
        if not partes:
            return Hipotese("", 0.0)
        # avg_logprob é logaritmo de probabilidade média por token; exp traz para [0, 1].
        media = sum(float(t.avg_logprob) for t in partes) / len(partes)
        return Hipotese(texto, float(min(1.0, max(0.0, 2.718281828**media))))

    def _dicas_para_modelo(self) -> str:
        """Capitaliza só palavras inteiramente minúsculas e preserva nomes como TeamSpeak."""
        return " ".join(
            parte.capitalize() if parte.islower() else parte for parte in self.dicas.strip().split()
        )

    def _prompt_inicial(self) -> str:
        dicas = self._dicas_para_modelo()
        return f"Abra {dicas}." if dicas else ""


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
