"""A fronteira por onde um motor de voz entra no produto (ADR-0017).

**O que esta interface decide, e o que ela deliberadamente não decide.** A ADR-0017 propôs
assinaturas em que o próprio motor fosse incremental (`transcrever_parcial(quadros)`) e
produzisse pedaços com epoch (`sintetizar(texto, epoch) -> Iterator[Pedaco]`). Implementar
assim obrigaria **cada** motor — e são quatro de cada lado, dois deles de nuvem — a
reimplementar o acordo de prefixo do F1-06, o fatiamento e o descarte de pedaço em voo do
F1-09 e as vinte interrupções do F1-11. A interface ficou mais estreita de propósito:

- **o motor traduz um bloco** (amostras → texto, texto → amostras) e **declara de onde ele é**;
- **quem é incremental, fatia, cancela e conhece epoch é a camada compartilhada** que já existe
  e já é regressão: `TranscritorIncremental` (F1-06) e `SintetizadorEmStreaming` (F1-09).

O ganho é verificável: trocar de motor não pode afrouxar o cancelamento, porque o motor não é
quem cancela. A emenda está registrada na própria ADR-0017, como o CONTRIBUTING manda.

**O que o motor de nuvem ganha a mais, e por quê.** Um motor local sintetiza em centenas de
milissegundos de CPU nossa; um motor de nuvem fica com um corpo de resposta aberto, e abandonar
esse corpo no meio é a diferença entre honrar o `Cancel` e pagar o resto do download. Por isso
`Cancelado` é parâmetro do adaptador de nuvem: ele é consultado **enquanto** o corpo é lido, e
o que já tinha chegado é descartado. O contrato continua sendo o do F1-09 — "nada escrito
depois do `Cancel`" —, só que agora com uma segunda chance de parar antes do fim.

`Onde` é o campo que a política usa: local é padrão, nuvem só liga por escolha do dono
(`jarvis.voz.registro`). Ele mora no motor, não numa tabela paralela, porque "este motor manda
áudio para fora" é propriedade do motor.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import NamedTuple, Protocol, runtime_checkable

IDIOMA_PADRAO = "pt-BR"

Cancelado = Callable[[], bool]
"""" "Já cancelaram?" — consultado antes de trabalhar e antes de entregar o que foi feito."""


class Onde(StrEnum):
    """Onde o motor roda. É a única pergunta que muda a natureza do produto."""

    LOCAL = "local"
    """Nada sai da máquina do dono."""

    NUVEM = "nuvem"
    """O áudio (ASR) ou o texto (TTS) **sai da máquina**. Só liga por escolha do dono."""


class Hipotese(NamedTuple):
    """O que um motor de ASR entendeu de um bloco, com a confiança dele.

    É `NamedTuple` por um motivo prático: o `TranscritorIncremental` do F1-06 já desempacota
    `texto, confianca = motor.transcrever(...)`, e um motor escrito antes desta interface
    continua valendo sem reescrita. Nomear os campos é o que faz a interface ser única sem
    quebrar o que já é regressão.
    """

    texto: str
    confianca: float
    """Em [0, 1]. Quem não tem como estimar devolve 0.0 e **diz** isso no relatório."""


class Sinais(NamedTuple):
    """O que o motor sabe, além do texto, sobre o quanto aquilo era fala (ADR-0043).

    São os três números que o Whisper calcula por segmento — e a Groq devolve os mesmos no
    `verbose_json`. É com eles que o filtro de ruído (`jarvis.voz.ruido`) separa a fala do dono do
    texto que o modelo inventa num trecho de respiração, tosse ou ventilador. `None` = o motor não
    mede (o oráculo, um motor de teste): quem filtra trata como "não sei", nunca como certeza.
    """

    sem_fala: float | None = None
    """`no_speech_prob`, o maior dos segmentos: perto de 1, o modelo acha que não houve fala."""
    logprob: float | None = None
    """`avg_logprob`, a média dos segmentos: perto de 0 é confiança; −1 ou menos é chute."""
    compressao: float | None = None
    """`compression_ratio`, o maior dos segmentos: acima de 2,4 é texto repetido em laço."""


class Transcricao(NamedTuple):
    """O texto do bloco e os sinais de quanto ele era fala."""

    hipotese: Hipotese
    sinais: Sinais = Sinais()


@runtime_checkable
class MotorDeAsr(Protocol):
    """Transcreve um bloco de áudio PCM16 16 kHz mono. Quem é incremental é o transcritor."""

    nome: str
    modelo: str
    licenca: str
    idioma: str
    onde: Onde

    def transcrever(self, amostras: bytes) -> Hipotese:
        """Texto e confiança do bloco inteiro."""
        ...


@runtime_checkable
class MotorDeTts(Protocol):
    """Sintetiza um trecho de texto em PCM16 16 kHz mono. Quem fatia é o sintetizador."""

    nome: str
    voz: str
    licenca: str
    onde: Onde

    def sintetizar(self, texto: str) -> bytes: ...


def transcrever_com_sinais(motor: MotorDeAsr, amostras: bytes) -> Transcricao:
    """O texto e os sinais do bloco. O motor que mede tem `transcrever_com_sinais`; o que não
    mede (o oráculo, um falso de teste) devolve só o texto, com os sinais vazios."""
    detalhado = getattr(motor, "transcrever_com_sinais", None)
    if callable(detalhado):
        resultado = detalhado(amostras)
        if isinstance(resultado, Transcricao):
            return resultado
    return Transcricao(motor.transcrever(amostras))


def nunca_cancelado() -> bool:
    """O `Cancelado` padrão: ninguém cancelou. Função nomeada em vez de `lambda` para o
    relatório de um motor dizer qual cancelamento ele estava consultando."""
    return False


def cancelado_por_epoch(epoch_atual: Callable[[], int], epoch: int) -> Cancelado:
    """ "Cancelado" = o epoch avançou (§3.3 regra 1, ADR-0002).

    O adaptador de nuvem não ganha o `DonoDoEpoch`: ele ganha **uma pergunta**. É o que
    impede um motor de mexer no epoch — ele não tem o objeto que o move.
    """

    def cancelado() -> bool:
        return epoch_atual() > epoch

    return cancelado
