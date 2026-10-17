"""A interface única de decisão por perguntas fechadas (ADR-0029).

Um classificador de decisão **não gera texto**: recebe um estado e perguntas tipadas e devolve
probabilidades. É o formato do Jev (TypeSafe, System One), mas a interface não é do Jev — o
detector de endereçamento e a seleção de tools (ADR-0024) falam com `ClassificadorDeDecisao`, e
trocar o adaptador (OpenRouter, um modelo local, um fake de teste) não muda quem pergunta.

Três tipos de pergunta, como no serviço:

- `PerguntaNoul`: sim/não; a resposta é a probabilidade do sim. **Formule para que "alto" seja
  sim** ("o falante está falando com o Jarvis?", nunca "o falante NÃO está falando com ele?").
- `PerguntaEscolha`: uma entre opções; a resposta traz a probabilidade de cada uma. O modelo
  puxa para a **primeira** opção (docs.typesafe.ai, jaggedness do 1.13): ponha a segura primeiro.
- `PerguntaNota`: um ponto numa escala ordenada de 2 a 10 níveis.

Nada aqui autoriza coisa alguma (ADR-0004): a resposta é uma estimativa que o código do Jarvis
pesa com limiar e política.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from jarvis.voz.interface import Cancelado, Onde, nunca_cancelado


class DecisaoIndisponivel(RuntimeError):
    """O classificador não respondeu (prazo, rede, serviço fora, formato inesperado).

    Quem pergunta decide o que fazer; a regra do produto é **na dúvida, não agir**."""


class DecisaoRecusada(DecisaoIndisponivel):
    """O serviço entendeu e recusou (chave inválida, sem crédito, pedido fora do contrato).

    É indisponível do mesmo jeito, mas o dono precisa ouvir o motivo certo, e não "sem rede"."""


@dataclass(frozen=True, slots=True)
class PerguntaNoul:
    instrucoes: str
    sim: str
    nao: str


@dataclass(frozen=True, slots=True)
class PerguntaEscolha:
    instrucoes: str
    opcoes: Mapping[str, str]
    """Nome da opção → como reconhecê-la. A ordem importa (a primeira atrai)."""


@dataclass(frozen=True, slots=True)
class PerguntaNota:
    instrucoes: str
    niveis: Sequence[str]
    """Do menor para o maior, cada nível descrito em palavras."""


Pergunta = PerguntaNoul | PerguntaEscolha | PerguntaNota


@dataclass(frozen=True, slots=True)
class RespostaNoul:
    probabilidade: float
    """A probabilidade do **sim**, de 0 a 1."""


@dataclass(frozen=True, slots=True)
class RespostaEscolha:
    escolha: str
    confianca: float
    probabilidades: Mapping[str, float] = field(default_factory=dict)

    @property
    def probabilidade_da_escolha(self) -> float:
        return float(self.probabilidades.get(self.escolha, 0.0))


@dataclass(frozen=True, slots=True)
class RespostaNota:
    nota: float
    confianca: float
    probabilidades: Mapping[int, float] = field(default_factory=dict)


Resposta = RespostaNoul | RespostaEscolha | RespostaNota


@runtime_checkable
class ClassificadorDeDecisao(Protocol):
    """Perguntas fechadas sobre um estado. Sem geração de texto, sem estado entre chamadas."""

    nome: str
    onde: Onde

    def decidir(
        self,
        estado: str | Mapping[str, Any] | Sequence[Any],
        perguntas: Mapping[str, Pergunta],
        *,
        cancelado: Cancelado = nunca_cancelado,
    ) -> dict[str, Resposta]:
        """Uma resposta por pergunta, com os mesmos nomes. `DecisaoIndisponivel` se falhar."""
        ...
