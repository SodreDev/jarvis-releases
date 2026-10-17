"""O cérebro: uma conversa contínua, dona do contexto, que responde em stream (ADR-0025).

Decisão do dono (2026-10-16): **um** cérebro com conversa contínua, interrompível, que começa a
falar enquanto gera e, interrompido, para de falar **e de gerar**. Este módulo é a parte do
`s2` que faz isso, sem processo e sem barramento — quem publica é o chamador, por `publicar` —,
para o contrato ser testado inteiro em memória:

- **A conversa é nossa** (regra 2). O motor recebe o contexto montado aqui a cada pedido.
- **Só o tocado volta** (regra 3). A resposta só entra na conversa por `ouvido`, com o texto que
  o dono ouviu; resposta de que ninguém confirmou o tocado **não existe** para o modelo (§3.3,
  regra 4) — inclusive a que foi gerada inteira.
- **Pedaço por fronteira** (regra 7). O texto do motor passa pelo `FatiadorDeFala` (a mesma regra
  do TTS) e sai um `ResponseChunk` por pedaço.
- **Cancelamento** (regra 9). Visto o cancelamento, nada mais daquele epoch é publicado, e o
  iterador do motor é fechado — é o `finally` dele que mata processo ou conexão. O tempo entre
  ver o cancelamento e o motor parado é medido e fica na `Resposta`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

from jarvis.barramento.contrato import prioridade_canonica, validar
from jarvis.barramento.envelope import Envelope, Tipo, Trust, uuid7
from jarvis.fatiador import Corte, FatiadorDeFala, PedacoDeFala
from jarvis.memoryd.livro import LivroDeMemoria
from jarvis.politica.memoria import Proveniencia, TurnoCorrente
from jarvis.s2.motor import (
    Contexto,
    Fim,
    Mensagem,
    Modo,
    MotivoDoFim,
    MotorDeConversa,
    Pensar,
    Texto,
)
from jarvis.voz.interface import Cancelado, nunca_cancelado
from jarvis.voz.s2_provisorio import PROMPT_DE_SISTEMA

TURNOS_NO_CONTEXTO: Final = 12
"""Orçamento fixo de conversa no contexto (regra 5): os últimos turnos estáveis. O resumo do que
ficou para trás é trabalho de segundo plano, fora desta fatia."""

Publicar = Callable[[dict[str, Any]], None]
"""Recebe o payload de um `ResponseChunk`. No processo, vira envelope (`envelope_do_pedaco`)."""


@dataclass(slots=True)
class Conversa:
    """Os turnos estáveis da sessão. Do Jarvis, só o que tocou."""

    sistema: str = PROMPT_DE_SISTEMA
    turnos: list[Mensagem] = field(default_factory=list)
    maximo: int = TURNOS_NO_CONTEXTO

    def contexto(self) -> Contexto:
        return Contexto(sistema=self.sistema, mensagens=tuple(self.turnos[-self.maximo :]))


@dataclass(slots=True)
class Resposta:
    """O que aconteceu num turno, para a auditoria e para o harness."""

    response_id: str
    turn_id: str
    epoch: int
    motor: str
    gerado: str = ""
    """Tudo o que o motor entregou — **não** é o que o dono ouviu, e não volta ao contexto."""
    publicados: list[dict[str, Any]] = field(default_factory=list)
    fim: MotivoDoFim = MotivoDoFim.CONCLUIDO
    detalhe: str = ""
    pediu_pensar: bool = False
    deltas_depois_do_cancelamento: int = 0
    ms_ate_contexto: float = 0.0
    ms_ate_primeiro_pedaco: float | None = None
    ms_cancelamento_ate_motor_parado: float | None = None

    @property
    def cancelada(self) -> bool:
        return self.fim is MotivoDoFim.CANCELADO


@dataclass(slots=True)
class Cerebro:
    """Uma conversa, um motor trocável, e o stream de pedaços de fala."""

    motor: MotorDeConversa
    conversa: Conversa = field(default_factory=Conversa)
    livro: LivroDeMemoria | None = None
    """O histórico persistente (ADR-0026, M1). Sem ele, a conversa vive só na memória."""
    session_id: str = ""
    turno_corrente: TurnoCorrente | None = None
    _pendentes: dict[str, Resposta] = field(default_factory=dict)

    @property
    def proveniencia(self) -> Proveniencia:
        """A origem de uma escrita de memória neste turno — do estado do cérebro, nunca do
        modelo (ADR-0026, regra 2). Sem histórico não há episódio, e a escrita é negada."""
        return Proveniencia(turno=self.turno_corrente, motor=self.motor.nome)

    def responder(
        self,
        texto_do_dono: str,
        *,
        epoch: int,
        publicar: Publicar,
        turn_id: str = "",
        cancelado: Cancelado = nunca_cancelado,
        modo: Modo = Modo.RAPIDO,
        trust: str = "user_voice",
    ) -> Resposta:
        """Responde a um turno estável do dono, publicando os pedaços enquanto o motor gera."""
        comeco = time.monotonic()
        # Resposta anterior sem `ouvido`: ninguém confirmou que tocou, então não existe (P4).
        self._pendentes.clear()
        self.conversa.turnos.append(Mensagem("dono", texto_do_dono))
        self.turno_corrente = None
        if self.livro is not None:
            episodio = self.livro.gravar_turno(
                session_id=self.session_id, papel="dono", texto=texto_do_dono, trust=trust
            )
            self.turno_corrente = TurnoCorrente(episodio, texto_do_dono, trust)
        contexto = self.conversa.contexto()
        resposta = Resposta(
            response_id=f"r-{uuid7()}",
            turn_id=turn_id or f"t-{uuid7()}",
            epoch=epoch,
            motor=self.motor.nome,
            ms_ate_contexto=_ms_desde(comeco),
        )
        fatiador = FatiadorDeFala()
        deltas = self.motor.gerar(contexto, modo, cancelado)
        visto_cancelamento: float | None = None
        try:
            for delta in deltas:
                if visto_cancelamento is not None:
                    resposta.deltas_depois_do_cancelamento += isinstance(delta, Texto)
                    continue
                if isinstance(delta, Fim):
                    resposta.fim, resposta.detalhe = delta.motivo, delta.detalhe
                    if delta.motivo is MotivoDoFim.CANCELADO:
                        visto_cancelamento = time.monotonic()
                    break
                if isinstance(delta, Pensar):
                    # Regra 4: quem refaz no modo `pensar` (com a ponte) é o chamador.
                    resposta.pediu_pensar = True
                    continue
                if not isinstance(delta, Texto):
                    continue  # pedido de tool: fora da fatia 1 (sem PDP no caminho ainda)
                resposta.gerado += delta.texto
                for pedaco in fatiador.alimentar(delta.texto):
                    if cancelado():
                        visto_cancelamento = time.monotonic()
                        break
                    self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
                if visto_cancelamento is None and cancelado():
                    visto_cancelamento = time.monotonic()
                if visto_cancelamento is not None:
                    break
        finally:
            # Fechar o iterador é o que faz o motor parar de gerar (o `finally` dele).
            deltas.close()
        if visto_cancelamento is None and cancelado():
            visto_cancelamento = time.monotonic()
        if visto_cancelamento is not None or resposta.fim is MotivoDoFim.CANCELADO:
            resposta.fim = MotivoDoFim.CANCELADO
            parado = time.monotonic()
            resposta.ms_cancelamento_ate_motor_parado = (
                (parado - visto_cancelamento) * 1000.0 if visto_cancelamento is not None else 0.0
            )
        else:
            for pedaco in fatiador.fechar():
                self._publicar(resposta, pedaco, publicar, comeco, ultimo=pedaco.corte is Corte.FIM)
        self._pendentes[resposta.response_id] = resposta
        return resposta

    def ouvido(
        self,
        response_id: str,
        texto_tocado: str,
        *,
        interrompida: bool,
        played_ms: int | None = None,
    ) -> None:
        """O que de fato tocou da resposta — só isso entra na conversa (regra 3, P4).

        Com histórico, o turno vai para o livro com o `played_ms` real: sem ele, o livro recusa.
        """
        if self._pendentes.pop(response_id, None) is None:
            return  # resposta velha, já substituída por um turno novo do dono
        if not (texto_tocado or interrompida):
            return
        self.conversa.turnos.append(Mensagem("jarvis", texto_tocado, interrompida))
        if self.livro is not None:
            self.livro.gravar_turno(
                session_id=self.session_id,
                papel="jarvis",
                texto=texto_tocado,
                trust="system",
                played_ms=played_ms,
                interrompida=interrompida,
            )

    def _publicar(
        self,
        resposta: Resposta,
        pedaco: PedacoDeFala,
        publicar: Publicar,
        comeco: float,
        *,
        ultimo: bool,
    ) -> None:
        payload: dict[str, Any] = {
            "response_id": resposta.response_id,
            "turn_id": resposta.turn_id,
            "epoch": resposta.epoch,
            "seq": len(resposta.publicados),
            "text": pedaco.texto,
            "boundary": str(pedaco.corte),
            "last": ultimo,
        }
        if ultimo:
            # Nunca `cancelado`: resposta cancelada não publica o último pedaço (regra 9).
            payload["end_reason"] = str(resposta.fim)
        if resposta.ms_ate_primeiro_pedaco is None and pedaco.texto:
            resposta.ms_ate_primeiro_pedaco = _ms_desde(comeco)
        resposta.publicados.append(payload)
        publicar(payload)


def envelope_do_pedaco(session_id: str, payload: dict[str, Any]) -> Envelope:
    """O `ResponseChunk` no envelope da §3.1, validado na borda como qualquer evento."""
    return validar(
        Envelope(
            session_id=session_id,
            epoch=int(payload["epoch"]),
            source="s2",
            trust=Trust.SYSTEM,
            priority=prioridade_canonica(Tipo.RESPONSE_CHUNK, payload),
            type=Tipo.RESPONSE_CHUNK,
            payload=payload,
        )
    )


def _ms_desde(comeco: float) -> float:
    return (time.monotonic() - comeco) * 1000.0
