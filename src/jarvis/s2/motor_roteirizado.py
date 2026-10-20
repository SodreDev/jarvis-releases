"""Motor de conversa de teste: texto roteirizado, entregue em deltas com atraso (ADR-0025).

Serve a duas coisas: testar o stream e o cancelamento sem rede e sem LLM, e medir o **piso do
nosso lado** no harness da primeira fala — com atraso zero, tudo o que sobra no tempo até o
primeiro áudio é nosso (montagem, fatiador, evento, TTS), não do motor.

Ele cumpre o contrato da `jarvis.s2.motor` como um motor de verdade teria de cumprir: espera em
fatias curtas consultando o cancelamento e não entrega delta nenhum depois dele. Quem conta o
que chegou depois do cancelamento é o cérebro — é o número que o teste de aceite (c) da
ADR-0025 cobra de todo motor.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass, field

from jarvis.s2.motor import (
    INTERVALO_DE_CONSULTA_S,
    Contexto,
    Delta,
    Fim,
    Modo,
    MotivoDoFim,
    PedidoDeTool,
    Raciocinio,
    Texto,
)
from jarvis.voz.interface import Cancelado, Onde

Parte = str | PedidoDeTool | Raciocinio
"""Um pedaço do roteiro: texto (cortado em deltas), uma proposta ou um raciocínio (inteiros)."""


def em_deltas(texto: str, *, caracteres: int = 4) -> tuple[str, ...]:
    """Corta o texto em deltas de poucos caracteres, como um stream de tokens faria —
    inclusive no meio da palavra, que é o caso que o fatiador tem de aguentar."""
    return tuple(texto[i : i + caracteres] for i in range(0, len(texto), caracteres))


@dataclass(slots=True)
class MotorRoteirizado:
    """Responde sempre o roteiro, um delta por vez."""

    resposta: Callable[[Contexto], str | Sequence[Parte]] | str = (
        "Depois de quinta vem sexta-feira."
    )
    """Texto, ou (por função) uma sequência de textos, pedidos de ferramenta e raciocínios — é
    como o teste do laço de ferramentas faz o motor "propor" (ADR-0028) e "pensar" (ADR-0031)
    sem LLM."""
    primeiro_atraso_s: float = 0.0
    """Do pedido ao primeiro delta: o "tempo até o primeiro token" do motor."""
    atraso_entre_deltas_s: float = 0.0
    caracteres_por_delta: int = 4
    nome: str = "roteirizado (teste)"
    onde: Onde = Onde.LOCAL
    pedidos: list[Contexto] = field(default_factory=list)
    """Cada contexto recebido — é como o teste prova que o motor não guarda estado."""
    _dormir: Callable[[float], None] = field(default=time.sleep, repr=False)

    def gerar(
        self, contexto: Contexto, modo: Modo, cancelado: Cancelado
    ) -> Generator[Delta, None, None]:
        del modo  # o roteiro não pensa
        self.pedidos.append(contexto)
        roteiro = self.resposta if isinstance(self.resposta, str) else self.resposta(contexto)
        partes: Sequence[Parte] = [roteiro] if isinstance(roteiro, str) else roteiro
        deltas: list[Parte] = []
        for parte in partes:
            if isinstance(parte, str):
                deltas += em_deltas(parte, caracteres=self.caracteres_por_delta)
            else:
                deltas.append(parte)
        for indice, delta in enumerate(deltas):
            atraso = self.primeiro_atraso_s if indice == 0 else self.atraso_entre_deltas_s
            if not self._esperar(atraso, cancelado):
                yield Fim(MotivoDoFim.CANCELADO)
                return
            if cancelado():
                yield Fim(MotivoDoFim.CANCELADO)
                return
            yield Texto(delta) if isinstance(delta, str) else delta
            if cancelado():
                # O consumidor viu o cancelamento depois deste delta; nada mais é gerado.
                yield Fim(MotivoDoFim.CANCELADO)
                return
        yield Fim(MotivoDoFim.CONCLUIDO, uso={"deltas": len(deltas)})

    def _esperar(self, segundos: float, cancelado: Cancelado) -> bool:
        """Espera em fatias, consultando o cancelamento. `False` se cancelaram no meio."""
        fim = time.monotonic() + segundos
        while True:
            if cancelado():
                return False
            restante = fim - time.monotonic()
            if restante <= 0:
                return True
            self._dormir(min(INTERVALO_DE_CONSULTA_S, restante))
