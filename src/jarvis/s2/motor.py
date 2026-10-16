"""A fronteira por onde um motor de conversa entra no cérebro (ADR-0025, regra 6).

O mesmo desenho dos motores de voz (ADR-0017, emenda): o motor **traduz** — contexto em
deltas de texto — e **declara de onde ele é**; quem conhece epoch, fatia para o TTS, publica no
barramento e guarda a conversa é o cérebro (`jarvis.s2.cerebro`). Por isso o motor recebe o
cancelamento como **uma pergunta** (`Cancelado`), nunca o dono do epoch.

Três obrigações de todo motor, cobradas pelos testes de contrato:

1. **Sem estado.** `gerar` recebe o contexto inteiro a cada pedido. A conversa é do cérebro:
   a sessão de um motor guardaria o texto *gerado*, e o que conta é o *tocado* (P4) — medido
   na CLI do Claude, que "lembra" do que gerou até o corte
   (`docs/medicoes/s2-provisorio-primeira-fala.md`).
2. **Para de gerar em até `PRAZO_DE_CANCELAMENTO_S`** depois de `cancelado()` virar verdade, e o
   último delta é `Fim(motivo=CANCELADO)`. Parar de *ler* não basta: o processo ou a conexão
   tem de acabar, senão o motor segue gerando (e cobrando) para ninguém.
3. **Fechar o iterador também para tudo.** Quem consome pode desistir no meio (`close()`); o
   motor libera processo e conexão no `finally`.
"""

from __future__ import annotations

from collections.abc import Generator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Literal, Protocol, runtime_checkable

from jarvis.voz.interface import Cancelado, Onde

PRAZO_DE_CANCELAMENTO_S: Final = 0.050
"""ADR-0025, regra 9 (c): do `Cancel` ao motor parado. É o intervalo de consulta do provisório
(`INTERVALO_DE_CONSULTA_S` da ADR-0018), um quadro e meio de áudio."""

INTERVALO_DE_CONSULTA_S: Final = 0.005
"""De quanto em quanto tempo um motor que espera (processo, rede, roteiro) consulta o
cancelamento. Dez vezes menor que o prazo, para o prazo sobrar para matar o processo."""


class Modo(StrEnum):
    """ADR-0025, regra 4: todo turno começa rápido; pensar é exceção, com teto."""

    RAPIDO = "rapido"
    PENSAR = "pensar"


class MotivoDoFim(StrEnum):
    CONCLUIDO = "concluido"
    CANCELADO = "cancelado"
    ERRO = "erro"
    PRAZO = "prazo"


Papel = Literal["dono", "jarvis"]


@dataclass(frozen=True, slots=True)
class Mensagem:
    """Um turno da conversa. Do Jarvis, é sempre o texto **tocado** (P4)."""

    papel: Papel
    texto: str
    interrompida: bool = False
    """O dono falou por cima: `texto` é só o que ele chegou a ouvir."""


@dataclass(frozen=True, slots=True)
class Contexto:
    """Tudo o que o motor recebe num pedido — montado pelo cérebro, a cada pedido."""

    sistema: str
    mensagens: tuple[Mensagem, ...]

    def __post_init__(self) -> None:
        if not self.mensagens or self.mensagens[-1].papel != "dono":
            raise ValueError("o contexto termina no turno do dono: é a ele que se responde")

    @property
    def turno(self) -> str:
        return self.mensagens[-1].texto

    def como_texto(self) -> str:
        """A conversa em texto corrido, para motor que só recebe um texto (a CLI).

        Turno do Jarvis interrompido vai marcado, para o modelo não continuar uma frase que o
        dono não ouviu como se ele tivesse ouvido (§3.3, regra 5).
        """
        if len(self.mensagens) == 1:
            return self.turno
        linhas = ["Conversa até aqui (do Jarvis, só o que o dono chegou a ouvir):"]
        for mensagem in self.mensagens[:-1]:
            quem = "Dono" if mensagem.papel == "dono" else "Jarvis"
            marca = " [interrompido pelo dono aqui]" if mensagem.interrompida else ""
            linhas.append(f"{quem}: {mensagem.texto}{marca}")
        linhas += ["", f"Agora o dono disse: {self.turno}"]
        return "\n".join(linhas)


@dataclass(frozen=True, slots=True)
class Texto:
    texto: str


@dataclass(frozen=True, slots=True)
class Pensar:
    """O motor pede para pensar antes de responder (ADR-0025, regra 4). Sem conteúdo: o
    raciocínio em si nunca vai para o TTS nem para a UI (P10)."""

    motivo: str = ""


@dataclass(frozen=True, slots=True)
class PedidoDeTool:
    """Proposta de chamada. Quem decide é o PDP (P1); o cérebro só a encaminha."""

    tool_id: str
    args: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Fim:
    motivo: MotivoDoFim
    detalhe: str = ""
    uso: Mapping[str, int] = field(default_factory=dict)
    """Tokens e o que mais o motor informar. Vazio quando ele não informa."""


Delta = Texto | Pensar | PedidoDeTool | Fim


@runtime_checkable
class MotorDeConversa(Protocol):
    """O que o cérebro precisa de um motor. `gerar` termina sempre com um `Fim`."""

    @property
    def nome(self) -> str: ...

    @property
    def onde(self) -> Onde: ...

    def gerar(
        self, contexto: Contexto, modo: Modo, cancelado: Cancelado
    ) -> Generator[Delta, None, None]: ...
