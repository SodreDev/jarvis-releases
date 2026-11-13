"""Guarda de laço da tarefa: o passo que se repete sem avançar (ADR-0062).

A tarefa que planeja passos (a de um pedido do dono, ADR-0038, e a do motor `agente`) só parava
no teto de passos e de tempo (ADR-0059). Com «até terminar» nem isso: um modelo que relê a mesma
página, ou que vai e volta entre duas abas, gastava passos e dinheiro até o dono mandar parar. A
`recuperacao` (`jarvis.s2.recuperacao`) já recusa repetir a ação que **falhou**; aqui é a que dá
certo e não muda nada.

Um passo é a ação (ferramenta e argumentos, em ordem fixa) **e o que ela devolveu** (status,
dados, motivo). Comparar só o nome da ferramenta daria falso positivo: rolar e ler, rolar e ler é
o jeito certo de ler uma página longa — o texto lido muda a cada volta. Comparando o resultado, só
o vai-e-volta que não traz nada novo conta como laço.

Conta como laço:

1. **a mesma ação com o mesmo resultado `IDENTICAS_SEGUIDAS` vezes seguidas** (A A A);
2. **um ciclo de período 2 ou 3 que se repete inteiro** (A B A B, A B C A B C);
3. **`PASSOS_SEM_NOVIDADE` passos seguidos sem nada novo**: cada um repete uma ação e um
   resultado que a tarefa já tinha visto (o ciclo mais longo, que os dois de cima não pegam). Um
   passo novo no meio zera a conta: rolar a página dá sempre o mesmo «ok», mas a leitura depois
   dele traz texto novo.

Na primeira vez, **aviso**: a nota vai ao motor no próximo passo ("você está repetindo; mude de
caminho ou termine") e a linha vai à tela. Se o laço volta depois do aviso, **parada**: a tarefa
acaba como no teto quando o dono diz «não» (o resumo do que fez, estado `falhou`), com a razão
dita. A guarda vive a tarefa inteira: «mais 50» e «até terminar» não a zeram.

A ideia (chamada idêntica por hash e vai-e-volta de período 2 e 3, com um aviso antes de barrar)
é a do `LoopGuard` do OpenJarvis (`agents/loop_guard.py`, Apache-2.0); o código é do Jarvis.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from jarvis.executor.ferramentas import ResultadoDeFerramenta
    from jarvis.s2.motor import PedidoDeTool

IDENTICAS_SEGUIDAS: Final = 3
"""A mesma ação com o mesmo resultado, seguidas: na terceira, é laço."""
PERIODOS: Final = (2, 3)
"""Os ciclos que contam (A B A B, A B C A B C), cada um repetido inteiro duas vezes."""
PASSOS_SEM_NOVIDADE: Final = 6
"""Passos seguidos em que nada é novo (ação e resultado já vistos na tarefa)."""


class TipoDeLaco(StrEnum):
    IDENTICA = "identica"
    CICLO = "ciclo"
    SEM_NOVIDADE = "sem_novidade"


class AcaoDoLaco(StrEnum):
    AVISO = "aviso"
    """A primeira vez: a nota vai ao motor e a tarefa segue."""
    PARADA = "parada"
    """Depois do aviso: a tarefa acaba com o resumo."""


@dataclass(frozen=True, slots=True)
class Laco:
    tipo: TipoDeLaco
    periodo: int
    """1 na ação idêntica; 2 ou 3 no ciclo; os passos sem nada novo no `SEM_NOVIDADE`."""
    ferramentas: tuple[str, ...]
    """As ferramentas do laço, na ordem (só para a tela e a nota; a trilha leva a última)."""
    acao: AcaoDoLaco

    def nota_ao_motor(self) -> str:
        """O aviso ao motor, na rodada seguinte. Diz o que se repete e o que fazer — não manda."""
        if self.tipo is TipoDeLaco.IDENTICA:
            oque = f"a mesma ação ({self.ferramentas[0]}, mesmos argumentos) devolveu o mesmo"
        elif self.tipo is TipoDeLaco.CICLO:
            oque = f"os mesmos passos em ciclo ({' → '.join(self.ferramentas)}) devolvem o mesmo"
        else:
            oque = (
                f"os últimos {self.periodo} passos ({', '.join(self.ferramentas)}) só repetiram "
                "ações e devolveram o mesmo"
            )
        return (
            f"ATENÇÃO, LAÇO: {oque} resultado, sem avançar. Não repita: mude de caminho, ou "
            "termine agora dizendo ao dono o que já ficou feito e o que faltou. Se o laço "
            "continuar, a tarefa para."
        )

    def linha_na_tela(self) -> str:
        if self.tipo is TipoDeLaco.IDENTICA:
            oque = f"{self.ferramentas[0]} repetida com o mesmo resultado"
        elif self.tipo is TipoDeLaco.CICLO:
            oque = f"ciclo {' → '.join(self.ferramentas)} sem nada novo"
        else:
            oque = f"{self.periodo} passos sem nada novo"
        if self.acao is AcaoDoLaco.AVISO:
            return f"{oque}: avisei o motor para mudar de caminho"
        return f"{oque} de novo, depois do aviso: parei a tarefa"


def marca_do_passo(pedido: PedidoDeTool, resultado: ResultadoDeFerramenta) -> str:
    """A ação e o que ela devolveu, num hash curto: dois passos com a mesma marca não mudaram
    nada. Só a marca fica na memória da guarda — nunca o resultado."""
    corpo = _canonico(
        [pedido.tool_id, pedido.args, resultado.status, resultado.dados, resultado.motivo]
    )
    return hashlib.sha256(corpo.encode("utf-8", "replace")).hexdigest()[:16]


def _canonico(valor: Any) -> str:
    try:
        return json.dumps(valor, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return repr(valor)


@dataclass(slots=True)
class GuardaDeLaco:
    """Uma por tarefa. `observar` cada passo executado, na ordem."""

    identicas_seguidas: int = IDENTICAS_SEGUIDAS
    passos_sem_novidade: int = PASSOS_SEM_NOVIDADE
    avisou: bool = False
    _marcas: list[str] = field(default_factory=list)
    _ferramentas: list[str] = field(default_factory=list)
    _vistas: set[str] = field(default_factory=set)
    _sem_novidade: int = 0

    def observar(self, pedido: PedidoDeTool, resultado: ResultadoDeFerramenta) -> Laco | None:
        marca = marca_do_passo(pedido, resultado)
        self._marcas.append(marca)
        self._ferramentas.append(pedido.tool_id)
        self._sem_novidade = self._sem_novidade + 1 if marca in self._vistas else 0
        self._vistas.add(marca)
        achado = self._achar()
        if achado is None:
            return None
        tipo, periodo = achado
        ferramentas = tuple(self._ferramentas[-periodo:])
        if tipo is TipoDeLaco.SEM_NOVIDADE:
            ferramentas = tuple(dict.fromkeys(ferramentas))
        acao = AcaoDoLaco.PARADA if self.avisou else AcaoDoLaco.AVISO
        self.avisou = True
        return Laco(tipo, periodo, ferramentas, acao)

    def _achar(self) -> tuple[TipoDeLaco, int] | None:
        marcas = self._marcas
        seguidas = self.identicas_seguidas
        if len(marcas) >= seguidas and len(set(marcas[-seguidas:])) == 1:
            return TipoDeLaco.IDENTICA, 1
        for periodo in PERIODOS:
            cauda = marcas[-2 * periodo :]
            # A A A A também repete com período 2, mas já é a idêntica.
            repete = len(cauda) == 2 * periodo and cauda[:periodo] == cauda[periodo:]
            if repete and len(set(cauda[:periodo])) > 1:
                return TipoDeLaco.CICLO, periodo
        if self._sem_novidade >= self.passos_sem_novidade:
            return TipoDeLaco.SEM_NOVIDADE, self._sem_novidade
        return None


def campos_na_trilha(laco: Laco, passo: int) -> Mapping[str, object]:
    """O evento `tarefa.laco`: códigos e números, nunca argumento nem resultado."""
    return {
        "tool_id": laco.ferramentas[-1],
        "categoria": str(laco.tipo),
        "decisao": str(laco.acao),
        "periodo": laco.periodo,
        "passo": passo,
    }


__all__ = [
    "IDENTICAS_SEGUIDAS",
    "PASSOS_SEM_NOVIDADE",
    "PERIODOS",
    "AcaoDoLaco",
    "GuardaDeLaco",
    "Laco",
    "TipoDeLaco",
    "campos_na_trilha",
    "marca_do_passo",
]
