"""Áudio sintético com tom conhecido, para os testes e o harness do tom de voz (ADR-0058).

Nada de microfone: cada cena é gerada de uma semente, com o contorno de F0, o nível, o ritmo e o
evento escolhidos — é isso que deixa o teste saber a resposta certa. A «fala» é uma fonte de
harmônicos (a voz) modulada em sílabas, com um vale de consoante entre elas; o sussurro e o sopro
são ruído filtrado com o mesmo envelope; a risada são rajadas vozeadas e aspiradas a 5 por
segundo; a tosse, um estouro de ruído de ataque abrupto. É um banco de prova do **detector**, não
uma imitação da voz humana: o que só a voz real do dono fecha está na ADR-0058.

Formato do projeto: PCM16 mono 16 kHz little endian (`jarvis.audio_io.quadro`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np

TAXA: Final = 16_000
FUNDO_DB: Final = -66.0
"""O chiado de fundo da sala sintética: bem abaixo da fala, acima do silêncio digital."""


def _rng(semente: int) -> np.random.Generator:
    return np.random.default_rng(semente)


def _amostras(segundos: float) -> int:
    return round(segundos * TAXA)


def _no_nivel(sinal: np.ndarray, nivel_db: float) -> np.ndarray:
    """Escala o sinal para que a média de potência do que não é silêncio fique em `nivel_db`."""
    ativo = np.abs(sinal) > 1e-6
    if not ativo.any():
        return sinal
    potencia = float(np.mean(sinal[ativo] ** 2))
    return np.asarray(sinal * (10.0 ** (nivel_db / 20.0) / np.sqrt(potencia)))


def _banda(ruido: np.ndarray, baixo: float, alto: float) -> np.ndarray:
    espectro = np.fft.rfft(ruido)
    hz = np.fft.rfftfreq(ruido.size, 1.0 / TAXA)
    espectro[(hz < baixo) | (hz > alto)] = 0
    return np.fft.irfft(espectro, ruido.size)


def _envelope_de_silabas(n: int, silabas_por_s: float, rng: np.random.Generator) -> np.ndarray:
    """Uma sílaba = um arco (núcleo) e um vale curto de consoante (~-20 dB), com jitter de ±15%."""
    envelope = np.zeros(n)
    t = 0
    while t < n:
        duracao = int(TAXA / silabas_por_s * rng.uniform(0.85, 1.15))
        nucleo = int(duracao * 0.78)
        arco = np.sin(np.linspace(0, np.pi, nucleo)) ** 0.6
        fim = min(t + nucleo, n)
        envelope[t:fim] = arco[: fim - t]
        envelope[fim : min(t + duracao, n)] = 0.1
        t += duracao
    return envelope


def voz(
    f0_pontos: Sequence[float],
    segundos: float,
    *,
    nivel_db: float = -28.0,
    silabas_por_s: float = 5.0,
    semente: int = 0,
    sopro: float = 0.02,
) -> np.ndarray:
    """Fala sintética: harmônicos com a F0 interpolada de `f0_pontos` (Hz, espaçados no tempo),
    em sílabas de `silabas_por_s`."""
    rng = _rng(semente)
    n = _amostras(segundos)
    tempo = np.arange(n) / TAXA
    f0 = np.interp(tempo, np.linspace(0, segundos, len(f0_pontos)), f0_pontos)
    f0 = f0 * (1.0 + 0.004 * rng.standard_normal(n).cumsum() / np.sqrt(np.arange(1, n + 1)))
    fase = 2 * np.pi * np.cumsum(f0) / TAXA
    harmonicos = sum(np.sin(k * fase) / k**1.2 for k in range(1, 25) if k * 450 < TAXA / 2)
    fonte = np.asarray(harmonicos) + sopro * _banda(rng.standard_normal(n), 300, 6000)
    return _no_nivel(fonte * _envelope_de_silabas(n, silabas_por_s, rng), nivel_db)


def sussurro(
    segundos: float, *, nivel_db: float = -38.0, silabas_por_s: float = 5.0, semente: int = 0
) -> np.ndarray:
    rng = _rng(semente)
    n = _amostras(segundos)
    ruido = _banda(rng.standard_normal(n), 400, 6000)
    return _no_nivel(ruido * _envelope_de_silabas(n, silabas_por_s, rng), nivel_db)


def risada(
    rajadas: int = 6, *, por_segundo: float = 5.0, nivel_db: float = -26.0, semente: int = 0
) -> np.ndarray:
    """«Ha-ha-ha»: rajadas de 80 ms vozeadas (F0 alta, 260 Hz) e aspiradas, a intervalos iguais."""
    rng = _rng(semente)
    periodo = _amostras(1.0 / por_segundo)
    n = periodo * rajadas
    saida = np.zeros(n)
    duracao = _amostras(0.085)
    tempo = np.arange(duracao) / TAXA
    for i in range(rajadas):
        f0 = 260.0 * (1.0 - 0.06 * i / rajadas)
        voz_da_rajada = sum(np.sin(2 * np.pi * k * f0 * tempo) / k for k in range(1, 15))
        aspirado = 0.35 * _banda(rng.standard_normal(duracao), 500, 5000)
        arco = np.sin(np.linspace(0, np.pi, duracao)) ** 1.5
        inicio = i * periodo
        saida[inicio : inicio + duracao] = (np.asarray(voz_da_rajada) + aspirado) * arco
    return _no_nivel(saida, nivel_db)


def tosse(*, nivel_db: float = -18.0, semente: int = 0) -> np.ndarray:
    """Um estouro: ataque de 5 ms, ruído largo, decaimento de ~250 ms."""
    rng = _rng(semente)
    n = _amostras(0.32)
    tempo = np.arange(n) / TAXA
    envelope = np.minimum(tempo / 0.005, 1.0) * np.exp(-tempo / 0.09)
    return _no_nivel(_banda(rng.standard_normal(n), 150, 7000) * envelope, nivel_db)


def suspiro(segundos: float = 1.2, *, nivel_db: float = -36.0, semente: int = 0) -> np.ndarray:
    """O sopro longo: ruído grave e liso, com subida de 0,3 s e descida até o fim."""
    rng = _rng(semente)
    n = _amostras(segundos)
    tempo = np.arange(n) / TAXA
    envelope = np.minimum(tempo / 0.3, 1.0) * np.clip((segundos - tempo) / (segundos - 0.3), 0, 1)
    return _no_nivel(_banda(rng.standard_normal(n), 200, 2500) * envelope, nivel_db)


def silencio(segundos: float) -> np.ndarray:
    return np.zeros(_amostras(segundos))


def trecho(*partes: np.ndarray, semente: int = 0, fundo_db: float = FUNDO_DB) -> bytes:
    """As partes em sequência, com os 400 ms de antes e o silêncio do fim que o laço manda ao ASR,
    sobre um chiado de fundo — em PCM16."""
    rng = _rng(semente + 7919)
    sinal = np.concatenate([silencio(0.4), *partes, silencio(0.6)])
    sinal = sinal + 10.0 ** (fundo_db / 20.0) * rng.standard_normal(sinal.size)
    return bytes(np.clip(np.rint(sinal * 32768.0), -32768, 32767).astype("<i2").tobytes())


# --- as cenas ----------------------------------------------------------------------------------
AFIRMACAO: Final = (130.0, 138.0, 132.0, 126.0, 120.0, 112.0, 104.0, 98.0)
"""Declinação e a queda na última tônica (H+L* L%)."""
PERGUNTA: Final = (128.0, 134.0, 128.0, 124.0, 122.0, 126.0, 175.0, 160.0)
"""Plana e a subida na última tônica, com a queda curta da postônica (L+H* L%)."""
PERGUNTA_OXITONA: Final = (128.0, 134.0, 128.0, 124.0, 122.0, 124.0, 150.0, 185.0)
"""A tônica é a última sílaba: a subida vai até o fim."""


@dataclass(frozen=True, slots=True)
class Cena:
    nome: str
    audio: bytes
    texto: str
    esperado: dict[str, str]


def cenas(semente: int = 0) -> list[Cena]:
    """O banco: cada cena com o texto que o ASR daria e o rótulo esperado por dimensão."""
    s = semente
    return [
        Cena(
            "afirmacao",
            trecho(voz(AFIRMACAO, 2.0, semente=s), semente=s),
            "vou sair um pouco mais tarde hoje",
            {"entonacao": "afirmacao", "volume": "normal"},
        ),
        Cena(
            "pergunta",
            trecho(voz(PERGUNTA, 2.0, semente=s + 1), semente=s + 1),
            "vai chover amanhã de manhã",
            {"entonacao": "pergunta"},
        ),
        Cena(
            "pergunta_oxitona",
            trecho(voz(PERGUNTA_OXITONA, 2.0, semente=s + 2), semente=s + 2),
            "você já comeu alguma coisa hoje",
            {"entonacao": "pergunta"},
        ),
        Cena(
            "grito",
            trecho(
                voz(tuple(f * 1.4 for f in AFIRMACAO), 1.8, nivel_db=-14.0, semente=s + 3),
                semente=s + 3,
            ),
            "para com isso agora mesmo",
            {"volume": "grito"},
        ),
        Cena(
            "voz_baixa",
            trecho(voz(AFIRMACAO, 2.0, nivel_db=-42.0, semente=s + 4), semente=s + 4),
            "pode deixar assim mesmo por favor",
            {"volume": "baixo"},
        ),
        Cena(
            "sussurro",
            trecho(sussurro(1.8, semente=s + 5), semente=s + 5),
            "abre a música baixinho",
            {"volume": "sussurro"},
        ),
        Cena(
            "risada",
            trecho(
                risada(semente=s + 6),
                silencio(0.2),
                voz(AFIRMACAO, 1.4, semente=s + 6),
                semente=s + 6,
            ),
            "essa foi muito boa mesmo",
            {"evento": "risada"},
        ),
        Cena(
            "tosse",
            trecho(
                tosse(semente=s + 7),
                silencio(0.25),
                voz(AFIRMACAO, 1.6, semente=s + 7),
                semente=s + 7,
            ),
            "abre o navegador para mim",
            {"evento": "tosse"},
        ),
        Cena(
            "suspiro",
            trecho(
                voz(AFIRMACAO, 1.6, semente=s + 8),
                silencio(0.35),
                suspiro(semente=s + 8),
                semente=s + 8,
            ),
            "que dia comprido foi esse hoje",
            {"evento": "suspiro"},
        ),
        Cena(
            "rapido",
            trecho(voz(AFIRMACAO, 1.6, silabas_por_s=8.5, semente=s + 9), semente=s + 9),
            "abre logo o navegador que eu tenho uma reunião agora",
            {"ritmo": "rapido"},
        ),
        Cena(
            "lento",
            trecho(voz(AFIRMACAO, 2.4, silabas_por_s=2.6, semente=s + 10), semente=s + 10),
            "abre o calendário",
            {"ritmo": "lento"},
        ),
    ]


def base_do_dono(semente: int = 100) -> list[tuple[bytes, str]]:
    """Seis turnos de voz «de sempre» (afirmação, -28 dBFS, 5 sílabas/s) para a linha de base."""
    turnos = []
    for i in range(6):
        pontos = tuple(f * (1.0 + 0.02 * ((i % 3) - 1)) for f in AFIRMACAO)
        audio = trecho(
            voz(pontos, 2.0, nivel_db=-28.0 + (i % 2), semente=semente + i), semente=semente + i
        )
        turnos.append((audio, "eu quero ver o que tem para hoje"))
    return turnos
