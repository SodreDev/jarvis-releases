"""TTS em streaming, cancelável e com licença verificada no carregamento (cartão F1-09).

Três coisas que este módulo garante, e que são aceite do cartão:

1. **Interrupção no meio da síntese, não só no meio da fila.** O sintetizador consulta o
   cancelamento **antes de sintetizar** cada pedaço e **antes de escrever** o que sintetizou.
   O pedaço em voo é **descartado**, não escrito: depois do `Cancel`, nenhuma amostra nova chega
   ao sumidouro. A síntese de um pedaço local é atômica (o modelo não é interrompível por dentro),
   mas a janela antecipada é limitada e os adaptadores remotos também consultam o cancelamento
   enquanto recebem o corpo.
2. **Licença no carregamento, não no CI.** `carregar_voz` consulta `licenses/modelos.toml` e
   recusa voz que não esteja registrada ou cuja licença não seja **permissiva**. CC-BY-SA não
   carrega: *ShareAlike* numa voz contamina o áudio que o produto distribui. `coqui/XTTS-v2`
   está barrado no registro e, por estar barrado, também não carrega.
3. **Mapa texto ↔ amostras.** Cada pedaço sabe qual trecho do texto ele é e em que amostra
   começa. É esse mapa que deixa o histórico (F1-12) guardar **só o prefixo tocado** em vez do
   texto que foi enfileirado.

**A interface do motor mora em `jarvis.voz` desde a ADR-0017** e é reexportada aqui; o motor
passou a declarar `onde` (local) e `registrado` — o id pelo qual o portão de motores decide se
este caminho (voz + fonemizador + runtime) pode rodar. São **duas** portas, e elas perguntam
coisas diferentes: `exigir_motor` olha o caminho, `carregar_voz` olha a voz.

**Pendência de licença do caminho de produto, declarada:** as quatro vozes pt-BR do
`rhasspy/piper-voices` usam fonemas do **espeak-ng** (`phoneme_type: espeak`), que é GPL-3.0 —
verificado voz por voz no cartão F1-09, incluindo a `edresson`, que não declara o campo e usa o
mesmo inventário IPA. Fonemizar pt-BR com licença permissiva não existe pronto. No F1-02 isso
não era problema (o espeak rodava **fora** do produto, gerando corpus); aqui é, porque o TTS
roda **no** produto. As opções estão nas notas do executor; a escolha é do dono (F1-16).
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturoAindaNaoPronto
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.audio_io.playback import Pedaco
from jarvis.audio_io.quadro import BYTES_POR_AMOSTRA, TAXA_PADRAO
from jarvis.fatiador import (
    PALAVRAS_DO_PRIMEIRO_PEDACO,
    PALAVRAS_MINIMAS_POR_PEDACO,
    PALAVRAS_POR_PEDACO,
    PONTUACAO_DE_CORTE,
    fatiar_tudo,
)
from jarvis.licencas import (
    ARQUIVO_MODELOS,
    Categoria,
    classificar,
    estado_registrado,
    licenca_registrada,
)
from jarvis.voz.interface import MotorDeTts, Onde
from jarvis.voz.registro import exigir_motor

__all__ = [
    "PALAVRAS_DO_PRIMEIRO_PEDACO",
    "PALAVRAS_MINIMAS_POR_PEDACO",
    "PALAVRAS_POR_PEDACO",
    "PONTUACAO_DE_CORTE",
    "Fala",
    "MotorDeTts",
    "MotorParametrico",
    "MotorPiperOnnx",
    "SintetizadorEmStreaming",
    "Trecho",
    "VozRecusada",
    "amostras_de",
    "carregar_voz",
    "falar_para",
    "fatiar",
]

PREFETCH_DE_SINTESE: Final = 2
"""Enquanto N toca, pelo menos N+1 e N+2 podem ser sintetizados em paralelo."""
MAXIMO_DE_SINTESES_PENDENTES: Final = PREFETCH_DE_SINTESE + 1
"""N em preparação mais duas futuras; limita CPU, rede, memória e descarte num barge-in."""
INTERVALO_DE_CANCELAMENTO_S: Final = 0.01


class VozRecusada(RuntimeError):
    """A voz não carrega: não está registrada, está barrada ou a licença não é permissiva."""


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


@dataclass(frozen=True, slots=True)
class _SintesePendente:
    indice: int
    inicio: int
    texto: str
    futuro: Future[bytes | None]


@dataclass(frozen=True, slots=True)
class _FalhaNaEntrada:
    causa: BaseException


@dataclass(frozen=True, slots=True)
class _FimDaEntrada:
    pass


_FIM_DA_ENTRADA = _FimDaEntrada()
_EventoDaSintese = _SintesePendente | _FalhaNaEntrada | _FimDaEntrada


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
    """Fatia o texto em lotes para síntese, sem cortar token por caractere.

    Depois do piso de palavras, corta em pontuação quando ela aparece antes do teto — prosódia
    de pedaço que termina em vírgula é melhor do que a de pedaço cortado no meio de uma oração.
    A regra mora em `jarvis.fatiador` desde a ADR-0025, para o `s2` cortar o stream com a
    **mesma** regra: aqui ela recebe o texto de uma vez.
    """
    return [(pedaco.inicio, pedaco.texto) for pedaco in fatiar_tudo(texto)]


@dataclass(slots=True)
class SintetizadorEmStreaming:
    """Sintetiza antecipadamente, entrega em ordem e para quando o cancelamento chega.

    O produtor de texto e até três sínteses rodam fora da linha que toca o áudio. A fila é
    limitada: depois de N ficar pronto, só há espaço para três resultados futuros. Assim o
    playback pode consumir N enquanto N+1 e N+2 já estão em curso, sem transformar uma resposta
    longa em trabalho ilimitado. A ordem de conclusão dos providers não muda a ordem de entrega.
    """

    motor: MotorDeTts
    session_id: str = ""
    epoch: int = 0
    taxa: int = TAXA_PADRAO
    cancelado: Callable[[], bool] = field(default=lambda: False)
    """Consultado antes de sintetizar e antes de escrever cada pedaço."""
    pedacos_descartados: int = 0
    ao_esperar: Callable[[], object] = field(default=lambda: None)
    """Na linha do consumidor: mantém o controle responsivo enquanto texto/áudio não chega."""
    pronunciar: Callable[[str], str] = field(default=lambda texto: texto)
    """A grafia → a pronúncia do dono (`jarvis.voz.vocabulario`, ADR-0044), aplicada só ao texto
    que o **motor** recebe: o `Trecho` (a tela, a conversa, o eco que a vigia reconhece) fica com a
    grafia certa. É aqui, e não em cada motor, para valer igual na piper, na nuvem e no
    OmniVoice."""

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
        return self._sintetizar(fatiar(texto), chunk_id=chunk_id)

    def pedacos_do_stream(
        self, trechos: Iterable[tuple[int, str]], *, chunk_id: str = "tts"
    ) -> Iterator[tuple[Pedaco, Trecho]]:
        """O mesmo, com os trechos **já cortados** chegando do `s2` (ADR-0025, regra 10).

        `trechos` é `(inicio_no_texto, texto)`, como o `fatiar` devolve; quem monta isso a
        partir dos `ResponseChunk` do epoch corrente é `jarvis.s2.stream`. Trecho vazio (o fim
        de uma resposta que acabou numa pontuação) não vira síntese.
        """
        return self._sintetizar(trechos, chunk_id=chunk_id)

    def _sintetizar(
        self, trechos: Iterable[tuple[int, str]], *, chunk_id: str
    ) -> Iterator[tuple[Pedaco, Trecho]]:
        """Agenda sínteses em paralelo, mas só publica cada resultado na ordem da entrada."""
        entrada = iter(trechos)
        pendentes: queue.Queue[_EventoDaSintese] = queue.Queue(maxsize=MAXIMO_DE_SINTESES_PENDENTES)
        vagas = threading.BoundedSemaphore(MAXIMO_DE_SINTESES_PENDENTES)
        parar = threading.Event()
        futuros: set[Future[bytes | None]] = set()
        tranca_dos_futuros = threading.Lock()
        executor = ThreadPoolExecutor(
            max_workers=MAXIMO_DE_SINTESES_PENDENTES,
            thread_name_prefix="jarvis-tts",
        )

        def colocar(evento: _EventoDaSintese) -> bool:
            while not parar.is_set():
                try:
                    pendentes.put(evento, timeout=INTERVALO_DE_CANCELAMENTO_S)
                    return True
                except queue.Full:
                    continue
            return False

        def sintetizar_se_vivo(texto: str) -> bytes | None:
            if parar.is_set() or self.cancelado():
                return None
            amostras = self.motor.sintetizar(self.pronunciar(texto))
            if parar.is_set() or self.cancelado():
                return None
            return amostras

        def produzir() -> None:
            indice = 0
            try:
                while not parar.is_set() and not self.cancelado():
                    while not vagas.acquire(timeout=INTERVALO_DE_CANCELAMENTO_S):
                        if parar.is_set() or self.cancelado():
                            return
                    if parar.is_set() or self.cancelado():
                        vagas.release()
                        return
                    try:
                        inicio, trecho_texto = next(entrada)
                    except StopIteration:
                        vagas.release()
                        return
                    if not trecho_texto:
                        vagas.release()
                        continue
                    with tranca_dos_futuros:
                        # O consumidor pode fechar enquanto next(entrada) está bloqueado.
                        # Não submeter depois de shutdown nem iniciar síntese desse texto.
                        if parar.is_set() or self.cancelado():
                            vagas.release()
                            return
                        futuro = executor.submit(sintetizar_se_vivo, trecho_texto)
                        futuros.add(futuro)
                    indice += 1
                    if not colocar(_SintesePendente(indice, inicio, trecho_texto, futuro)):
                        futuro.cancel()
                        vagas.release()
                        return
            except BaseException as causa:
                colocar(_FalhaNaEntrada(causa))
            finally:
                try:
                    # Só o produtor fecha a entrada: fechar um gerador que está executando
                    # em outra linha levantaria ValueError e deixaria seu finally para trás.
                    fechar = getattr(entrada, "close", None)
                    if fechar is not None:
                        fechar()
                except BaseException as causa:
                    colocar(_FalhaNaEntrada(causa))
                finally:
                    colocar(_FIM_DA_ENTRADA)

        produtor = threading.Thread(target=produzir, name="jarvis-tts-produtor", daemon=True)
        produtor.start()
        amostras_acumuladas = 0
        try:
            while True:
                self.ao_esperar()
                if self.cancelado():
                    return
                try:
                    evento = pendentes.get(timeout=INTERVALO_DE_CANCELAMENTO_S)
                except queue.Empty:
                    continue
                if isinstance(evento, _FimDaEntrada):
                    return
                if isinstance(evento, _FalhaNaEntrada):
                    raise evento.causa

                futuro = evento.futuro
                amostras: bytes | None = None
                try:
                    while True:
                        self.ao_esperar()
                        if self.cancelado():
                            futuro.cancel()
                            if futuro.done() and not futuro.cancelled():
                                self.pedacos_descartados += 1
                            return
                        try:
                            amostras = futuro.result(timeout=INTERVALO_DE_CANCELAMENTO_S)
                            break
                        except FuturoAindaNaoPronto:
                            # Em Python, o timeout do provider pode ter a mesma classe do
                            # timeout de `Future.result`. Se o futuro já acabou, a segunda
                            # chamada precisa propagar a falha real em vez de esperar para sempre.
                            if futuro.done():
                                amostras = futuro.result()
                                break
                            continue
                finally:
                    with tranca_dos_futuros:
                        futuros.discard(futuro)
                    vagas.release()
                if amostras is None or self.cancelado():
                    # O provider terminou depois do Cancel (ou nem chegou a começar): nada é
                    # publicado. Motor local é atômico; motor remoto também abandona o corpo.
                    self.pedacos_descartados += 1
                    return
                pedaco = Pedaco(
                    chunk_id=f"{chunk_id}-{evento.indice}",
                    epoch=self.epoch,
                    amostras=amostras,
                )
                trecho = Trecho(
                    indice=evento.indice,
                    texto=evento.texto,
                    inicio_no_texto=evento.inicio,
                    inicio_em_amostras=amostras_acumuladas,
                    amostras=len(amostras) // BYTES_POR_AMOSTRA,
                )
                amostras_acumuladas += trecho.amostras
                yield pedaco, trecho
        finally:
            parar.set()
            with tranca_dos_futuros:
                restantes = tuple(futuros)
            for futuro in restantes:
                futuro.cancel()
            executor.shutdown(wait=False, cancel_futures=True)


def falar_para(
    sintetizador: SintetizadorEmStreaming,
    texto: str,
    enfileirar: Callable[[Pedaco], bool],
    *,
    chunk_id: str = "tts",
) -> Fala:
    """Sintetiza e entrega ao playback, pedaço por pedaço, parando no cancelamento.

    `enfileirar` é a fila do F1-03: ela devolve `False` quando descarta por epoch velho, e é
    isso que impede pedaço de epoch morto de tocar (aceite (b)). A primeira recusa fecha o
    pipeline inteiro: não há razão para continuar gerando áudio que a fila já declarou morto.
    """
    pedacos: list[Pedaco] = []
    trechos: list[Trecho] = []
    recusados = 0
    fluxo = sintetizador.pedacos(texto, chunk_id=chunk_id)
    try:
        for pedaco, trecho in fluxo:
            if not enfileirar(pedaco):
                recusados += 1
                break
            pedacos.append(pedaco)
            trechos.append(trecho)
    finally:
        fechar = getattr(fluxo, "close", None)
        if fechar is not None:
            fechar()
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
    onde: Onde = Onde.LOCAL
    registrado: str = "tts-parametrico"
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
    onde: Onde = Onde.LOCAL
    registrado: str = "tts-piper-epitran"
    """Id no `licenses/motores.toml`. O padrão é o caminho **local e permissivo** (ADR-0016,
    opção B); a linha de base com espeak-ng é `tts-piper-espeak`, que só abre com
    `permitir_fora_do_produto`."""
    permitir_fora_do_produto: bool = False
    """Só `tools/` passa `True`, e só para o motor cujo registro diz `fora_do_produto`."""
    taxa_alvo: int = TAXA_PADRAO
    ritmo: float = 1.0
    fonemas_descartados: int = 0
    """Quantos símbolos o fonemizador produziu e o inventário da voz não conhece.

    **Isto é o achado da ADR-0017 virando número.** `sintetizar` descarta o que não está no
    mapa — a ADR-0016 dizia que isso levantava erro, e não levantava: descartava em silêncio, e
    foi assim que o `ʷ` do `epitran` sumiu sem ninguém notar. Trocar descarte por erro é emenda
    da ADR-0016 e decisão do dono; **medir** não é, e `jarvis.voz.fonemizador.conferir_cobertura`
    mede antes de sintetizar."""
    simbolos_descartados: dict[str, int] = field(default_factory=dict)
    """Quais símbolos, e quantas vezes cada um — para o relatório dizer o que falta mapear."""
    _sessao: object | None = field(default=None, repr=False)
    _config: dict[str, object] = field(default_factory=dict, repr=False)

    def abrir(self) -> None:
        import json as _json

        import numpy as np
        import onnxruntime as ort

        # Duas portas, e elas perguntam coisas diferentes: `exigir_motor` diz se **este
        # caminho** (voz + fonemizador + runtime) pode rodar; `carregar_voz` diz se **a voz**
        # pode entrar no produto. Um motor registrado com voz barrada continua barrado.
        exigir_motor(self.registrado, permitir_fora_do_produto=self.permitir_fora_do_produto)
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
                continue
            self.fonemas_descartados += 1
            self.simbolos_descartados[simbolo] = self.simbolos_descartados.get(simbolo, 0) + 1
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
