"""A memória de trabalho do turno (ADR-0034): o que as ferramentas trouxeram vale só para ele.

Texto de página, mapa de elementos, scripts e telas que uma tarefa leu são **do turno** (ou da
tarefa em segundo plano): servem para os próximos passos e morrem no fim — nunca vão para a
conversa, para o livro de memória nem para a trilha. Se um fato curto valer para depois, o modelo
o guarda de propósito com `memoria.*`.

Enquanto o turno dura, cada rodada é um pedido novo ao motor com **todos** os resultados até ali.
Doze passos de 6000 caracteres seriam 72 mil a cada rodada: aqui o contexto ganha um orçamento.
O resultado mais novo vai sempre inteiro (é dele que o próximo passo depende); os anteriores vão
inteiros enquanto couberem, do mais novo para o mais velho, e o que não couber vai **podado**
(`ResultadoDeFerramenta.resumo_para_o_modelo`): ferramenta, status, endereço, título e o tamanho
do que saiu — o bastante para o modelo saber o que já fez e, se precisar, ler de novo.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from jarvis.executor.ferramentas import ResultadoDeFerramenta

ORCAMENTO_DE_FERRAMENTAS: Final = 18_000
"""Caracteres de resultados de ferramenta que vão ao motor a cada rodada (fora o mais novo, que vai
sempre inteiro): três resultados cheios, ou um cheio e dezenas de podados."""


def textos_no_contexto(
    feitos: Sequence[ResultadoDeFerramenta], orcamento: int = ORCAMENTO_DE_FERRAMENTAS
) -> tuple[list[str], int]:
    """O texto de cada resultado na ordem em que aconteceram, e quantos foram podados."""
    if not feitos:
        return [], 0
    textos: list[str] = [""] * len(feitos)
    *anteriores, ultimo = feitos
    textos[-1] = ultimo.para_o_modelo()
    restante = orcamento
    podados = 0
    for indice in range(len(anteriores) - 1, -1, -1):
        inteiro = anteriores[indice].para_o_modelo()
        if len(inteiro) <= restante:
            textos[indice] = inteiro
            restante -= len(inteiro)
        else:
            textos[indice] = anteriores[indice].resumo_para_o_modelo()
            restante = max(0, restante - len(textos[indice]))
            podados += 1
    return textos, podados
