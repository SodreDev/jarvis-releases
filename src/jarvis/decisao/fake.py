"""O classificador de mentira dos testes: responde o que o roteiro mandar, sem rede.

Existe para o detector e o laço serem exercitados com respostas conhecidas — probabilidade
alta, baixa, no meio, serviço fora, lento — sem tocar a nuvem (a suíte não fala com serviço de
verdade). Não imita o modelo: não entende a fala, só devolve o que foi roteirizado.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from jarvis.decisao.interface import (
    DecisaoIndisponivel,
    Pergunta,
    Resposta,
    RespostaEscolha,
    RespostaNoul,
)
from jarvis.voz.interface import Cancelado, Onde, nunca_cancelado

Roteiro = Callable[[Any, Mapping[str, Pergunta]], Mapping[str, Resposta]]


@dataclass(slots=True)
class ClassificadorFalso:
    roteiro: Roteiro
    nome: str = "decisao-falsa"
    onde: Onde = Onde.LOCAL
    atraso_s: float = 0.0
    falhar_com: str = ""
    """Texto não vazio: toda chamada levanta `DecisaoIndisponivel` com ele."""
    chamadas: list[tuple[Any, tuple[str, ...]]] = field(default_factory=list)

    def decidir(
        self,
        estado: str | Mapping[str, Any] | Sequence[Any],
        perguntas: Mapping[str, Pergunta],
        *,
        cancelado: Cancelado = nunca_cancelado,
    ) -> dict[str, Resposta]:
        self.chamadas.append((estado, tuple(perguntas)))
        if self.atraso_s:
            time.sleep(self.atraso_s)
        if self.falhar_com:
            raise DecisaoIndisponivel(self.falhar_com)
        return dict(self.roteiro(estado, perguntas))


def endereco(
    probabilidade: float, intencao: str = "resposta", probabilidade_da_intencao: float = 0.9
) -> Roteiro:
    """Um roteiro do detector de endereçamento: `p` de falar com o Jarvis e a intenção dita."""

    def responder(_estado: Any, perguntas: Mapping[str, Pergunta]) -> Mapping[str, Resposta]:
        resto = (1.0 - probabilidade_da_intencao) / max(1, len(perguntas) - 1)
        return {
            "falando_com_o_jarvis": RespostaNoul(probabilidade),
            "pedido": RespostaEscolha(
                escolha=intencao,
                confianca=probabilidade_da_intencao,
                probabilidades={
                    nome: (probabilidade_da_intencao if nome == intencao else resto)
                    for nome in perguntas["pedido"].opcoes  # type: ignore[union-attr]
                },
            ),
        }

    return responder
