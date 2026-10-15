"""Gerador determinístico de áudio de teste: fala simulada, silêncio, ruído rosa e eco.

Cartão F1-01. Tudo aqui é `random.Random(semente)` e `math` da biblioteca padrão — nenhuma
dependência nova e nenhum modelo. Mesma semente, mesmos bytes **na mesma máquina**: o
Mersenne Twister é igual em toda plataforma, mas `math.sin` sai da libm do sistema, então
não comparamos hash entre sistemas operacionais (comparamos duas execuções na mesma
máquina, que é o que o aceite (b) do cartão pede).

O que isto **não** é: voz. `fala_simulada` tem envelope silábico e formantes para que um
detector de energia e um VAD vejam fala/silêncio alternando; não tem fonema, então não
serve para medir ASR nem detector semântico. Voz de verdade (TTS com licença verificada)
é o cartão F1-02.
"""

from __future__ import annotations

import math
from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from random import Random
from typing import Final

from jarvis.audio_io.quadro import (
    AMPLITUDE_MAXIMA,
    BYTES_POR_AMOSTRA,
    TAXA_PADRAO,
    como_int16,
    de_int16,
)

MINIMO_INT16: Final = -32_768
MAXIMO_INT16: Final = 32_767
FORMANTES_HZ: Final[tuple[float, ...]] = (500.0, 1_500.0, 2_500.0)
"""Três formantes de vogal média — o suficiente para parecer fala para o detector."""
SILABAS_POR_S: Final = 4.5


def _n_amostras(duracao_ms: float, taxa: int) -> int:
    return max(0, round(taxa * duracao_ms / 1000.0))


def _saturar(valor: float) -> int:
    return max(MINIMO_INT16, min(MAXIMO_INT16, round(valor)))


def silencio(duracao_ms: float, *, taxa: int = TAXA_PADRAO) -> bytes:
    """Silêncio digital: zero. (Ruído de fundo de sala é `ruido_rosa` com ganho baixo.)"""
    return bytes(_n_amostras(duracao_ms, taxa) * BYTES_POR_AMOSTRA)


def fala_simulada(
    duracao_ms: float,
    *,
    aleatorio: Random,
    taxa: int = TAXA_PADRAO,
    f0_hz: float = 110.0,
    pico: float = 0.35,
) -> bytes:
    """Fala simulada: harmônicos sob envelope silábico, com jitter de f0 e de amplitude."""
    total = _n_amostras(duracao_ms, taxa)
    fase_silaba = aleatorio.random() * math.tau
    jitter_f0 = 1.0 + 0.04 * (aleatorio.random() - 0.5)
    f0 = f0_hz * jitter_f0
    pesos = [1.0, 0.6, 0.35]
    valores: array[int] = array("h")
    for n in range(total):
        t = n / taxa
        silaba = 0.5 * (1.0 - math.cos(math.tau * SILABAS_POR_S * t + fase_silaba))
        # Piso de 0,3 no envelope: fala de verdade não cai para o silêncio digital entre
        # sílabas. Sem o piso, um detector sem histerese (o do F1-01) oscila a cada sílaba —
        # e o remédio certo é o gerador parecer com voz, não o detector ganhar histerese
        # antes do cartão dele (F1-05).
        envelope = 0.3 + 0.7 * silaba**1.5
        amostra = 0.0
        for peso, formante in zip(pesos, FORMANTES_HZ, strict=True):
            harmonico = max(1.0, round(formante / f0)) * f0
            amostra += peso * math.sin(math.tau * harmonico * t)
        amostra += 0.05 * (aleatorio.random() * 2.0 - 1.0)
        valores.append(_saturar(pico * AMPLITUDE_MAXIMA * envelope * amostra / sum(pesos)))
    return de_int16(valores)


def ruido_rosa(
    duracao_ms: float, *, aleatorio: Random, taxa: int = TAXA_PADRAO, pico: float = 0.08
) -> bytes:
    """Ruído rosa por Voss-McCartney (oito geradores em oitavas) — ruído de sala plausível."""
    total = _n_amostras(duracao_ms, taxa)
    n_geradores = 8
    geradores = [aleatorio.random() * 2.0 - 1.0 for _ in range(n_geradores)]
    soma = sum(geradores)
    valores: array[int] = array("h")
    for n in range(1, total + 1):
        mudanca = n ^ (n - 1)
        for i in range(n_geradores):
            if mudanca & (1 << i):
                soma -= geradores[i]
                geradores[i] = aleatorio.random() * 2.0 - 1.0
                soma += geradores[i]
        valores.append(_saturar(pico * AMPLITUDE_MAXIMA * soma / n_geradores))
    return de_int16(valores)


