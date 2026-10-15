"""Quadro de 20 ms: a unidade que atravessa o `audio-io` (SPEC §2, cartão F1-01).

Formato único em todo o caminho de captura: PCM 16 bits com sinal, mono, 16 kHz, little
endian — o mesmo do corpus (`corpus/turnos/README.md`) e o mesmo que a F0-04 mediu. Um
quadro tem **exatamente** 320 amostras (640 bytes); quadro de outro tamanho é erro, não
arredondamento, porque é com ele que `played_ms` e latência são contados.
"""

from __future__ import annotations

import math
import sys
from array import array
from dataclasses import dataclass
from typing import Final

TAXA_PADRAO: Final = 16_000
CANAIS: Final = 1
BYTES_POR_AMOSTRA: Final = 2
MS_POR_QUADRO: Final = 20
AMOSTRAS_POR_QUADRO: Final = TAXA_PADRAO * MS_POR_QUADRO // 1000
BYTES_POR_QUADRO: Final = AMOSTRAS_POR_QUADRO * BYTES_POR_AMOSTRA
AMPLITUDE_MAXIMA: Final = 32_768.0
PISO_DB: Final = -120.0
"""Silêncio digital em relatório é piso declarado, não `-inf`: tabela com -inf não soma."""


def como_int16(amostras: bytes) -> array[int]:
    """Bytes PCM16 little endian como vetor de inteiros (independe da ordem da máquina)."""
    vetor: array[int] = array("h")
    vetor.frombytes(amostras)
    if sys.byteorder != "little":
        vetor.byteswap()
    return vetor


def de_int16(valores: array[int] | list[int]) -> bytes:
    """Inverso de `como_int16`: vetor de inteiros em bytes PCM16 little endian."""
    vetor: array[int] = array("h", valores)
    if sys.byteorder != "little":
        vetor.byteswap()
    return vetor.tobytes()


def energia_db(amostras: bytes) -> float:
    """Energia RMS em dBFS, com piso declarado para o silêncio digital."""
    vetor = como_int16(amostras)
    if not vetor:
        return PISO_DB
    soma = 0.0
    for valor in vetor:
        soma += float(valor) * float(valor)
    rms = math.sqrt(soma / len(vetor))
    if rms <= 0.0:
        return PISO_DB
    return max(PISO_DB, 20.0 * math.log10(rms / AMPLITUDE_MAXIMA))


@dataclass(frozen=True, slots=True)
class Quadro:
    """20 ms de áudio capturado, com o instante do relógio injetado (F1-01)."""

    indice: int
    amostras: bytes
    ts_mono_ns: int
    taxa: int = TAXA_PADRAO

    def __post_init__(self) -> None:
        if len(self.amostras) != BYTES_POR_QUADRO:
            raise ValueError(
                f"quadro tem {len(self.amostras)} bytes; o contrato é {BYTES_POR_QUADRO} "
                f"({AMOSTRAS_POR_QUADRO} amostras de 20 ms a {TAXA_PADRAO} Hz)"
            )

    @property
    def n_amostras(self) -> int:
        return len(self.amostras) // BYTES_POR_AMOSTRA

    @property
    def duracao_ms(self) -> float:
        return 1000.0 * self.n_amostras / self.taxa

    @property
    def energia_db(self) -> float:
        return energia_db(self.amostras)

    def valores(self) -> array[int]:
        return como_int16(self.amostras)


def em_quadros(
    amostras: bytes, *, indice_inicial: int = 0, ts_inicial_ns: int = 0, taxa: int = TAXA_PADRAO
) -> list[Quadro]:
    """Fatia um bloco em quadros de 20 ms, completando o último com silêncio (declarado).

    Completar o último quadro é escolha explícita: o contrato é quadro de tamanho fixo, e
    arquivo de corpus não termina em múltiplo de 20 ms. Quem conta `played_ms` conta amostra
    consumida, não quadro, então o preenchimento não vira áudio contado como tocado.
    """
    quadros: list[Quadro] = []
    passo_ns = round(MS_POR_QUADRO * 1_000_000)
    for i in range(0, len(amostras), BYTES_POR_QUADRO):
        pedaco = amostras[i : i + BYTES_POR_QUADRO]
        if len(pedaco) < BYTES_POR_QUADRO:
            pedaco = pedaco + bytes(BYTES_POR_QUADRO - len(pedaco))
        indice = indice_inicial + len(quadros)
        quadros.append(
            Quadro(
                indice=indice,
                amostras=pedaco,
                ts_mono_ns=ts_inicial_ns + len(quadros) * passo_ns,
                taxa=taxa,
            )
        )
    return quadros
