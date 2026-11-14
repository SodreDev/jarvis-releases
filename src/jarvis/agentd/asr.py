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
from jarvis.voz.interface import IDIOMA_PADRAO, Hipotese, MotorDeAsr, Onde, Sinais, Transcricao
from jarvis.voz.registro import exigir_motor

PASSO_PADRAO_MS: Final = 200.0
ESTABILIDADE_MINIMA: Final = 0.6
"""Limiar de "utilizável" do SLO-3, escrito **antes** de medir (aceite (b) do F1-06)."""
IDIOMA: Final = IDIOMA_PADRAO
TAMANHO_AUTOMATICO: Final = "auto"
"""`modelo_do_asr = "auto"` (ADR-0067): o melhor que esta máquina roda ao vivo."""
MODELO_NA_PLACA: Final = "large-v3-turbo"
"""Com a placa de vídeo: o turbo (o mesmo da Groq) em float16."""
MODELO_NA_CPU: Final = "small"
"""Sem a placa: o que cabe no tempo de um turno na CPU (`docs/medicoes/stt-pt-br.md`)."""

__all__ = [
    "ESTABILIDADE_MINIMA",
    "IDIOMA",
    "MODELO_NA_CPU",
    "MODELO_NA_PLACA",
    "PASSO_PADRAO_MS",
    "TAMANHO_AUTOMATICO",
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
    dispositivo: str = "auto"
    """`auto` (o padrão, ADR-0067): a placa de vídeo em float16 quando o CTranslate2 a enxerga **e**
    uma conta de teste passa — a falta da cuBLAS só aparece na primeira conta, não ao carregar —;
    senão a CPU em int8, como sempre. `cpu`/`cuda` forçam. `em_uso` diz qual ficou."""
    em_uso: str = ""
    nome: str = ""
    modelo: str = ""
    licenca: str = "Apache-2.0"
    onde: Onde = Onde.LOCAL
    registrado: str = "asr-whisper-local"
    """Id no `licenses/motores.toml`: é o portão que diz se este motor pode rodar."""
    dica: str = ""
    """O texto que vai antes do áudio (`initial_prompt`), já montado por `jarvis.voz.dica`: a
    palavra de ativação e poucos termos do dono ("Jarvis, Thiago Nigro."). Nome próprio é onde o
    whisper pequeno mais erra ("jarvis" sai "Dia 10" sem dica, medido em 2026-10-17). **Curta de
    propósito** (ADR-0043): a lista de apps instalados que ia aqui fez todo ruído forçado no whisper
    virar texto, e em `hotwords` a dica vazou mais do que como texto inicial — por isso só ele.
    Vazio = sem dica."""
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
        self._modelo = None
        automatico = self.tamanho == TAMANHO_AUTOMATICO
        if self.dispositivo in {"auto", "cuda"} and _cuda_visivel():
            try:
                tamanho = MODELO_NA_PLACA if automatico else self.tamanho
                modelo = WhisperModel(
                    tamanho,
                    device="cuda",
                    compute_type="float16",
                    download_root=self.pasta or None,
                )
                # A conta de teste: sem a libcublas, é aqui que a placa falha (0,1 s de silêncio).
                import numpy as np

                silencio = np.zeros(1600, dtype=np.float32)
                list(modelo.transcribe(silencio, language=self.idioma, beam_size=1)[0])
                self._modelo, self.em_uso = modelo, "cuda/float16"
                self._resolver(tamanho, automatico)
            except Exception:
                if self.dispositivo == "cuda":
                    raise
        if self._modelo is None:
            tamanho = MODELO_NA_CPU if automatico else self.tamanho
            self._modelo = WhisperModel(
                tamanho,
                device="cpu",
                compute_type="int8",
                download_root=self.pasta or None,
            )
            self.em_uso = "cpu/int8"
            self._resolver(tamanho, automatico)

    def _resolver(self, tamanho: str, automatico: bool) -> None:
        """O `auto` vira o tamanho que carregou: o relatório e o diagnóstico dizem qual."""
        if automatico:
            self.tamanho = tamanho
            self.nome = f"faster-whisper@{tamanho}"
            self.modelo = f"openai/whisper-{tamanho}"

    def transcrever(self, amostras: bytes) -> Hipotese:
        return self.transcrever_com_sinais(amostras).hipotese

    def transcrever_com_sinais(self, amostras: bytes) -> Transcricao:
        """O texto e os sinais dos segmentos (`no_speech_prob`, `avg_logprob`, compressão): é com
        eles que o filtro de ruído separa a fala do texto inventado num trecho sem fala."""
        import numpy as np

        if self._modelo is None:
            self.abrir()
        audio = np.frombuffer(amostras, dtype="<i2").astype(np.float32) / 32768.0
        trechos, _ = self._modelo.transcribe(
            audio,
            language=self.idioma,
            beam_size=self.beam,
            vad_filter=False,
            initial_prompt=self.dica or None,
        )
        partes = list(trechos)
        texto = " ".join(t.text for t in partes).strip()
        if not partes:
            return Transcricao(Hipotese("", 0.0))
        # avg_logprob é logaritmo de probabilidade média por token; exp traz para [0, 1].
        media = sum(float(t.avg_logprob) for t in partes) / len(partes)
        sinais = Sinais(
            sem_fala=max(float(t.no_speech_prob) for t in partes),
            logprob=media,
            compressao=max(float(t.compression_ratio) for t in partes),
        )
        return Transcricao(Hipotese(texto, float(min(1.0, max(0.0, 2.718281828**media)))), sinais)


def _cuda_visivel() -> bool:
    try:
        import ctranslate2  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover — vem junto com o faster-whisper
        return False
    try:
        visivel = int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:
        return False
    if visivel:
        _carregar_cublas_do_pip()
    return visivel


def _carregar_cublas_do_pip() -> None:
    """A cuBLAS 12 do pacote `nvidia-cublas-cu12`, quando ele está no Python: o CTranslate2 a abre
    pelo nome (`libcublas.so.12`), e a pasta do pacote não está no caminho do carregador — então
    ela é aberta aqui antes, com RTLD_GLOBAL. Sem o pacote, nada muda: a conta de teste decide."""
    import ctypes
    import importlib.util
    from pathlib import Path

    try:
        especificacao = importlib.util.find_spec("nvidia.cublas")
    except (ImportError, ValueError):
        return
    if especificacao is None or not especificacao.submodule_search_locations:
        return
    for pasta in especificacao.submodule_search_locations:
        for nome in ("libcublasLt.so.12", "libcublas.so.12"):
            caminho = Path(pasta) / "lib" / nome
            if caminho.exists():
                try:
                    ctypes.CDLL(str(caminho), mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    return


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
