"""Fila de prioridades P0–P4 com coalescing obrigatório (§3.2, §3.4).

Duas propriedades que a SPEC cobra e que esta fila garante por construção:

* **P0 preempta tudo.** Retirada é sempre da banda mais alta com trabalho pendente, e a
  banda P0 não tem teto: `Cancel` e `speech_started` não podem ser recusados por fila cheia
  (P3 — interromper vence tudo).
* **Hipótese substitui hipótese.** Dez parciais em 200 ms deixam uma entrada na fila, não
  dez: eventos com a mesma chave de coalescing se sobrescrevem, sem perder posição.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

from jarvis.barramento.envelope import Envelope, Prioridade, Tipo

TIPOS_COALESCIVEIS: frozenset[Tipo] = frozenset(
    {Tipo.PARTIAL_TRANSCRIPT, Tipo.TURN_PREDICTION, Tipo.STATE_REVISION, Tipo.AUDIO_ACTIVITY}
)
"""Tipos cuja mensagem nova **substitui** a antiga: são hipóteses sobre o mesmo instante.

Fora desta lista nada é coalescido — `FinalTranscript`, `ToolResult`, `PolicyDecision` e
`PlaybackProgress` são fatos, e perder um deles muda o histórico (P4) ou a auditoria.
"""


class FilaCheia(RuntimeError):
    """Banda P1–P4 sem espaço. Nunca acontece em P0, por projeto."""


def chave_de_coalescing(envelope: Envelope) -> str | None:
    """Chave que torna duas mensagens a mesma hipótese, ou `None` se o evento é um fato."""
    if envelope.type not in TIPOS_COALESCIVEIS:
        return None
    if envelope.type is Tipo.AUDIO_ACTIVITY:
        # `speech_started` (P0) nunca é coalescido: é o gatilho do barge-in.
        if bool(envelope.payload.get("speech")):
            return None
        return f"{envelope.type}|{envelope.session_id}|{envelope.payload['device_id']}"
    if envelope.type is Tipo.STATE_REVISION:
        return (
            f"{envelope.type}|{envelope.session_id}|{envelope.epoch}|{envelope.payload['task_id']}"
        )
    return f"{envelope.type}|{envelope.session_id}|{envelope.epoch}"


@dataclass(slots=True)
class FilaDePrioridade:
    """Uma banda por prioridade, FIFO dentro da banda, coalescing por chave."""

    capacidade_por_banda: int = 1024
    _bandas: dict[Prioridade, OrderedDict[str, Envelope]] = field(init=False)
    coalescidos: int = field(default=0, init=False)
    """Quantas hipóteses foram substituídas — a métrica do aceite (d)."""

    def __post_init__(self) -> None:
        self._bandas = {p: OrderedDict() for p in Prioridade}

    def __len__(self) -> int:
        return sum(len(banda) for banda in self._bandas.values())

    def pendentes(self, prioridade: Prioridade) -> int:
        return len(self._bandas[prioridade])

    def publicar(self, envelope: Envelope) -> None:
        banda = self._bandas[envelope.priority]
        chave = chave_de_coalescing(envelope)
        if chave is not None and chave in banda:
            banda[chave] = envelope  # substitui no lugar: a posição na fila é preservada
            self.coalescidos += 1
            return
        if envelope.priority is not Prioridade.P0 and len(banda) >= self.capacidade_por_banda:
            raise FilaCheia(f"banda {envelope.priority} cheia ({self.capacidade_por_banda})")
        banda[chave if chave is not None else envelope.event_id] = envelope

    def retirar(self) -> Envelope | None:
        """Devolve o próximo evento: P0 primeiro, FIFO dentro da banda."""
        for prioridade in Prioridade:
            banda = self._bandas[prioridade]
            if banda:
                _, envelope = banda.popitem(last=False)
                return envelope
        return None

    def descartar_epoch(
        self, epoch: int, *, manter: frozenset[Tipo] = frozenset()
    ) -> list[Envelope]:
        """Esvazia o que pertence a um epoch invalidado (§3.3 regras 2 e 6).

        Devolve o que foi descartado, para o log — descarte silencioso não é auditável.
        Os tipos em `manter` continuam na fila (as exceções da regra 6).
        """
        descartados: list[Envelope] = []
        for banda in self._bandas.values():
            for chave in list(banda):
                envelope = banda[chave]
                if envelope.epoch == epoch and envelope.type not in manter:
                    descartados.append(banda.pop(chave))
        return descartados
