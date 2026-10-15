"""TTS em streaming, cancelável e com licença verificada no carregamento (cartão F1-09).

Três coisas que este módulo garante, e que são aceite do cartão:

1. **Interrupção no meio da síntese, não só no meio da fila.** O sintetizador consulta o
   cancelamento **antes de sintetizar** cada pedaço e **antes de escrever** o que sintetizou.
   O pedaço em voo é **descartado**, não escrito: depois do `Cancel`, nenhuma amostra nova chega
   ao sumidouro. A síntese de um pedaço é atômica (o modelo não é interrompível por dentro), e
   é por isso que o **primeiro** pedaço é o mais curto que a prosódia aceita — ele é o pior caso
   de trabalho jogado fora.
2. **Licença no carregamento, não no CI.** `carregar_voz` consulta `licenses/modelos.toml` e
   recusa voz que não esteja registrada ou cuja licença não seja **permissiva**. CC-BY-SA não
   carrega: *ShareAlike* numa voz contamina o áudio que o produto distribui. `coqui/XTTS-v2`
   está barrado no registro e, por estar barrado, também não carrega.
3. **Mapa texto ↔ amostras.** Cada pedaço sabe qual trecho do texto ele é e em que amostra
   começa. É esse mapa que deixa o histórico (F1-12) guardar **só o prefixo tocado** em vez do
   texto que foi enfileirado.

**Pendência de licença do caminho de produto, declarada:** as quatro vozes pt-BR do
`rhasspy/piper-voices` usam fonemas do **espeak-ng** (`phoneme_type: espeak`), que é GPL-3.0 —
verificado voz por voz no cartão F1-09, incluindo a `edresson`, que não declara o campo e usa o
mesmo inventário IPA. Fonemizar pt-BR com licença permissiva não existe pronto. No F1-02 isso
não era problema (o espeak rodava **fora** do produto, gerando corpus); aqui é, porque o TTS
roda **no** produto. As opções estão nas notas do executor; a escolha é do dono (F1-16).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from jarvis.audio_io.playback import Pedaco
from jarvis.audio_io.quadro import BYTES_POR_AMOSTRA, TAXA_PADRAO
from jarvis.licencas import (
    ARQUIVO_MODELOS,
    Categoria,
    classificar,
    estado_registrado,
    licenca_registrada,
)

PALAVRAS_DO_PRIMEIRO_PEDACO: Final = 3
"""O primeiro pedaço é curto de propósito: ele é o que atrasa o SLO-5 e o que se joga fora."""
PALAVRAS_POR_PEDACO: Final = 8
PONTUACAO_DE_CORTE: Final = (",", ";", ":", ".", "!", "?")


class VozRecusada(RuntimeError):
    """A voz não carrega: não está registrada, está barrada ou a licença não é permissiva."""


@runtime_checkable
class MotorDeTts(Protocol):
    """Sintetiza um trecho de texto em PCM16 16 kHz. Quem fatia é o sintetizador."""

    nome: str
    voz: str
    licenca: str

    def sintetizar(self, texto: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class Trecho:
    """Um pedaço do texto, com onde ele começa no texto e nas amostras."""

    indice: int
    texto: str
    inicio_no_texto: int
    inicio_em_amostras: int
    amostras: int

    @property
    def fim_no_texto(self) -> int:
        return self.inicio_no_texto + len(self.texto)

    @property
    def fim_em_amostras(self) -> int:
        return self.inicio_em_amostras + self.amostras


@dataclass(frozen=True, slots=True)
class Fala:
    """O resultado de sintetizar um turno: pedaços de áudio e o mapa texto ↔ amostras."""

    texto: str
    pedacos: tuple[Pedaco, ...] = ()
    trechos: tuple[Trecho, ...] = ()
    cancelada_em: int | None = None
    """Índice do pedaço em que o `Cancel` chegou, ou `None` se a síntese terminou."""

    @property
    def amostras_sintetizadas(self) -> int:
        return sum(p.n_amostras for p in self.pedacos)

    def texto_ate(self, amostras_tocadas: int) -> str:
        """O prefixo do texto que corresponde às amostras realmente tocadas (regra 4 da §3.3).

        Pedaço parcialmente tocado entra **proporcional às amostras**, por caractere: é a
        aproximação honesta de "o dono ouviu até aqui" sem alinhamento fonema-a-fonema, e o
        erro fica dentro de um pedaço. Quem precisa de precisão de fonema precisa de
        alinhamento do modelo, que nenhum dos candidatos entrega hoje.
        """
        if amostras_tocadas <= 0:
            return ""
        # O corte é uma posição no texto ORIGINAL, não a junção dos pedaços: juntar os pedaços
        # perderia o espaço entre eles, e o aceite (a) do F1-12 compara caractere a caractere.
        corte = 0
        for trecho in self.trechos:
            if amostras_tocadas >= trecho.fim_em_amostras:
                corte = trecho.fim_no_texto
                continue
            if amostras_tocadas <= trecho.inicio_em_amostras:
                break
            fracao = (amostras_tocadas - trecho.inicio_em_amostras) / max(1, trecho.amostras)
            corte = trecho.inicio_no_texto + round(fracao * len(trecho.texto))
            break
        return self.texto[:corte]


def carregar_voz(identificador: str, *, registro: Path = ARQUIVO_MODELOS) -> str:
    """Devolve a licença da voz, ou recusa. É a porta de licença **no produto** (aceite (d))."""
    estado = estado_registrado(identificador, arquivo=registro)
    if estado is None:
        raise VozRecusada(
            f"voz {identificador!r} não está em licenses/modelos.toml: licença que ninguém "
            "verificou não entra no produto (ADR-0012)"
        )
    if estado == "barrado":
        raise VozRecusada(
            f"voz {identificador!r} está **barrada** no registro — ela existe lá justamente "
            "para ninguém tentar de novo"
        )
    licenca = licenca_registrada(identificador, arquivo=registro) or ""
    categoria = classificar(licenca)
    if categoria is not Categoria.PERMISSIVA:
        raise VozRecusada(
            f"voz {identificador!r} tem licença {licenca!r} ({categoria}), que não é permissiva. "
            "O produto distribui o áudio sintetizado: CC-BY-SA contaminaria o que o dono "
            "distribui, e atribuição obrigatória numa voz é decisão do dono, não do código"
        )
    return licenca


def fatiar(texto: str) -> list[tuple[int, str]]:
    """Fatia o texto em trechos para síntese: o primeiro curto, os outros maiores.

    Corta em pontuação quando ela aparece dentro do limite de palavras — prosódia de pedaço
    que termina em vírgula é melhor do que a de pedaço cortado no meio de uma oração.
    """
    palavras = texto.split()
    if not palavras:
        return []
    fatias: list[tuple[int, str]] = []
    posicao = 0
    indice = 0
    while indice < len(palavras):
        limite = PALAVRAS_DO_PRIMEIRO_PEDACO if not fatias else PALAVRAS_POR_PEDACO
        tomadas = palavras[indice : indice + limite]
        for i, palavra in enumerate(tomadas):
            if palavra.endswith(PONTUACAO_DE_CORTE) and i + 1 < len(tomadas):
                tomadas = tomadas[: i + 1]
                break
        trecho = " ".join(tomadas)
        inicio = texto.index(tomadas[0], posicao)
        fatias.append((inicio, trecho))
        posicao = inicio + len(trecho)
        indice += len(tomadas)
    return fatias


@dataclass(slots=True)
class SintetizadorEmStreaming:
    """Sintetiza por pedaços e para **na hora** quando o cancelamento chega."""

    motor: MotorDeTts
    session_id: str = ""
    epoch: int = 0
    taxa: int = TAXA_PADRAO
    cancelado: Callable[[], bool] = field(default=lambda: False)
    """Consultado antes de sintetizar e antes de escrever cada pedaço."""
    pedacos_descartados: int = 0

    def falar(self, texto: str, *, chunk_id: str = "tts") -> Fala:
        """Sintetiza tudo de uma vez (sem streaming) — útil para medição e para teste."""
        pedacos: list[Pedaco] = []
        trechos: list[Trecho] = []
        for pedaco, trecho in self.pedacos(texto, chunk_id=chunk_id):
            pedacos.append(pedaco)
            trechos.append(trecho)
        cancelada = self.cancelado()
        return Fala(
            texto=texto,
            pedacos=tuple(pedacos),
            trechos=tuple(trechos),
            cancelada_em=len(pedacos) if cancelada else None,
        )

    def pedacos(self, texto: str, *, chunk_id: str = "tts") -> Iterator[tuple[Pedaco, Trecho]]:
        """Gera pedaço por pedaço. Para de gerar assim que o cancelamento aparece."""
        amostras_acumuladas = 0
        for indice, (inicio, trecho_texto) in enumerate(fatiar(texto), start=1):
            if self.cancelado():
                return
            amostras = self.motor.sintetizar(trecho_texto)
            if self.cancelado():
                # O pedaço foi sintetizado e é **descartado**: nada escrito depois do Cancel.
                self.pedacos_descartados += 1
                return
            pedaco = Pedaco(chunk_id=f"{chunk_id}-{indice}", epoch=self.epoch, amostras=amostras)
            trecho = Trecho(
                indice=indice,
                texto=trecho_texto,
                inicio_no_texto=inicio,
                inicio_em_amostras=amostras_acumuladas,
                amostras=len(amostras) // BYTES_POR_AMOSTRA,
            )
            amostras_acumuladas += trecho.amostras
            yield pedaco, trecho


def falar_para(
    sintetizador: SintetizadorEmStreaming,
    texto: str,
    enfileirar: Callable[[Pedaco], bool],
    *,
    chunk_id: str = "tts",
) -> Fala:
    """Sintetiza e entrega ao playback, pedaço por pedaço, parando no cancelamento.

    `enfileirar` é a fila do F1-03: ela devolve `False` quando descarta por epoch velho, e é
    isso que impede pedaço de epoch morto de tocar (aceite (b)).
    """
    pedacos: list[Pedaco] = []
    trechos: list[Trecho] = []
    recusados = 0
    for pedaco, trecho in sintetizador.pedacos(texto, chunk_id=chunk_id):
        if not enfileirar(pedaco):
            recusados += 1
            continue
        pedacos.append(pedaco)
        trechos.append(trecho)
    return Fala(
        texto=texto,
        pedacos=tuple(pedacos),
        trechos=tuple(trechos),
        cancelada_em=len(pedacos) if (sintetizador.cancelado() or recusados) else None,
    )


@dataclass(slots=True)
class MotorParametrico:
    """Voz sem modelo: duração estimada pelas sílabas, PCM determinístico.

    É o motor do CI — não tem fonema e não serve para julgar naturalidade. O nome dele vai no
    relatório, como o do VAD de energia no F1-05.
    """

    nome: str = "parametrico@1"
    voz: str = "parametrico"
    licenca: str = "Apache-2.0"
    ms_por_silaba: float = 95.0
    semente: int = 0

    def sintetizar(self, texto: str) -> bytes:
        from random import Random

        from jarvis.audio_io.sintese import fala_simulada

        silabas = max(1, sum(1 for letra in texto.lower() if letra in "aeiouáéíóúâêôãõà"))
        aleatorio = Random(self.semente + len(texto))  # noqa: S311 — áudio de teste
        return fala_simulada(silabas * self.ms_por_silaba, aleatorio=aleatorio, taxa=TAXA_PADRAO)


def amostras_de(pedacos: Sequence[Pedaco]) -> int:
    return sum(p.n_amostras for p in pedacos)


@dataclass(slots=True)
class MotorPiperOnnx:
    """Voz VITS do piper rodada por `onnxruntime` (MIT), com o **fonemizador injetado**.

    O fonemizador é parâmetro de propósito: ele é a peça GPL (espeak-ng) e, sendo injeção,
    aparece na assinatura em vez de ficar escondido num `import`. `src/` não gera processo —
    quem passa um fonemizador que chama o espeak é `tools/`, onde isso é permitido, e a
    fronteira de licença fica visível no tipo.

    Carregar exige voz registrada e permissiva (`carregar_voz`), então uma voz CC-BY-SA não
    chega nem a abrir o arquivo.
    """

    caminho: Path
    fonemizar: Callable[[str], str]
    voz: str = ""
    identificador_registrado: str = ""
    nome: str = "piper-onnx"
    licenca: str = ""
    taxa_alvo: int = TAXA_PADRAO
    ritmo: float = 1.0
    _sessao: object | None = field(default=None, repr=False)
    _config: dict[str, object] = field(default_factory=dict, repr=False)

    def abrir(self) -> None:
        import json as _json

        import numpy as np
        import onnxruntime as ort

        self.licenca = carregar_voz(self.identificador_registrado or self.voz)
        config = self.caminho.with_suffix(".onnx.json")
        if not self.caminho.exists() or not config.exists():
            raise VozRecusada(
                f"a voz {self.voz} não está em {self.caminho.parent}: os pesos não são "
                "versionados (ver notas do F1-02 para a origem)"
            )
        self._config = _json.loads(config.read_text(encoding="utf-8"))
        opcoes = ort.SessionOptions()
        opcoes.inter_op_num_threads = 1
        opcoes.intra_op_num_threads = 1
        self._sessao = ort.InferenceSession(
            str(self.caminho), sess_options=opcoes, providers=["CPUExecutionProvider"]
        )
        self.nome = f"piper-onnx@{self._config.get('piper_version', '?')}+{self.voz}"
        _ = np  # numpy é usado em `sintetizar`; importado aqui para falhar cedo

    def sintetizar(self, texto: str) -> bytes:
        import numpy as np

        from jarvis.audio_io.quadro import de_int16
        from jarvis.corpus.voz import reamostrar

        if self._sessao is None:
            self.abrir()
        mapa: dict[str, list[int]] = self._config["phoneme_id_map"]  # type: ignore[assignment]
        ids = [*mapa["^"], *mapa["_"]]
        for simbolo in self.fonemizar(texto):
            if simbolo in mapa:
                ids += [*mapa[simbolo], *mapa["_"]]
        ids += [*mapa["$"]]
        sessao = self._sessao
        assert sessao is not None
        saida = sessao.run(  # type: ignore[attr-defined]
            None,
            {
                "input": np.array([ids], dtype=np.int64),
                "input_lengths": np.array([len(ids)], dtype=np.int64),
                # noise_scale = 0 e noise_w = 0: determinismo (ver jarvis.corpus.voz).
                "scales": np.array([0.0, self.ritmo, 0.0], dtype=np.float32),
            },
        )[0].squeeze()
        audio = np.asarray(saida, dtype=np.float64)
        taxa = int(self._config["audio"]["sample_rate"])  # type: ignore[index]
        em_alvo = reamostrar(audio, de=taxa, para=self.taxa_alvo)
        inteiros = np.clip(np.rint(em_alvo * 32767.0), -32768, 32767).astype(np.int64)
        return de_int16([int(v) for v in inteiros])
