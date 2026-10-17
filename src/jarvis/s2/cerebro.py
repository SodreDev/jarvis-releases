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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from jarvis.barramento.contrato import prioridade_canonica, validar
from jarvis.barramento.envelope import Envelope, Tipo, Trust, uuid7
from jarvis.executor.ferramentas import (
    Confirmar,
    ExecutorDeFerramentas,
    ResultadoDeFerramenta,
    negar_sempre,
)
from jarvis.fatiador import Corte, FatiadorDeFala, PedacoDeFala
from jarvis.memoryd.livro import LivroDeMemoria
from jarvis.politica.memoria import AlcanceDeMemoria, Proveniencia, TurnoCorrente
from jarvis.s2.avisos import AvisoLiberado, frase_do_aviso
from jarvis.s2.memoria_do_turno import MemoriaDoTurno, consultar
from jarvis.s2.motor import (
    Contexto,
    Fim,
    Mensagem,
    Modo,
    MotivoDoFim,
    MotorDeConversa,
    PedidoDeTool,
    Pensar,
)
from jarvis.voz.interface import Cancelado, nunca_cancelado
from jarvis.voz.s2_provisorio import PROMPT_DE_SISTEMA

MAXIMO_DE_RODADAS: Final = 4
"""Quantas vezes o motor pode pedir ferramenta num turno antes de ter de responder (ADR-0028)."""
MAXIMO_DE_CHAMADAS_POR_RODADA: Final = 3
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
    ferramentas: list[ResultadoDeFerramenta] = field(default_factory=list)
    """Cada chamada do turno, com o que aconteceu — para a auditoria e para o teste."""
    memoria: MemoriaDoTurno | None = None
    """O que o livro lembrou e foi ao prompt neste turno (fatia 7), com a proveniência."""
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
    ferramentas: ExecutorDeFerramentas | None = None
    """O executor das tools do catálogo v1 (ADR-0028). Sem ele, pedido de tool volta negado."""
    confirmar: Confirmar = negar_sempre
    """Como o dono confirma: a janela liga aqui. Sem janela, toda confirmação é não."""
    lembrar_a_cada_turno: bool = True
    """Com livro, consulta a memória antes de cada resposta (fatia 7, `memoria_do_turno`)."""
    alcance_de_memoria: AlcanceDeMemoria = field(default_factory=AlcanceDeMemoria)
    """O que o dono deixou a memória alcançar (ADR-0026, regra 7) — o D20 decide com ele."""
    ao_lembrar: Callable[[MemoriaDoTurno], None] | None = None
    """Chamada da linha do cérebro quando a consulta termina, antes do motor: é por onde a tela
    mostra "lembrei: …". Quem liga aqui guarda e volta."""
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
        avisos: Sequence[AvisoLiberado] = (),
    ) -> Resposta:
        """Responde a um turno estável do dono, publicando os pedaços enquanto o motor gera.

        `avisos` são os que a fila liberou junto com esta mensagem e que o `s2` decidiu falar
        (ADR-0025, regra 13, decisão do dono): vão **antes** da resposta, em pedaços marcados
        com `notif_ids`, e o motor fica sabendo que já foram ditos — informa, depois responde.
        """
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
        memoria = None
        contexto = self.conversa.contexto()
        if self.livro is not None and self.lembrar_a_cada_turno:
            memoria = consultar(
                self.livro,
                texto_do_dono,
                onde=self.motor.onde,
                motor=self.motor.nome,
                alcance=self.alcance_de_memoria,
            )
            if self.ao_lembrar is not None:
                self.ao_lembrar(memoria)
            if memoria.bloco():
                contexto = Contexto(
                    sistema=f"{contexto.sistema}\n\n{memoria.bloco()}",
                    mensagens=contexto.mensagens,
                )
        if avisos:
            ditos = " ".join(frase_do_aviso(a) for a in avisos)
            contexto = Contexto(
                sistema=f"{contexto.sistema}\n\nAntes desta resposta você já disse ao dono, em "
                f"voz: «{ditos}» Não repita o aviso: responda à mensagem dele.",
                mensagens=contexto.mensagens,
            )
        resposta = Resposta(
            response_id=f"r-{uuid7()}",
            turn_id=turn_id or f"t-{uuid7()}",
            epoch=epoch,
            motor=self.motor.nome,
            ms_ate_contexto=_ms_desde(comeco),
            memoria=memoria,
        )
        fatiador = FatiadorDeFala()
        visto_cancelamento = self._falar_avisos(
            avisos, fatiador, resposta, publicar, comeco, cancelado
        )
        catalogo = self.ferramentas.catalogo_para_o_modelo() if self.ferramentas else ()
        resultados: list[Mensagem] = []
        for _rodada in range(MAXIMO_DE_RODADAS):
            if visto_cancelamento is not None:
                break
            da_vez = Contexto(
                sistema=contexto.sistema,
                mensagens=(*contexto.mensagens, *resultados),
                ferramentas=catalogo,
            )
            pedidos, visto_cancelamento = self._rodada(
                da_vez, modo, cancelado, fatiador, resposta, publicar, comeco
            )
            if (
                visto_cancelamento is not None
                or not pedidos
                or resposta.fim is not MotivoDoFim.CONCLUIDO
            ):
                break
            # O que o motor disse antes de pedir a ferramenta ("deixa eu ver") sai agora: a
            # palavra que esperava o espaço seguinte é fechada, e só então a ferramenta roda.
            for pedaco in fatiador.alimentar(" "):
                self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
            for pedido in pedidos[:MAXIMO_DE_CHAMADAS_POR_RODADA]:
                if cancelado():
                    visto_cancelamento = time.monotonic()
                    break
                resultado = self._chamar(pedido, cancelado)
                resposta.ferramentas.append(resultado)
                resultados.append(Mensagem("ferramenta", resultado.para_o_modelo()))
            if visto_cancelamento is None and cancelado():
                visto_cancelamento = time.monotonic()
        else:
            resposta.detalhe = f"o motor pediu ferramenta {MAXIMO_DE_RODADAS} vezes sem responder"
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

    def _rodada(
        self,
        contexto: Contexto,
        modo: Modo,
        cancelado: Cancelado,
        fatiador: FatiadorDeFala,
        resposta: Resposta,
        publicar: Publicar,
        comeco: float,
    ) -> tuple[list[PedidoDeTool], float | None]:
        """Uma chamada ao motor: publica o texto em pedaços e junta os pedidos de ferramenta."""
        pedidos: list[PedidoDeTool] = []
        visto_cancelamento: float | None = None
        deltas = self.motor.gerar(contexto, modo, cancelado)
        try:
            for delta in deltas:
                if isinstance(delta, Fim):
                    resposta.fim, resposta.detalhe = delta.motivo, delta.detalhe
                    if delta.motivo is MotivoDoFim.CANCELADO:
                        visto_cancelamento = time.monotonic()
                    break
                if isinstance(delta, Pensar):
                    # Regra 4: quem refaz no modo `pensar` (com a ponte) é o chamador.
                    resposta.pediu_pensar = True
                    continue
                if isinstance(delta, PedidoDeTool):
                    pedidos.append(delta)  # o modelo propõe; quem dispõe é o código (P1)
                    continue
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
        return pedidos, visto_cancelamento

    def _chamar(self, pedido: PedidoDeTool, cancelado: Cancelado) -> ResultadoDeFerramenta:
        if self.ferramentas is None:
            return ResultadoDeFerramenta(
                pedido.tool_id, "negado", motivo="nenhuma ferramenta está ligada nesta sessão"
            )
        return self.ferramentas.executar(
            pedido.tool_id,
            pedido.args,
            cancelado=cancelado,
            confirmar=self.confirmar,
            session_id=self.session_id,
        )

    def avisar(
        self,
        avisos: Sequence[AvisoLiberado],
        *,
        epoch: int,
        publicar: Publicar,
        cancelado: Cancelado = nunca_cancelado,
    ) -> Resposta:
        """Piso livre, sem mensagem do dono: só os avisos, sem chamar o motor (regra 12)."""
        comeco = time.monotonic()
        self._pendentes.clear()
        resposta = Resposta(
            response_id=f"r-{uuid7()}", turn_id=f"t-{uuid7()}", epoch=epoch, motor="avisos"
        )
        fatiador = FatiadorDeFala()
        if self._falar_avisos(avisos, fatiador, resposta, publicar, comeco, cancelado) is None:
            for pedaco in fatiador.fechar():
                self._publicar(resposta, pedaco, publicar, comeco, ultimo=pedaco.corte is Corte.FIM)
        else:
            resposta.fim = MotivoDoFim.CANCELADO
        self._pendentes[resposta.response_id] = resposta
        return resposta

    def _falar_avisos(
        self,
        avisos: Sequence[AvisoLiberado],
        fatiador: FatiadorDeFala,
        resposta: Resposta,
        publicar: Publicar,
        comeco: float,
        cancelado: Cancelado,
    ) -> float | None:
        """Publica a frase de cada aviso; devolve o instante do cancelamento, se houve."""
        for aviso in avisos:
            frase = frase_do_aviso(aviso)
            resposta.gerado += frase + " "
            # A frase termina em ponto, e o espaço depois fecha a última palavra: todos os
            # pedaços do aviso saem aqui, e nenhum mistura aviso com a resposta do motor.
            for pedaco in fatiador.alimentar(frase + " "):
                if cancelado():
                    return time.monotonic()
                self._publicar(
                    resposta, pedaco, publicar, comeco, ultimo=False, notif_ids=[aviso.notif_id]
                )
        return time.monotonic() if cancelado() else None

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
        notif_ids: Sequence[str] = (),
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
        if notif_ids:
            payload["notif_ids"] = list(notif_ids)
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
