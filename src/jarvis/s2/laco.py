"""O laço canônico do agente (ADR-0072): o Jarvis e o subagente passam pelo MESMO código.

Dono, 2026-11-16: o Jarvis é um agente-CLI com voz. A mensagem do usuário (a transcrição entra
como mensagem normal, marcada como voz) vai ao modelo com todas as ferramentas, a memória e as
skills; o modelo pensa e propõe; o código valida, executa e devolve o resultado ao modelo, que
itera até terminar. O subagente roda o mesmo laço com a etapa delegada.

Este módulo é o pedaço que os dois compartilham — e o único lugar em que o modelo é chamado:

- `rodada_do_agente`: chama o motor e separa o que ele mandou (fala, raciocínio, chamada de
  ferramenta, fim). O motor que chama ferramenta pelo protocolo de texto (ADR-0028) passa pelo
  `LeitorDoProtocolo`; o de chamada nativa (ADR-0072) já entrega `PedidoDeTool`. Quem chama diz
  `quem` é («jarvis», «subagente», …): os observadores (a suíte do laço) veem toda rodada;
- `mensagens_das_ferramentas`: o resultado de cada ferramenta volta ao modelo como mensagem, junto
  da chamada que o gerou (o par que o provedor nativo exige);
- `com_a_chamada`: anota no resultado os argumentos da chamada.

O turno (`jarvis.s2.cerebro`) e a tarefa (`jarvis.s2.tarefa_do_pedido`, `jarvis.tarefas.motores`)
só decidem o que fazer com o que a rodada trouxe: falar (o turno) ou seguir (a tarefa).
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterator, Sequence
from dataclasses import replace
from typing import TYPE_CHECKING, Final

from jarvis.s2.motor import (
    Contexto,
    Delta,
    Fim,
    Mensagem,
    Modo,
    MotivoDoFim,
    MotorDeConversa,
    PedidoDeTool,
    Texto,
)
from jarvis.s2.protocolo import LeitorDoProtocolo
from jarvis.s2.rascunho import textos_no_contexto
from jarvis.voz.interface import Cancelado

if TYPE_CHECKING:
    from jarvis.executor.ferramentas import ResultadoDeFerramenta

QUEM_JARVIS: Final = "jarvis"
QUEM_SUBAGENTE: Final = "subagente"
QUEM_MONITOR: Final = "monitor"
"""O agente monitor das redes (ADR-0073): o mesmo laço, com as ferramentas dele."""
QUEM_CHAMADA: Final = "chamada"
"""O agente da chamada (ADR-0074): o mesmo laço, com as 6 ferramentas da ligação e nada mais."""
QUEM_CANAL_DO_DONO: Final = "canal_do_dono"
"""O agente do canal do dono (ADR-0074): acha o chat do dono no WhatsApp Web lendo a lista,
manda a ação pendente e lê a resposta dele."""

ObservadorDaRodada = Callable[[str, Contexto], None]
"""Recebe `quem` e o contexto de cada rodada, antes de o motor gerar (a suíte do laço)."""
_OBSERVADORES: list[ObservadorDaRodada] = []


def observar(observador: ObservadorDaRodada) -> Callable[[], None]:
    """Liga um observador de rodadas; devolve como desligar."""
    _OBSERVADORES.append(observador)

    def desligar() -> None:
        if observador in _OBSERVADORES:
            _OBSERVADORES.remove(observador)

    return desligar


Envolver = Callable[[Iterator[Delta]], Iterator[Delta]]
"""Quem mede (`jarvis.s2.consumo.medir`) embrulha os deltas crus do motor."""


def rodada_do_agente(
    motor: MotorDeConversa,
    contexto: Contexto,
    modo: Modo,
    cancelado: Cancelado,
    *,
    quem: str,
    envolver: Envolver | None = None,
) -> Generator[Delta, None, None]:
    """Uma chamada ao modelo, já separada: `Texto` (fala), `Raciocinio`, `Pensar`, `PedidoDeTool`
    e, por último, `Fim`. Fechar este gerador fecha o do motor (o cancelamento para a geração).

    O fim cancelado não esvazia o leitor: o que ele segurava era meio de protocolo ou de frase, e
    ninguém mais vai ouvir."""
    for observador in tuple(_OBSERVADORES):
        observador(quem, contexto)
    leitor = LeitorDoProtocolo()
    crus: Iterator[Delta] = motor.gerar(contexto, modo, cancelado)
    deltas = envolver(crus) if envolver is not None else crus
    try:
        for delta in deltas:
            if isinstance(delta, Texto):
                yield from leitor.alimentar(delta.texto)
            elif isinstance(delta, Fim):
                if delta.motivo is not MotivoDoFim.CANCELADO:
                    yield from leitor.fechar()
                yield delta
                return
            else:
                yield delta
        yield from leitor.fechar()
    finally:
        fechar = getattr(deltas, "close", None)
        if callable(fechar):
            fechar()


def com_a_chamada(resultado: ResultadoDeFerramenta, pedido: PedidoDeTool) -> ResultadoDeFerramenta:
    """O resultado com os argumentos da chamada que o gerou. O id da chamada nativa não precisa
    voltar: o motor remonta o par chamada → resultado com um id seu, o mesmo nos dois lados."""
    return replace(resultado, argumentos=dict(pedido.args))


def mensagens_das_ferramentas(
    feitos: Sequence[ResultadoDeFerramenta],
) -> tuple[list[Mensagem], int]:
    """O resultado de cada ferramenta, na ordem, como mensagem ao modelo — com a chamada que o
    gerou — e quantos foram podados pelo orçamento (`jarvis.s2.rascunho`)."""
    textos, podados = textos_no_contexto(feitos)
    mensagens = [
        Mensagem(
            "ferramenta",
            texto,
            chamada=PedidoDeTool(
                resultado.tool_id,
                dict(resultado.argumentos),
                chamada_id=f"chamada-{indice}",
            ),
        )
        for indice, (resultado, texto) in enumerate(zip(feitos, textos, strict=True))
    ]
    return mensagens, podados


__all__ = [
    "QUEM_CANAL_DO_DONO",
    "QUEM_CHAMADA",
    "QUEM_JARVIS",
    "QUEM_MONITOR",
    "QUEM_SUBAGENTE",
    "com_a_chamada",
    "mensagens_das_ferramentas",
    "observar",
    "rodada_do_agente",
]
