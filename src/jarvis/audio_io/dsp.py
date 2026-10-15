"""AEC, NR e AGC: a cadeia que faz o assistente não se ouvir falar (cartão F1-04).

**Por que é código nosso e não biblioteca.** A porta de licença e o P11 (roda nos dois
sistemas) eliminaram os dois candidatos do cartão:

- `webrtc-audio-processing` no PyPI está na 0.1.3 (2018), só com `sdist` e rodas de Python 2.7
  e 3.6 para ARM: não há roda para CPython 3.12, e muito menos para Windows;
- `speexdsp` no PyPI é só `sdist` (precisa de Cython e dos cabeçalhos de `libspeexdsp`), e
  `speexdsp-ns` tem rodas 3.12 **só** manylinux — e faz **supressão de ruído**, não AEC.

Então a cadeia é nossa, em `numpy` (BSD-3, com roda para Linux e Windows em CPython 3.12). O
custo declarado: é um AEC honesto de filtro adaptativo no domínio da frequência (PBFDAF), não
o WebRTC — sem processamento não linear, sem detector de duplo-falar de nível de produto e sem
*comfort noise*. O que ele tem de fazer é o aceite (b) do cartão: com AEC, o VAD não dispara
no nosso próprio áudio.

Ordem da cadeia (a do cartão): **AEC → NR → AGC**. AEC primeiro porque o eco é o sinal mais
alto e mais correlacionado; NR depois, sobre o resíduo; AGC por último, para não amplificar
eco nem ruído.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np

from jarvis.audio_io.quadro import (
    AMOSTRAS_POR_QUADRO,
    PISO_DB,
    TAXA_PADRAO,
    como_int16,
    de_int16,
)

ESCALA: Final = 32768.0
LIMIAR_DO_DETECTOR_DB: Final = -45.0
"""O mesmo limiar do `DetectorDeEnergia`. Duplicado aqui para `dsp` não importar `energia`
(a cadeia é a camada de baixo); um teste prova que os dois números são o mesmo."""
COMPRIMENTO_PADRAO_MS: Final = 400.0
"""Cauda coberta pelo filtro. Cobre os 240 ms de atraso do aceite (a) e ainda sobra sala."""
PASSO_PADRAO: Final = 0.5
"""Passo do NLMS normalizado: 0,5 converge em poucos segundos sem oscilar nos testes."""
EPSILON: Final = 1e-8


def para_float(amostras: bytes) -> np.ndarray[Any, np.dtype[np.float64]]:
    return np.asarray(como_int16(amostras), dtype=np.float64) / ESCALA


def para_bytes(sinal: np.ndarray[Any, np.dtype[np.float64]]) -> bytes:
    inteiros = np.clip(np.rint(sinal * ESCALA), -32768, 32767).astype(np.int64)
    return de_int16([int(v) for v in inteiros])


def energia_db_de(sinal: np.ndarray[Any, np.dtype[np.float64]]) -> float:
    if sinal.size == 0:
        return PISO_DB
    rms = float(np.sqrt(np.mean(np.square(sinal))))
    return PISO_DB if rms <= 0.0 else max(PISO_DB, 20.0 * float(np.log10(rms)))


def erle_db(
    microfone: np.ndarray[Any, np.dtype[np.float64]],
    residuo: np.ndarray[Any, np.dtype[np.float64]],
) -> float:
    """*Echo Return Loss Enhancement*: quanto do que entrou no microfone a AEC removeu."""
    entrada = float(np.sum(np.square(microfone)))
    saida = float(np.sum(np.square(residuo)))
    if entrada <= 0.0:
        return 0.0
    return 10.0 * float(np.log10(entrada / max(saida, EPSILON)))


@dataclass(slots=True)
class CanceladorDeEco:
    """Filtro adaptativo por blocos no domínio da frequência (PBFDAF), 20 ms por bloco.

    Cada bloco de 20 ms vira um espectro de 640 pontos (overlap-save). O filtro é uma pilha de
    `particoes` espectros, uma por bloco de atraso coberto; a estimativa do eco é a soma dos
    produtos, e a atualização é NLMS por partição.

    Duplo-falar: quando a energia do resíduo é muito maior que a do eco estimado, quem está
    falando é o dono (não é eco), e o passo é **congelado** para o filtro não divergir
    aprendendo a voz dele. É proteção simples e declarada — não é o detector de duplo-falar do
    WebRTC.
    """

    taxa: int = TAXA_PADRAO
    bloco: int = AMOSTRAS_POR_QUADRO
    comprimento_ms: float = COMPRIMENTO_PADRAO_MS
    passo: float = PASSO_PADRAO
    particoes: int = field(init=False)
    _pesos: np.ndarray[Any, np.dtype[np.complex128]] = field(init=False, repr=False)
    _referencias: np.ndarray[Any, np.dtype[np.complex128]] = field(init=False, repr=False)
    _cauda: np.ndarray[Any, np.dtype[np.float64]] = field(init=False, repr=False)
    _potencia: np.ndarray[Any, np.dtype[np.float64]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.particoes = max(1, round(self.comprimento_ms * self.taxa / 1000 / self.bloco))
        n_fft = 2 * self.bloco
        tamanho = n_fft // 2 + 1
        self._pesos = np.zeros((self.particoes, tamanho), dtype=np.complex128)
        self._referencias = np.zeros((self.particoes, tamanho), dtype=np.complex128)
        self._cauda = np.zeros(self.bloco, dtype=np.float64)
        self._potencia = np.zeros(tamanho, dtype=np.float64)

    def zerar(self) -> None:
        """Esquece o que aprendeu. É o que fazer quando o caminho acústico muda de verdade."""
        self._pesos[:] = 0.0
        self._referencias[:] = 0.0
        self._cauda[:] = 0.0
        self._potencia[:] = 0.0

    def processar(
        self,
        microfone: np.ndarray[Any, np.dtype[np.float64]],
        referencia: np.ndarray[Any, np.dtype[np.float64]],
    ) -> tuple[np.ndarray[Any, np.dtype[np.float64]], float]:
        """Devolve (resíduo, eco estimado em energia) para um bloco de 20 ms."""
        bloco = self.bloco
        entrada = np.concatenate([self._cauda, referencia])
        self._cauda = referencia.copy()
        espectro = np.fft.rfft(entrada)

        self._referencias = np.roll(self._referencias, 1, axis=0)
        self._referencias[0] = espectro

        estimativa_espectral = np.sum(self._pesos * self._referencias, axis=0)
        estimativa = np.fft.irfft(estimativa_espectral)[bloco:]
        residuo = microfone - estimativa

        # NLMS normalizado **por bin**: potência média da referência naquele bin, vezes o
        # número de partições. Normalizar pela potência total (escalar) foi a primeira versão
        # e não convergia: o passo efetivo ficava centenas de vezes menor do que precisa.
        self._potencia = 0.9 * self._potencia + 0.1 * np.abs(espectro) ** 2
        energia_eco = float(np.sum(np.square(estimativa)))
        energia_residuo = float(np.sum(np.square(residuo)))
        energia_referencia = float(np.sum(np.square(referencia)))
        # Duplo-falar comparado com a REFERÊNCIA, não com o eco estimado: no primeiro bloco o
        # eco estimado é zero (pesos zerados) e comparar com ele congelava o filtro para
        # sempre — o aceite (a) media 0,0 dB de ERLE por causa disso.
        duplo_falar = energia_residuo > 8.0 * max(energia_referencia, EPSILON)
        if not duplo_falar:
            erro = np.fft.rfft(np.concatenate([np.zeros(bloco), residuo]))
            normalizador = self.particoes * self._potencia + EPSILON
            self._pesos += self.passo * np.conj(self._referencias) * (erro / normalizador)
        return residuo, energia_eco


@dataclass(slots=True)
class SupressorDeRuido:
    """Subtração espectral com piso de ruído por estatística de mínimos (NR da cadeia).

    Simples de propósito: o cartão pede "um NR razoável", não produto. O piso de ganho evita o
    artefato clássico (voz com "borbulha") ao custo de deixar passar algum ruído.
    """

    bloco: int = AMOSTRAS_POR_QUADRO
    piso_de_ganho: float = 0.1
    adaptacao: float = 0.05
    _ruido: np.ndarray[Any, np.dtype[np.float64]] | None = field(default=None, repr=False)
    _janela: np.ndarray[Any, np.dtype[np.float64]] | None = field(default=None, repr=False)

    def processar(
        self, sinal: np.ndarray[Any, np.dtype[np.float64]]
    ) -> np.ndarray[Any, np.dtype[np.float64]]:
        if self._janela is None or self._janela.size != sinal.size:
            self._janela = np.hanning(sinal.size)
        espectro = np.fft.rfft(sinal * self._janela)
        magnitude = np.abs(espectro)
        if self._ruido is None:
            self._ruido = magnitude.copy()
        else:
            subindo = magnitude > self._ruido
            self._ruido = np.where(
                subindo,
                self._ruido + self.adaptacao * (magnitude - self._ruido),
                self._ruido + 0.5 * (magnitude - self._ruido),
            )
        ganho = np.maximum(
            self.piso_de_ganho, (magnitude - self._ruido) / np.maximum(magnitude, EPSILON)
        )
        limpo = np.fft.irfft(espectro * ganho, n=sinal.size)
        return np.asarray(limpo, dtype=np.float64)


@dataclass(slots=True)
class ControleDeGanho:
    """AGC lento com limitador: aproxima o RMS do alvo sem bombear nem estourar.

    **O limiar de silêncio é o do detector, de propósito** (`LIMIAR_PADRAO_DB`). Medido no
    cartão F1-04: com limiar de -60 dBFS, o AGC perseguia o alvo em cima do **resíduo de eco**
    (-67 dBFS), empurrava o resíduo para -49 dBFS e fazia o detector disparar em 20 a 30
    quadros de 250 na condição de eco mais forte — ou seja, o AGC desfazia o trabalho da AEC.
    Com o limiar alinhado ao do detector, zero disparos nas nove condições.
    """

    alvo_dbfs: float = -20.0
    passo: float = 0.05
    ganho_maximo_db: float = 20.0
    ganho_db: float = 0.0
    limiar_de_silencio_dbfs: float = LIMIAR_DO_DETECTOR_DB

    def processar(
        self, sinal: np.ndarray[Any, np.dtype[np.float64]]
    ) -> np.ndarray[Any, np.dtype[np.float64]]:
        nivel = energia_db_de(sinal)
        if nivel > self.limiar_de_silencio_dbfs:
            # Só persegue o alvo quando há sinal: perseguir silêncio é amplificar ruído.
            desejado = max(-self.ganho_maximo_db, min(self.ganho_maximo_db, self.alvo_dbfs - nivel))
            self.ganho_db += self.passo * (desejado - self.ganho_db)
        fator = 10.0 ** (self.ganho_db / 20.0)
        return np.asarray(np.clip(sinal * fator, -1.0, 1.0), dtype=np.float64)
