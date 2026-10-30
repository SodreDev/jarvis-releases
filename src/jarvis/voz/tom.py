"""O tom de voz do dono, medido no mesmo trecho que vai ao ASR (dono, 2026-10-30; ADR-0058).

**O que o texto perde.** O ASR devolve palavras: «vai chover amanhã» sai sem `?` mesmo quando o
dono perguntou, e o grito, o sussurro, a risada e a pressa somem. Este módulo mede, no trecho que
o portão de ruído (ADR-0043) já aceitou, o que a voz diz além das palavras e devolve um rótulo
compacto por turno — `Tom` —, comparado com a **linha de base do próprio dono** (aprendida aos
poucos, só estatísticas: nenhum áudio fica guardado).

**Núcleo de DSP, sem modelo** (sempre ligado, quase grátis; roda numa linha à parte enquanto o
ASR transcreve, e o laço só espera por ele um prazo curto depois do ASR):

1. **Volume** — o nível RMS dos quadros de fala em dBFS (o mesmo quadro de 20 ms do portão de
   ruído) contra a média do dono. Grito exige também a F0 acima da do dono (gritar sobe o tom;
   chegar perto do microfone, não). Sussurro não depende do ganho: é fala **sem vozeamento** (o
   YIN não acha período) com palavras no texto.
2. **Entonação** — o contorno de F0 pelo YIN (de Cheveigné & Kawahara, 2002), em semitons. No
   português do Brasil a pergunta total neutra sobe **na última sílaba tônica** e pode cair
   depois dela (L+H* L%), e a afirmação cai nela (H+L* L%): por isso a medida é o pico da F0 no
   último meio segundo de fala contra a mediana do resto, não a inclinação do último quadro.
3. **Ritmo** — sílabas por segundo de fala (as sílabas vêm dos grupos vocálicos do texto do
   ASR; o tempo, dos quadros acima do fundo, sem as pausas) contra o ritmo do dono.
4. **Energia** — a ativação (arousal): F0, faixa de F0, nível e ritmo **juntos** acima ou abaixo
   da base. É a única dimensão emocional que a prosódia dá com alguma firmeza; se a voz agitada é
   irritação ou empolgação, quem diz são as palavras — e quem lê as palavras é o cérebro.
5. **Eventos** — risada (rajadas regulares de 3 a 8 por segundo), tosse (estouro ruidoso de
   ataque abrupto) e suspiro (sopro longo, sem voz e sem articulação). Heurísticas fracas, com
   confiança baixa: o classificador opcional (`ClassificadorDeTom`) as substitui quando ligado.

**O que o rótulo NÃO é:** ordem, nem «sim». Ele vai ao cérebro numa linha curta, só quando foge
do neutro (`Tom.linha`), e muda o **jeito** da resposta; nunca aprova ação — a confirmação por
voz continua com as defesas da ADR-0043/0048, que nem recebem o tom.

**Limiares provisórios.** Calibrados com áudio sintético (tons, ruído e a voz piper local,
`tools/harness_tom.py`); a voz real do dono é o que os fecha (ADR-0058, «o que não foi provado»).
"""

from __future__ import annotations

import contextlib
import itertools
import json
import math
import os
import re
import threading
import time
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol

import numpy as np

from jarvis.audio_io.quadro import (
    AMOSTRAS_POR_QUADRO,
    AMPLITUDE_MAXIMA,
    MS_POR_QUADRO,
    TAXA_PADRAO,
)
from jarvis.voz.tonica import nucleos_escritos

# --- a análise ---------------------------------------------------------------------------------
JANELA: Final = 640
"""40 ms de janela do YIN: duas vezes o período mais longo que se procura (70 Hz)."""
PASSO: Final = 160
"""10 ms entre análises: o contorno de F0 tem 100 pontos por segundo."""
F0_MIN: Final = 70.0
F0_MAX: Final = 450.0
LIMIAR_YIN: Final = 0.15
"""O limiar absoluto do YIN (o artigo usa 0,1–0,15): o primeiro mínimo abaixo dele é o período."""
VOZEADO_MAXIMO: Final = 0.3
"""Acima deste mínimo da diferença normalizada, o quadro não tem período: é sopro ou ruído."""
MARGEM_DE_FALA_DB: Final = 6.0
"""Quadro de fala = acima do fundo (percentil 20 do trecho) mais esta margem — a do portão."""
ENERGIA_MINIMA_DB: Final = -60.0
PAUSA_MINIMA_MS: Final = 300.0
REGIAO_FINAL_S: Final = 0.5
"""O último meio segundo de fala vozeada: cobre a última tônica e as postônicas."""

# --- os limiares do rótulo (provisórios: ver a ADR-0058) ---------------------------------------
LIMIAR_DE_CONFIANCA: Final = 0.5
"""Dimensão com confiança abaixo disto fica no neutro: na dúvida, o rótulo não diz nada."""
TURNOS_PARA_A_BASE: Final = 5
"""Antes disto a linha de base do dono ainda não vale: volume e ritmo usam faixas absolutas, com
metade da confiança, e a energia não é julgada."""
PERGUNTA_ST: Final = 3.0
"""O pico final acima da mediana do resto, em semitons, a partir do qual a fala soa pergunta."""
ALTO_DB: Final = 6.0
GRITO_DB: Final = 10.0
GRITO_F0_ST: Final = 2.5
BAIXO_DB: Final = -8.0
RISADA_F0_ST: Final = 4.0
"""A F0 das rajadas acima da voz do dono a partir da qual elas são risada, não sílabas: rir sobe
o tom muito acima do da fala (Bachorowski, Smoski & Owren, 2001)."""
RAPIDO: Final = 1.3
LENTO: Final = 0.7
ALFA_MINIMO: Final = 0.05
"""O passo mínimo da média móvel da base: depois de 20 turnos, cada turno pesa 5%."""


class Volume(StrEnum):
    SUSSURRO = "sussurro"
    BAIXO = "baixo"
    NORMAL = "normal"
    ALTO = "alto"
    GRITO = "grito"


class Entonacao(StrEnum):
    AFIRMACAO = "afirmacao"
    PERGUNTA = "pergunta"
    EXCLAMACAO = "exclamacao"


class Evento(StrEnum):
    NENHUM = "nenhum"
    RISADA = "risada"
    SUSPIRO = "suspiro"
    TOSSE = "tosse"


class Ritmo(StrEnum):
    LENTO = "lento"
    NORMAL = "normal"
    RAPIDO = "rapido"