def aplicar_ganho_db(amostras: bytes, db: float) -> bytes:
    """Ganho linear em dB, com saturação (nunca estoura o int16 em silêncio)."""
    if db == 0.0:
        return amostras
    fator = 10.0 ** (db / 20.0)
    return de_int16(array("h", (_saturar(v * fator) for v in como_int16(amostras))))


def atrasar(amostras: bytes, *, atraso_ms: float, taxa: int = TAXA_PADRAO) -> bytes:
    """Mesmo sinal, deslocado para a frente — a parte do eco que depende do caminho."""
    return silencio(atraso_ms, taxa=taxa) + amostras


def misturar(*sinais: bytes) -> bytes:
    """Soma com saturação; o resultado tem o tamanho do maior sinal."""
    if not sinais:
        return b""
    vetores = [como_int16(sinal) for sinal in sinais]
    tamanho = max(len(v) for v in vetores)
    saida: array[int] = array("h", bytes(tamanho * BYTES_POR_AMOSTRA))
    for vetor in vetores:
        for i, valor in enumerate(vetor):
            saida[i] = _saturar(saida[i] + valor)
    return de_int16(saida)


def eco(sinal: bytes, *, atraso_ms: float, ganho_db: float, taxa: int = TAXA_PADRAO) -> bytes:
    """Cópia atrasada e atenuada de um sinal — o eco do nosso próprio playback (F1-04)."""
    return atrasar(aplicar_ganho_db(sinal, ganho_db), atraso_ms=atraso_ms, taxa=taxa)


class TipoDeTrecho(StrEnum):
    """Os quatro materiais que a fonte sintética sabe produzir."""

    FALA = "fala"
    SILENCIO = "silencio"
    RUIDO_ROSA = "ruido_rosa"
    ECO = "eco"


@dataclass(frozen=True, slots=True)
class Trecho:
    """Um pedaço do roteiro da fonte sintética.

    `ganho_db` e `atraso_ms` só têm efeito em `ECO` e em `RUIDO_ROSA` (ganho). O eco é do
    sinal **já gerado** até ali: é o que simula o assistente se ouvindo falar (F1-04).
    """

    tipo: TipoDeTrecho
    duracao_ms: float
    ganho_db: float = 0.0
    atraso_ms: float = 0.0


ROTEIRO_PADRAO: Final[tuple[Trecho, ...]] = (
    Trecho(TipoDeTrecho.SILENCIO, 200.0),
    Trecho(TipoDeTrecho.FALA, 600.0),
    Trecho(TipoDeTrecho.SILENCIO, 300.0),
    Trecho(TipoDeTrecho.FALA, 400.0),
    Trecho(TipoDeTrecho.SILENCIO, 200.0),
)


def _ajustar(amostras: bytes, duracao_ms: float, taxa: int) -> bytes:
    alvo = _n_amostras(duracao_ms, taxa) * BYTES_POR_AMOSTRA
    if len(amostras) >= alvo:
        return amostras[:alvo]
    return amostras + bytes(alvo - len(amostras))


def gerar(
    roteiro: Sequence[Trecho] = ROTEIRO_PADRAO, *, semente: int = 0, taxa: int = TAXA_PADRAO
) -> bytes:
    """Monta o roteiro inteiro. Mesma semente e mesmo roteiro ⇒ mesmos bytes."""
    aleatorio = Random(semente)  # noqa: S311 — áudio de teste, não criptografia
    gerado = b""
    for trecho in roteiro:
        if trecho.tipo is TipoDeTrecho.SILENCIO:
            pedaco = silencio(trecho.duracao_ms, taxa=taxa)
        elif trecho.tipo is TipoDeTrecho.FALA:
            pedaco = fala_simulada(trecho.duracao_ms, aleatorio=aleatorio, taxa=taxa)
        elif trecho.tipo is TipoDeTrecho.RUIDO_ROSA:
            pedaco = aplicar_ganho_db(
                ruido_rosa(trecho.duracao_ms, aleatorio=aleatorio, taxa=taxa), trecho.ganho_db
            )
        else:
            # A cauda do eco é a parte da cópia atrasada que cai **depois** do que já foi
            # gerado — é o assistente ouvindo o próprio playback que acabou de sair.
            atrasado = eco(gerado, atraso_ms=trecho.atraso_ms, ganho_db=trecho.ganho_db, taxa=taxa)
            pedaco = atrasado[len(gerado) :]
        gerado += _ajustar(pedaco, trecho.duracao_ms, taxa)
    return gerado