class Energia(StrEnum):
    BAIXA = "baixa"
    NORMAL = "normal"
    ALTA = "alta"


DIMENSOES: Final = ("volume", "entonacao", "evento", "ritmo", "energia")
"""As dimensões do rótulo, na ordem em que a linha as diz. O dono escolhe quais vão ao cérebro."""

_FRASES: Final[Mapping[str, str]] = {
    "sussurro": "sussurrando",
    "baixo": "voz baixa",
    "alto": "voz alta",
    "grito": "gritando",
    "pergunta": "entonação de pergunta",
    "exclamacao": "exclamando",
    "risada": "rindo",
    "suspiro": "suspirou",
    "tosse": "tossiu",
    "rapido": "fala rápida",
    "lento": "fala lenta",
    "alta": "voz agitada",
    "baixa": "voz cansada",
}


_JEITO: Final[Mapping[str, str]] = {
    "grito": "curto e calmo",
    "sussurro": "curto",
    "risada": "leve",
    "rapido": "breve",
}
"""Como reagir, dito na própria nota (a persona só diz que a nota muda o jeito, ADR-0058): custa
caracteres só no turno em que aparece, e nunca diz o que fazer — só o jeito."""


@dataclass(frozen=True, slots=True)
class Prosodia:
    """O que a análise mediu no trecho. Só números — e nenhum deles sai da máquina."""

    duracao_ms: float = 0.0
    fala_ms: float = 0.0
    """Quadros de 20 ms acima do fundo mais a margem: o tempo de fala, sem as pausas."""
    nivel_db: float = -120.0
    """Média de potência dos quadros de fala, em dBFS."""
    pico_db: float = -120.0
    saturado: float = 0.0
    """Fração das amostras no limite do int16: o microfone estourou."""
    vozeado: float = 0.0
    """Fração dos quadros de fala com período (F0): perto de zero é sussurro, sopro ou ruído."""
    f0_st: float = 0.0
    """Mediana da F0, em semitons acima de 100 Hz (0 = sem F0)."""
    faixa_st: float = 0.0
    """Do percentil 10 ao 90 da F0, em semitons."""
    final_st: float = 0.0
    """O pico da F0 no último meio segundo vozeado menos a mediana do resto, em semitons."""
    queda_final_st: float = 0.0
    """Do pico final até os últimos quadros vozeados: a queda depois da tônica."""
    planura: float = 0.0
    """Planura espectral mediana dos quadros de fala (0 = tonal, 1 = ruído branco)."""
    pausas: int = 0
    maior_pausa_ms: float = 0.0
    jitter: float = 0.0
    """Variação do período entre quadros vizinhos (aproximação por quadro, não por ciclo)."""
    shimmer_db: float = 0.0
    rajadas: int = 0
    """A maior sequência de rajadas de energia em intervalo regular de 3 a 8 por segundo."""
    rajadas_f0_st: float = 0.0
    """A mediana da F0 nas rajadas (0 = sem rajadas, ou sem voz nelas)."""
    rajadas_com_voz: float = 1.0
    """A fração com voz no trecho das rajadas: na risada a voz some entre um «ha» e outro."""
    fora_das_rajadas_f0_st: float = 0.0
    """A da fala fora delas — a referência quando a base do dono ainda não está pronta."""
    vozeado_ms: float = 0.0
    """O tempo com voz (vogais, sobretudo): é o denominador do ritmo."""
    estouro_ms: float = 0.0
    """O maior estouro ruidoso de ataque abrupto (a tosse), em ms; 0 = nenhum."""
    sopro_ms: float = 0.0
    """O maior trecho de fala sem voz e sem articulação, numa borda (o suspiro), em ms."""
    analise_ms: float = 0.0
    """Quanto a análise levou — o custo, para a trilha e para o harness."""

    @property
    def tem_fala(self) -> bool:
        return self.fala_ms >= 100.0


@dataclass(frozen=True, slots=True)
class Achados:
    """O que um classificador opcional ouviu (ADR-0058, fatia E): probabilidade por código."""

    fonte: str
    eventos: Mapping[Evento, float] = field(default_factory=dict)
    volume: Mapping[Volume, float] = field(default_factory=dict)
    energia: Mapping[Energia, float] = field(default_factory=dict)
    ms: float = 0.0


class ClassificadorDeTom(Protocol):
    """Um classificador local e opcional, atrás do mesmo contrato do núcleo: recebe o **mesmo**
    trecho (PCM16 mono 16 kHz) e devolve probabilidades. Roda na linha do tom, em paralelo ao ASR;
    falha é silenciosa (o núcleo segue sozinho). Nunca recebe texto, nunca chama a rede."""

    @property
    def nome(self) -> str: ...

    def ouvir(self, amostras: bytes) -> Achados: ...


@dataclass(frozen=True, slots=True)
class Tom:
    """O rótulo do turno: como o dono falou, comparado com ele mesmo."""

    volume: Volume = Volume.NORMAL
    entonacao: Entonacao = Entonacao.AFIRMACAO
    evento: Evento = Evento.NENHUM
    ritmo: Ritmo = Ritmo.NORMAL
    energia: Energia = Energia.NORMAL
    confianca: float = 0.0
    """A menor confiança entre as dimensões que fugiram do neutro (0 quando nenhuma fugiu)."""
    fonte: str = "dsp"
    base_pronta: bool = False

    def fora_do_neutro(self, dimensoes: Sequence[str] = DIMENSOES) -> list[str]:
        """Os códigos que fogem do neutro, na ordem de `DIMENSOES`, só das dimensões pedidas."""
        neutros = {
            "volume": Volume.NORMAL,
            "entonacao": Entonacao.AFIRMACAO,
            "evento": Evento.NENHUM,
            "ritmo": Ritmo.NORMAL,
            "energia": Energia.NORMAL,
        }
        return [
            str(getattr(self, d))
            for d in DIMENSOES
            if d in dimensoes and getattr(self, d) != neutros[d]
        ]

    def neutro(self, dimensoes: Sequence[str] = DIMENSOES) -> bool:
        return not self.fora_do_neutro(dimensoes)

    def linha(self, dimensoes: Sequence[str] = DIMENSOES) -> str:
        """A linha que vai ao cérebro — vazia quando o tom é o de sempre (o caso comum, que não
        custa nenhum token)."""
        codigos = self.fora_do_neutro(dimensoes)
        if not codigos:
            return ""
        frases = ", ".join(_FRASES[c] for c in codigos)
        jeitos = list(dict.fromkeys(_JEITO[c] for c in codigos if c in _JEITO))
        dica = f"; jeito: {', '.join(jeitos)}" if jeitos else ""
        return f"[tom da voz do dono: {frases}{dica}]"

    def resumo(self, dimensoes: Sequence[str] = DIMENSOES) -> str:
        """Curto, para o indicador da janela: «pergunta · voz baixa». Vazio no neutro."""
        return " · ".join(_FRASES[c] for c in self.fora_do_neutro(dimensoes))

    def codigos(self) -> dict[str, object]:
        """Para a trilha: só códigos e a confiança, nunca os números da voz."""
        return {
            "volume": str(self.volume),
            "entonacao": str(self.entonacao),
            "som": str(self.evento),  # «evento» é o tipo do registro na trilha
            "ritmo": str(self.ritmo),
            "energia": str(self.energia),
            "confianca": round(self.confianca, 2),
            "fonte": self.fonte,
            "base_pronta": self.base_pronta,
        }


NEUTRO: Final = Tom()


# --- 1. a medida -----------------------------------------------------------------------------
def _como_float(amostras: bytes) -> np.ndarray:
    n = len(amostras) // 2
    return np.frombuffer(amostras[: n * 2], dtype="<i2").astype(np.float32) / AMPLITUDE_MAXIMA


def _db(potencia: np.ndarray | float) -> np.ndarray:
    with np.errstate(divide="ignore"):
        return np.maximum(10.0 * np.log10(np.maximum(potencia, 1e-12)), -120.0)


def yin(x: np.ndarray, *, quadros: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """F0 (Hz) e o mínimo da diferença normalizada cumulativa de cada análise de 10 ms.

    O YIN (de Cheveigné & Kawahara, 2002) vetorizado em numpy: a diferença d(τ) sai da
    autocorrelação por FFT e de somas acumuladas dos quadrados; o período é o primeiro mínimo local
    abaixo de `LIMIAR_YIN` (ou o mínimo global, se nenhum passa), refinado por interpolação
    parabólica. `quadros` restringe a análise às posições pedidas (as de fala): o resto não custa.
    """
    tau_max = int(TAXA_PADRAO / F0_MIN)
    tau_min = int(TAXA_PADRAO / F0_MAX)
    total = 1 + (x.size - JANELA - tau_max) // PASSO
    if total <= 0:
        return np.zeros(0), np.ones(0)
    posicoes = np.arange(total) if quadros is None else quadros[quadros < total]
    if posicoes.size == 0:
        return np.zeros(0), np.ones(0)
    largura = JANELA + tau_max
    indices = np.arange(largura)[None, :] + PASSO * posicoes[:, None]
    trecho = x[indices]
    nfft = 1 << (largura - 1).bit_length()  # sem volta circular: j + τ < largura <= nfft
    espectro_a = np.fft.rfft(trecho[:, :JANELA], nfft)
    espectro_b = np.fft.rfft(trecho, nfft)
    r = np.fft.irfft(np.conj(espectro_a) * espectro_b, nfft)[:, : tau_max + 1]
    acumulado = np.concatenate(
        [np.zeros((posicoes.size, 1), np.float32), np.cumsum(trecho * trecho, axis=1)], axis=1
    )
    taus = np.arange(tau_max + 1)
    energia = acumulado[:, taus + JANELA] - acumulado[:, taus]
    d = np.maximum(energia[:, :1] + energia - 2.0 * r, 0.0)
    d[:, 0] = 0.0
    normalizada = np.ones_like(d)
    normalizada[:, 1:] = d[:, 1:] * taus[1:] / np.maximum(np.cumsum(d[:, 1:], axis=1), 1e-12)
    faixa = normalizada[:, tau_min:]
    abaixo = faixa < LIMIAR_YIN
    achou = abaixo.any(axis=1)
    primeiro = np.where(achou, abaixo.argmax(axis=1), faixa.argmin(axis=1))
    sobe = np.ones_like(abaixo)
    sobe[:, :-1] = faixa[:, 1:] > faixa[:, :-1]
    coluna = np.arange(faixa.shape[1])[None, :]
    local = np.where(achou, (sobe & (coluna >= primeiro[:, None])).argmax(axis=1), primeiro)
    meio = np.clip(local, 1, faixa.shape[1] - 2)
    linhas = np.arange(posicoes.size)
    a, b, c = faixa[linhas, meio - 1], faixa[linhas, meio], faixa[linhas, meio + 1]
    curvatura = a - 2.0 * b + c
    desvio = np.where(
        np.abs(curvatura) > 1e-9, 0.5 * (a - c) / np.where(curvatura == 0, 1, curvatura), 0.0
    )
    tau = tau_min + meio + np.clip(desvio, -1.0, 1.0)
    return TAXA_PADRAO / tau, faixa[linhas, local]


def _corridas(marcas: np.ndarray) -> list[tuple[int, int]]:
    """Os trechos de `True` seguidos, como (início, fim exclusivo)."""
    if marcas.size == 0 or not marcas.any():
        return []
    bordas = np.diff(np.concatenate(([0], marcas.astype(np.int8), [0])))
    return list(
        zip(
            np.flatnonzero(bordas == 1).tolist(), np.flatnonzero(bordas == -1).tolist(), strict=True
        )
    )


def _mediana_movel(valores: np.ndarray, largura: int = 5) -> np.ndarray:
    if valores.size < largura:
        return valores
    borda = largura // 2
    estendido = np.concatenate(
        [np.repeat(valores[:1], borda), valores, np.repeat(valores[-1:], borda)]
    )
    janelas = np.lib.stride_tricks.sliding_window_view(estendido, largura)
    return np.asarray(np.median(janelas, axis=1))


def _planura(quadros: np.ndarray) -> np.ndarray:
    """Planura espectral (Wiener) de 300 Hz a 6 kHz, por quadro."""
    espectro = np.abs(np.fft.rfft(quadros * np.hanning(quadros.shape[1]), axis=1)) ** 2 + 1e-12
    hz = np.fft.rfftfreq(quadros.shape[1], 1.0 / TAXA_PADRAO)
    banda = espectro[:, (hz >= 300) & (hz <= 6000)]
    return np.exp(np.mean(np.log(banda), axis=1)) / np.mean(banda, axis=1)


def _rajadas(envelope_db: np.ndarray) -> list[list[int]]:
    """As sequências de picos de energia (10 ms) a intervalos regulares de 120 a 330 ms, com vale
    de 6 dB entre eles — candidatas ao «ha-ha-ha». Cada uma com três picos ou mais.

    Fala corrida também tem sílabas nesse ritmo: o que separa a risada é a F0 das rajadas, bem
    acima da voz do dono, e a voz que some entre elas (o sopro do «h»); quem escolhe é o `medir`
    e quem julga é o `rotular`."""
    if envelope_db.size < 20:
        return []
    suave = np.convolve(envelope_db, np.ones(3) / 3, mode="same")
    picos: list[int] = []
    for i in range(1, suave.size - 1):
        if suave[i] >= suave[i - 1] and suave[i] > suave[i + 1]:
            if picos and i - picos[-1] < 8:
                if suave[i] > suave[picos[-1]]:
                    picos[-1] = i
                continue
            picos.append(i)
    fortes: list[int] = []
    for pico in picos:
        if (
            fortes
            and suave[fortes[-1] : pico + 1].min() > min(suave[fortes[-1]], suave[pico]) - 6.0
        ):
            if suave[pico] > suave[fortes[-1]]:
                fortes[-1] = pico
            continue
        fortes.append(pico)
    sequencias: list[list[int]] = []
    atual: list[int] = fortes[:1]
    for anterior, pico in itertools.pairwise(fortes):
        intervalo = pico - anterior
        if 12 <= intervalo <= 33 and (
            len(atual) < 2 or abs(intervalo - (atual[-1] - atual[-2])) <= 0.3 * intervalo
        ):
            atual.append(pico)
            continue
        if len(atual) >= 3:
            sequencias.append(atual)
        atual = [pico]
    if len(atual) >= 3:
        sequencias.append(atual)
    return sequencias


def _a_mais_risada(
    sequencias: Sequence[Sequence[int]], com_voz: np.ndarray, st: np.ndarray
) -> tuple[int, float, float, float]:
    """Entre as sequências, a de F0 mais alta com voz intermitente. Devolve (picos, F0 das
    rajadas, fração com voz no trecho delas, F0 da fala fora delas)."""
    melhor: tuple[int, float, float, float] = (0, 0.0, 1.0, 0.0)
    for sequencia in sequencias:
        picos = np.asarray(sequencia)
        perto = np.abs(com_voz[:, None] - picos[None, :]).min(axis=1) <= 4 if st.size else None
        if perto is None or perto.sum() < 3:
            continue
        dentro = (com_voz >= picos[0] - 4) & (com_voz <= picos[-1] + 4)
        com_voz_no_trecho = float(dentro.sum() / (picos[-1] - picos[0] + 9))
        fora = float(np.median(st[~dentro])) if (~dentro).sum() >= 10 else 0.0
        candidata = (len(sequencia), float(np.median(st[perto])), com_voz_no_trecho, fora)
        if com_voz_no_trecho <= 0.65 and (melhor[0] == 0 or candidata[1] > melhor[1]):
            melhor = candidata
    return melhor


def medir(amostras: bytes) -> Prosodia:
    """A prosódia do trecho. Alguns milissegundos para segundos de fala (numpy, sem modelo)."""
    comeco = time.perf_counter()
    x = _como_float(amostras)
    n_quadros = x.size // AMOSTRAS_POR_QUADRO
    if n_quadros < 5:
        return Prosodia(duracao_ms=float(x.size * 1000 / TAXA_PADRAO))
    quadros = x[: n_quadros * AMOSTRAS_POR_QUADRO].reshape(n_quadros, AMOSTRAS_POR_QUADRO)
    potencia = np.mean(quadros * quadros, axis=1).astype(np.float64)
    db = _db(potencia)
    fundo = float(np.percentile(db, 20))
    limiar = max(fundo + MARGEM_DE_FALA_DB, ENERGIA_MINIMA_DB)
    fala = db >= limiar
    duracao_ms = float(n_quadros * MS_POR_QUADRO)
    if not fala.any():
        return Prosodia(duracao_ms=duracao_ms, analise_ms=(time.perf_counter() - comeco) * 1000)
    nivel_db = float(_db(np.mean(potencia[fala])))
    pico_db = float(np.percentile(db, 95))
    saturado = float(np.mean(np.abs(x) >= 0.999))

    # Pausas: silêncio de 300 ms ou mais entre o primeiro e o último quadro de fala.
    corridas = _corridas(fala)
    pausas_ms = [
        (inicio - fim_anterior) * MS_POR_QUADRO
        for (_, fim_anterior), (inicio, _) in itertools.pairwise(corridas)
    ]
    pausas = [p for p in pausas_ms if p >= PAUSA_MINIMA_MS]

    # A F0 só onde há fala: a análise de 10 ms k cobre o quadro de 20 ms k // 2.
    total_10ms = max(1 + (x.size - JANELA - int(TAXA_PADRAO / F0_MIN)) // PASSO, 0)
    de_fala = np.flatnonzero(fala[np.minimum(np.arange(total_10ms) // 2, n_quadros - 1)])
    f0, aperiodicidade = yin(x, quadros=de_fala)
    vozeado = (aperiodicidade < VOZEADO_MAXIMO) & (f0 >= F0_MIN) & (f0 <= F0_MAX)
    posicoes = de_fala[: f0.size]
    com_voz = posicoes[vozeado]
    st = 12.0 * np.log2(np.maximum(f0[vozeado], 1.0) / 100.0)
    if st.size >= 3:
        # Erro de oitava: o YIN às vezes pega o dobro/metade do período num quadro solto; o que
        # foge 6 semitons da mediana dos vizinhos sai (a vizinhança, não a mediana do trecho: a
        # risada fica uma oitava acima da fala e é dado), e o contorno é alisado em 50 ms.
        mantido = np.abs(st - _mediana_movel(st, 9)) <= 6.0
        st, com_voz = _mediana_movel(st[mantido]), com_voz[mantido]
    tempos = com_voz * PASSO / TAXA_PADRAO
    vozeado_fracao = float(st.size / max(posicoes.size, 1))

    f0_st = faixa_st = final_st = queda = jitter = shimmer = 0.0
    if st.size >= 10:
        f0_st = float(np.median(st))
        faixa_st = float(np.percentile(st, 90) - np.percentile(st, 10))
        final = tempos >= tempos[-1] - REGIAO_FINAL_S
        corpo = ~final if (~final).sum() >= 10 else np.ones_like(final)
        pico_final = float(np.percentile(st[final], 90))
        final_st = pico_final - float(np.median(st[corpo]))
        queda = pico_final - float(np.mean(st[-5:]))
        # Jitter e shimmer por quadro (10 ms), só entre análises vizinhas: uma aproximação — o
        # de verdade é ciclo a ciclo —, que vai à base e nunca sozinho ao rótulo.
        vizinhos = np.diff(com_voz) == 1
        if vizinhos.any():
            periodos = 1.0 / (100.0 * 2.0 ** (st / 12.0))
            jitter = float(np.mean(np.abs(np.diff(periodos))[vizinhos]) / np.mean(periodos))
            janelas = x[com_voz[:, None] * PASSO + np.arange(JANELA)[None, :]]
            nivel_10ms = _db(np.mean(janelas * janelas, axis=1).astype(np.float64))
            shimmer = float(np.mean(np.abs(np.diff(nivel_10ms))[vizinhos]))

    planura = _planura(quadros[fala])
    planura_mediana = float(np.median(planura))

    # Envelope de 10 ms, do primeiro ao último quadro de fala, para as rajadas e o estouro.
    inicio, fim_fala = corridas[0][0] * 2, corridas[-1][1] * 2
    meio_quadros = x[: (x.size // PASSO) * PASSO].reshape(-1, PASSO)
    envelope = _db(np.mean(meio_quadros[inicio:fim_fala] ** 2, axis=1).astype(np.float64))
    sequencias = [[pico + inicio for pico in seq] for seq in _rajadas(envelope)]
    n_rajadas, rajadas_f0, rajadas_com_voz, fora_f0 = _a_mais_risada(sequencias, com_voz, st)

    estouro = _estouro(db, fala, planura, fundo, corridas, x)
    sopro = _sopro(db, fala, planura, corridas, x, de_fala, vozeado)
    return Prosodia(
        duracao_ms=duracao_ms,
        fala_ms=float(fala.sum() * MS_POR_QUADRO),
        nivel_db=nivel_db,
        pico_db=pico_db,
        saturado=saturado,
        vozeado=vozeado_fracao,
        f0_st=f0_st,
        faixa_st=faixa_st,
        final_st=final_st,
        queda_final_st=queda,
        planura=planura_mediana,
        pausas=len(pausas),
        maior_pausa_ms=float(max(pausas, default=0.0)),
        jitter=jitter,
        shimmer_db=shimmer,
        rajadas=n_rajadas,
        rajadas_f0_st=rajadas_f0,
        rajadas_com_voz=rajadas_com_voz,
        fora_das_rajadas_f0_st=fora_f0,
        vozeado_ms=float(st.size * PASSO * 1000 / TAXA_PADRAO),
        estouro_ms=estouro,
        sopro_ms=sopro,
        analise_ms=(time.perf_counter() - comeco) * 1000,
    )


def _vozeado_no_trecho(x: np.ndarray, inicio: int, fim: int) -> float:
    """Fração de análises com período entre os quadros de 20 ms `inicio` e `fim`."""
    posicoes = np.arange(inicio * 2, fim * 2)
    f0, aperiodicidade = yin(x, quadros=posicoes)
    if f0.size == 0:
        return 0.0
    return float(np.mean((aperiodicidade < VOZEADO_MAXIMO) & (f0 >= F0_MIN) & (f0 <= F0_MAX)))


def _estouro(
    db: np.ndarray,
    fala: np.ndarray,
    planura: np.ndarray,
    fundo: float,
    corridas: Sequence[tuple[int, int]],
    x: np.ndarray,
) -> float:
    """A tosse: um trecho de fala de 120 a 700 ms que nasce de uma vez (20 dB acima do fundo num
    quadro só), é ruído (planura alta) e quase não tem voz."""
    planura_por_quadro = np.zeros(db.size)
    planura_por_quadro[np.flatnonzero(fala)] = planura
    melhor = 0.0
    for inicio, fim in corridas:
        duracao = (fim - inicio) * MS_POR_QUADRO
        if not 120 <= duracao <= 700:
            continue
        antes = db[inicio - 1] if inicio > 0 else fundo
        ataque = float(db[min(inicio + 1, fim - 1)] - antes)
        if ataque < 20.0 or float(np.median(planura_por_quadro[inicio:fim])) < 0.2:
            continue
        if _vozeado_no_trecho(x, inicio, fim) > 0.3:
            continue
        melhor = max(melhor, duracao)
    return melhor


def _sopro(
    db: np.ndarray,
    fala: np.ndarray,
    planura: np.ndarray,
    corridas: Sequence[tuple[int, int]],
    x: np.ndarray,
    de_fala: np.ndarray,
    vozeado: np.ndarray,
) -> float:
    """O suspiro: na primeira ou na última corrida de fala, 450 ms ou mais sem voz, com o envelope
    liso (sem a articulação que o sussurro tem) e ataque gradual."""
    melhor = 0.0
    for inicio, fim in {corridas[0], corridas[-1]}:
        duracao = (fim - inicio) * MS_POR_QUADRO
        if duracao < 450:
            continue
        trecho_db = db[inicio:fim]
        aspereza = float(np.mean(np.abs(np.diff(trecho_db))))
        # Ataque gradual: do quadro de antes ao primeiro da corrida, pouco; e o máximo chega
        # depois de 100 ms. Ruído que liga de uma vez (chiado, ventilador ligando) não é suspiro.
        antes = float(db[inicio - 1]) if inicio > 0 else float(trecho_db[0])
        degrau = float(trecho_db[0]) - antes
        subida_ms = float(np.argmax(trecho_db)) * MS_POR_QUADRO
        if aspereza > 1.5 or degrau > 12.0 or subida_ms < 100.0:
            continue
        if _vozeado_no_trecho(x, inicio, fim) > 0.2:
            continue
        melhor = max(melhor, duracao)
    return melhor


# --- 2. a linha de base do dono ---------------------------------------------------------------
@dataclass(slots=True)
class LinhaDeBase:
    """A voz de sempre do dono — só médias e desvios, aprendidos turno a turno."""

    turnos: int = 0
    nivel_db: float = -30.0
    nivel_desvio_db: float = 4.0
    f0_turnos: int = 0
    f0_st: float = 0.0
    f0_desvio_st: float = 2.0
    faixa_st: float = 6.0
    ritmo_turnos: int = 0
    silabas_por_s: float = 5.5

    @property
    def pronta(self) -> bool:
        return self.turnos >= TURNOS_PARA_A_BASE

    @property
    def f0_pronta(self) -> bool:
        return self.f0_turnos >= TURNOS_PARA_A_BASE

    def aprender(self, prosodia: Prosodia, silabas_por_s: float | None) -> None:
        """Uma média móvel que começa rápida (o 1º turno já vale) e assenta em `ALFA_MINIMO`. O
        desvio de cada turno entra limitado a 2,5 desvios: um grito não arrasta a base."""
        if not prosodia.tem_fala:
            return
        self.turnos += 1
        alfa = max(1.0 / self.turnos, ALFA_MINIMO)
        self.nivel_db, self.nivel_desvio_db = _mover(
            self.nivel_db, self.nivel_desvio_db, prosodia.nivel_db, alfa, self.turnos, piso=1.5
        )
        if prosodia.f0_st != 0.0 and prosodia.vozeado >= 0.4:
            self.f0_turnos += 1
            alfa_f0 = max(1.0 / self.f0_turnos, ALFA_MINIMO)
            self.f0_st, self.f0_desvio_st = _mover(
                self.f0_st, self.f0_desvio_st, prosodia.f0_st, alfa_f0, self.f0_turnos, piso=0.8
            )
            self.faixa_st += alfa_f0 * (prosodia.faixa_st - self.faixa_st)
        if silabas_por_s is not None and 1.0 <= silabas_por_s <= 12.0:
            self.ritmo_turnos += 1
            alfa_r = max(1.0 / self.ritmo_turnos, ALFA_MINIMO)
            self.silabas_por_s += alfa_r * (silabas_por_s - self.silabas_por_s)

    def para_dict(self) -> dict[str, float | int]:
        return {
            "versao": 1,
            "turnos": self.turnos,
            "nivel_db": round(self.nivel_db, 2),
            "nivel_desvio_db": round(self.nivel_desvio_db, 2),
            "f0_turnos": self.f0_turnos,
            "f0_st": round(self.f0_st, 2),
            "f0_desvio_st": round(self.f0_desvio_st, 2),
            "faixa_st": round(self.faixa_st, 2),
            "ritmo_turnos": self.ritmo_turnos,
            "silabas_por_s": round(self.silabas_por_s, 2),
        }

    @classmethod
    def de_dict(cls, dados: Mapping[str, object]) -> LinhaDeBase:
        """Arquivo torto ou de outra versão = base nova: perder a calibração é melhor que mentir."""
        if dados.get("versao") != 1:
            return cls()
        base = cls()
        for nome, padrao in base.para_dict().items():
            if nome == "versao":
                continue
            valor = dados.get(nome, padrao)
            if (
                not isinstance(valor, int | float)
                or isinstance(valor, bool)
                or not math.isfinite(valor)
            ):
                return cls()
            setattr(base, nome, int(valor) if isinstance(padrao, int) else float(valor))
        return base


def _mover(
    media: float, desvio: float, valor: float, alfa: float, n: int, *, piso: float
) -> tuple[float, float]:
    if n == 1:
        return valor, desvio
    limite = 2.5 * max(desvio, piso)
    diferenca = max(-limite, min(limite, valor - media))
    media += alfa * diferenca
    desvio = math.sqrt((1 - alfa) * desvio * desvio + alfa * diferenca * diferenca)
    return media, max(desvio, piso)


class RepositorioDaLinhaDeBase:
    """`tom.json` na pasta de estado da sessão (0600, pasta 0700): os números da base, nunca áudio.

    Apagar o arquivo zera a calibração; com `tom_de_voz = false` ele nem é lido."""

    ARQUIVO: Final = "tom.json"

    def __init__(self, pasta: Path) -> None:
        self.caminho = pasta / self.ARQUIVO

    def ler(self) -> LinhaDeBase:
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return LinhaDeBase()
        return LinhaDeBase.de_dict(dados) if isinstance(dados, dict) else LinhaDeBase()

    def gravar(self, base: LinhaDeBase) -> None:
        pasta = self.caminho.parent
        pasta.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporario = pasta / f".{self.ARQUIVO}.{os.getpid()}.tmp"
        descritor = os.open(temporario, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descritor, "w", encoding="utf-8") as arquivo:
            json.dump(base.para_dict(), arquivo)
        temporario.replace(self.caminho)


# --- 3. o rótulo ---------------------------------------------------------------------------------
_PALAVRA: Final = re.compile(r"[^\W\d_]+", re.UNICODE)


def silabas(texto: str) -> int:
    """Sílabas aproximadas do texto: os grupos vocálicos escritos de cada palavra (ditongo conta
    um; hiato conta um também — o erro é pequeno e igual para a base e para o turno)."""
    total = 0
    for palavra in _PALAVRA.findall(unicodedata.normalize("NFC", texto.casefold())):
        total += max(len(nucleos_escritos(palavra)), 1)
    return total


def taxa_de_silabas(prosodia: Prosodia, texto: str) -> float | None:
    """Sílabas do texto por segundo **com voz** (as vogais carregam as sílabas; a pausa, o sopro
    e a tosse não contam). No sussurro, sem voz, o tempo de fala. `None` = pouco para medir."""
    tempo_ms = prosodia.vozeado_ms if prosodia.vozeado >= 0.25 else prosodia.fala_ms
    if tempo_ms < 500 or len(_PALAVRA.findall(texto)) < 3:
        return None
    return silabas(texto) / (tempo_ms / 1000.0)


def _confianca(valor: float, comeco: float, cheio: float) -> float:
    """0 em `comeco`, 1 em `cheio`, linear entre os dois."""
    if cheio == comeco:
        return 1.0
    return max(0.0, min(1.0, (valor - comeco) / (cheio - comeco)))


def rotular(
    prosodia: Prosodia,
    base: LinhaDeBase,
    *,
    texto: str = "",
    achados: Sequence[Achados] = (),
) -> Tom:
    """O rótulo do turno. Cada dimensão só foge do neutro com confiança de `LIMIAR_DE_CONFIANCA`
    ou mais; antes de a base ficar pronta, volume e ritmo valem metade e a energia não é julgada."""
    if not prosodia.tem_fala:
        return NEUTRO
    palavras = len(_PALAVRA.findall(texto))
    peso = 1.0 if base.pronta else 0.5
    escolhas: dict[str, tuple[StrEnum, float]] = {}

    # Volume. Sussurro: fala com palavras e quase sem voz (não depende do ganho do microfone).
    relativo = prosodia.nivel_db - base.nivel_db
    f0_relativo = prosodia.f0_st - base.f0_st if base.f0_pronta and prosodia.f0_st else 0.0
    if palavras >= 1 and prosodia.vozeado < 0.25 and prosodia.planura >= 0.15:
        escolhas["volume"] = (Volume.SUSSURRO, _confianca(0.25 - prosodia.vozeado, 0.0, 0.15))
    elif base.pronta:
        if relativo >= GRITO_DB and (f0_relativo >= GRITO_F0_ST or prosodia.saturado > 0.002):
            escolhas["volume"] = (Volume.GRITO, _confianca(relativo, GRITO_DB - 2, GRITO_DB + 4))
        elif relativo >= ALTO_DB:
            escolhas["volume"] = (Volume.ALTO, _confianca(relativo, ALTO_DB - 2, ALTO_DB + 3))
        elif relativo <= BAIXO_DB:
            escolhas["volume"] = (Volume.BAIXO, _confianca(-relativo, -BAIXO_DB - 2, -BAIXO_DB + 4))
    elif prosodia.saturado > 0.002 or prosodia.nivel_db >= -10.0:
        escolhas["volume"] = (Volume.GRITO, 0.5 * peso * 2)  # estourou o microfone: alto de verdade
    elif prosodia.nivel_db <= -48.0:
        escolhas["volume"] = (Volume.BAIXO, peso * _confianca(-prosodia.nivel_db, 46, 54))

    # Entonação: o pico da última tônica contra o resto (L+H* L% do pt-BR).
    termina = texto.rstrip()[-1:] if texto.strip() else ""
    if prosodia.vozeado >= 0.3 and prosodia.f0_st:
        if prosodia.final_st >= PERGUNTA_ST - 0.5 and termina != "!":
            escolhas["entonacao"] = (
                Entonacao.PERGUNTA,
                _confianca(prosodia.final_st, PERGUNTA_ST - 1.0, PERGUNTA_ST + 2.0),
            )
        elif termina == "!" or (
            base.pronta
            and prosodia.faixa_st >= base.faixa_st + 4.0
            and relativo >= 4.0
            and prosodia.queda_final_st >= 3.0
        ):
            escolhas["entonacao"] = (Entonacao.EXCLAMACAO, 0.6 if termina == "!" else 0.5)
    if termina == "?" and "entonacao" not in escolhas:
        escolhas["entonacao"] = (Entonacao.PERGUNTA, 1.0)  # o próprio ASR ouviu a pergunta

    # Eventos pelo DSP (fracos): risada, tosse, suspiro.
    referencia_f0 = base.f0_st if base.f0_pronta else prosodia.fora_das_rajadas_f0_st
    elevacao = prosodia.rajadas_f0_st - referencia_f0 if referencia_f0 else 0.0
    if prosodia.estouro_ms > 0:
        escolhas["evento"] = (Evento.TOSSE, 0.55)
    elif prosodia.rajadas >= 4 and prosodia.rajadas_f0_st and elevacao >= RISADA_F0_ST:
        escolhas["evento"] = (
            Evento.RISADA,
            _confianca(elevacao, RISADA_F0_ST - 1.0, RISADA_F0_ST + 3.0),
        )
    elif prosodia.sopro_ms > 0 and escolhas.get("volume", (None, 0))[0] is not Volume.SUSSURRO:
        escolhas["evento"] = (Evento.SUSPIRO, _confianca(prosodia.sopro_ms, 400, 900))

    # Ritmo: sílabas do texto por segundo de fala.
    # Com risada, tosse ou suspiro no meio, o tempo não é o da fala: o ritmo não é julgado.
    taxa = taxa_de_silabas(prosodia, texto) if "evento" not in escolhas else None
    if taxa is not None:
        referencia = base.silabas_por_s if base.ritmo_turnos >= TURNOS_PARA_A_BASE else 5.5
        peso_ritmo = 1.0 if base.ritmo_turnos >= TURNOS_PARA_A_BASE else 0.5
        if taxa >= RAPIDO * referencia:
            escolhas["ritmo"] = (
                Ritmo.RAPIDO,
                peso_ritmo * _confianca(taxa / referencia, RAPIDO - 0.1, RAPIDO + 0.25),
            )
        elif taxa <= LENTO * referencia:
            escolhas["ritmo"] = (
                Ritmo.LENTO,
                peso_ritmo * _confianca(referencia / taxa, 1 / LENTO - 0.1, 1 / LENTO + 0.4),
            )

    # Energia (ativação): várias pistas juntas, só com a base pronta.
    if base.pronta and base.f0_pronta and prosodia.vozeado >= 0.4:
        sinais = [
            f0_relativo / max(base.f0_desvio_st, 0.8),
            (prosodia.faixa_st - base.faixa_st) / 3.0,
            relativo / max(base.nivel_desvio_db, 1.5),
        ]
        if taxa is not None and base.ritmo_turnos >= TURNOS_PARA_A_BASE:
            sinais.append((taxa / base.silabas_por_s - 1.0) / 0.2)
        media = float(np.mean(sinais))
        if all(s >= 0.8 for s in sinais) and media >= 1.5:
            escolhas["energia"] = (Energia.ALTA, _confianca(media, 1.0, 2.5))
        elif all(s <= -0.5 for s in sinais) and media <= -1.2:
            escolhas["energia"] = (Energia.BAIXA, _confianca(-media, 0.8, 2.2))

    fonte = "dsp"
    for achado in achados:
        fonte = f"{fonte}+{achado.fonte}"
        escolhas = _juntar(escolhas, achado)

    valores: dict[str, StrEnum] = {}
    confiancas: list[float] = []
    for dimensao, (valor, confianca) in escolhas.items():
        if confianca >= LIMIAR_DE_CONFIANCA:
            valores[dimensao] = valor
            confiancas.append(confianca)
    return Tom(
        volume=Volume(valores.get("volume", Volume.NORMAL)),
        entonacao=Entonacao(valores.get("entonacao", Entonacao.AFIRMACAO)),
        evento=Evento(valores.get("evento", Evento.NENHUM)),
        ritmo=Ritmo(valores.get("ritmo", Ritmo.NORMAL)),
        energia=Energia(valores.get("energia", Energia.NORMAL)),
        confianca=min(confiancas, default=0.0),
        fonte=fonte,
        base_pronta=base.pronta,
    )


LIMIAR_DO_CLASSIFICADOR: Final = 0.5
"""Probabilidade do classificador a partir da qual ele vence a heurística do DSP."""


def _juntar(
    escolhas: dict[str, tuple[StrEnum, float]], achado: Achados
) -> dict[str, tuple[StrEnum, float]]:
    """O classificador vence o DSP no que ele mede — e o «nenhum» dele, com certeza alta, apaga o
    evento que a heurística inventou."""
    novas = dict(escolhas)
    for dimensao, probabilidades in (
        ("evento", achado.eventos),
        ("volume", achado.volume),
        ("energia", achado.energia),
    ):
        if not probabilidades:
            continue
        valor, probabilidade = max(probabilidades.items(), key=lambda item: item[1])
        if probabilidade < LIMIAR_DO_CLASSIFICADOR:
            continue
        if dimensao == "evento" and valor is Evento.NENHUM:
            novas.pop("evento", None)
            continue
        if dimensao == "volume" and dimensao in novas and novas[dimensao][0] is Volume.GRITO:
            continue  # o nível medido contra a base do dono vale mais que o rótulo genérico
        novas[dimensao] = (valor, probabilidade)
    return novas


# --- 4. o que o laço usa ------------------------------------------------------------------------
_RESPOSTAS_CURTAS: Final = frozenset(
    {
        "sim",
        "nao",
        "não",
        "ok",
        "pode",
        "claro",
        "isso",
        "certo",
        "beleza",
        "para",
        "chega",
        "cancela",
    }
)


def com_pergunta(texto: str, tom: Tom) -> str:
    """A entonação de pergunta põe o `?` que o ASR não pôs: «vai chover amanhã» → «vai chover
    amanhã?». Não mexe em texto que já termina em `?` ou `!`, nem em resposta curta («sim»,
    «pode»): tom nunca vira resposta a uma confirmação."""
    if tom.entonacao is not Entonacao.PERGUNTA:
        return texto
    limpo = texto.rstrip()
    if not limpo or limpo[-1] in "?!":
        return texto
    palavras = [p.casefold() for p in _PALAVRA.findall(limpo)]
    if not palavras or (len(palavras) <= 2 and set(palavras) <= _RESPOSTAS_CURTAS | {"jarvis"}):
        return texto
    return limpo.rstrip(".…;,: ") + "?"


GANHO_DO_SUSSURRO_DB: Final = -9.0
"""Com o dono sussurrando, a resposta sai 9 dB mais baixa (ADR-0058, opcional `tom_na_voz`)."""


def ganho_da_resposta_db(tom: Tom) -> float:
    return GANHO_DO_SUSSURRO_DB if tom.volume is Volume.SUSSURRO else 0.0


def aplicar_ganho(amostras: bytes, db: float) -> bytes:
    """Ganho em PCM16 por numpy, com saturação — rápido o bastante para cada pedaço do TTS."""
    if db == 0.0 or not amostras:
        return amostras
    valores = np.frombuffer(amostras[: len(amostras) // 2 * 2], dtype="<i2").astype(np.float32)
    valores *= 10.0 ** (db / 20.0)
    return np.clip(np.rint(valores), -32768, 32767).astype("<i2").tobytes()


@dataclass(frozen=True, slots=True)
class MedidaDoTom:
    """O que a linha do tom devolve: a prosódia e o que os classificadores ouviram."""

    prosodia: Prosodia
    achados: tuple[Achados, ...] = ()


class AnalisadorDeTom:
    """O tom do laço: mede (na linha à parte, em paralelo ao ASR), rotula e aprende a base.

    `medir` é puro e pode rodar em qualquer linha; `rotular` e `aprender` leem e mudam a base sob
    uma trava. A base é gravada a cada `GRAVAR_A_CADA` turnos aprendidos e no `fechar`."""

    GRAVAR_A_CADA: Final = 5

    def __init__(
        self,
        repositorio: RepositorioDaLinhaDeBase | None = None,
        *,
        classificadores: Sequence[ClassificadorDeTom] = (),
    ) -> None:
        self.repositorio = repositorio
        self.classificadores = tuple(classificadores)
        self._trava = threading.Lock()
        self._base = repositorio.ler() if repositorio is not None else LinhaDeBase()
        self._nao_gravados = 0

    @property
    def base(self) -> LinhaDeBase:
        with self._trava:
            return replace(self._base)

    def medir(self, amostras: bytes) -> MedidaDoTom:
        prosodia = medir(amostras)
        achados: list[Achados] = []
        if prosodia.tem_fala:
            for classificador in self.classificadores:
                # Classificador que falha não leva o turno junto: o núcleo segue sozinho.
                with contextlib.suppress(Exception):
                    achados.append(classificador.ouvir(amostras))
        return MedidaDoTom(prosodia, tuple(achados))

    def rotular(self, escuta: MedidaDoTom, texto: str) -> Tom:
        with self._trava:
            base = replace(self._base)
        return rotular(escuta.prosodia, base, texto=texto, achados=escuta.achados)

    def aprender(self, escuta: MedidaDoTom, texto: str) -> None:
        """O turno aceito entra na base (ruído descartado nunca chega aqui)."""
        prosodia = escuta.prosodia
        taxa = (
            silabas(texto) / (prosodia.fala_ms / 1000.0)
            if prosodia.fala_ms >= 600 and len(_PALAVRA.findall(texto)) >= 3
            else None
        )
        with self._trava:
            self._base.aprender(prosodia, taxa)
            self._nao_gravados += 1
            gravar = self._nao_gravados >= self.GRAVAR_A_CADA
        if gravar:
            self.gravar()

    def gravar(self) -> None:
        if self.repositorio is None:
            return
        with self._trava:
            base = replace(self._base)
            self._nao_gravados = 0
        with contextlib.suppress(OSError):  # disco cheio não derruba a conversa
            self.repositorio.gravar(base)

    def fechar(self) -> None:
        if self._nao_gravados:
            self.gravar()


__all__ = [
    "DIMENSOES",
    "NEUTRO",
    "Achados",
    "AnalisadorDeTom",
    "ClassificadorDeTom",
    "Energia",
    "Entonacao",
    "Evento",
    "LinhaDeBase",
    "MedidaDoTom",
    "Prosodia",
    "RepositorioDaLinhaDeBase",
    "Ritmo",
    "Tom",
    "Volume",
    "aplicar_ganho",
    "com_pergunta",
    "ganho_da_resposta_db",
    "medir",
    "rotular",
    "silabas",
    "taxa_de_silabas",
    "yin",
]
