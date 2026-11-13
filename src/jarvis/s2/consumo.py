"""Quanto cada chamada ao motor custou: tokens, custo estimado e tempo até o 1º token (ADR-0061).

O dono escolhe o preset (ADR-0056) e até aqui não via quanto cada turno custava. Os números já
chegavam — o `usage` que o provedor manda no fim do stream (`Fim.uso`) e o preço por milhão de
tokens do catálogo (`Capacidades.preco_entrada/preco_saida`) — e se perdiam no cérebro.

`medir` envolve o gerador de deltas de um motor sem mudar nada do que passa por ele: anota quando
chegou o primeiro delta (de qualquer tipo — texto, raciocínio ou proposta de ferramenta), conta os
caracteres que saíram e, no `Fim`, lê o `usage`. Quando o gerador acaba (pelo `Fim`, pelo
cancelamento ou pelo `close()` do cérebro), entrega uma `Medicao` a quem pediu.

Regras:

1. **Só números.** Nada do contexto, do texto do dono nem da resposta: a trilha recebe contagens.
   O orçamento do prompt não muda — nada disto vai ao modelo.
2. **Reportado vence estimado.** Sem o `usage` (o motor que não informa, a chamada cortada), a
   contagem é `caracteres / CARACTERES_POR_TOKEN`, e a medição sai marcada `estimado=True`.
3. **Custo só com preço conhecido.** Custo = tokens × preço por milhão (o que, em micro-dólares,
   é a própria multiplicação). Sem preço no catálogo, o custo é `None` ("sem preço"), não zero. O
   custo que o provedor reporta (`custo_microusd` no `uso`, a CLI do Claude) vence a conta.
"""

from __future__ import annotations

import contextlib
import math
import time
from collections.abc import Callable, Generator, Iterator, Mapping
from dataclasses import dataclass
from typing import Final

from jarvis.s2.motor import Delta, Fim, PedidoDeTool, Raciocinio, Texto

CARACTERES_POR_TOKEN: Final = 4
"""A estimativa de sempre quando o provedor não diz: ~4 caracteres por token."""

CHAVES_DE_ENTRADA: Final = (
    "entrada",
    "prompt_tokens",
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
"""Os nomes que os provedores dão aos tokens de entrada. `entrada` é o nosso (compatível, Codex);
os da CLI do Claude somam: o que veio do cache também é entrada cobrada (mais barata, mas o preço
por tipo de cache não está no catálogo — a conta fica do lado de cima, e o custo reportado pela
CLI vence)."""
CHAVES_DE_SAIDA: Final = ("saida", "completion_tokens", "output_tokens")
CHAVE_DO_CUSTO: Final = "custo_microusd"
"""Custo que o próprio provedor reportou, em micro-dólares (US$ × 10⁶)."""


@dataclass(frozen=True, slots=True)
class Medicao:
    """Uma chamada ao motor, em números."""

    tokens_entrada: int
    tokens_saida: int
    estimado: bool
    """Algum dos dois números veio da estimativa por caracteres."""
    custo_microusd: int | None
    """US$ × 10⁶. `None` = sem preço conhecido (não é zero)."""
    ms_primeiro_token: float | None
    """Do começo da chamada ao primeiro delta. `None` = nada chegou."""
    ms: float
    fim: str
    """Como a chamada acabou (`concluido`, `erro`, `prazo`, `cancelado`, `cortada`)."""


def _inteiro(valor: object) -> int | None:
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
        return None
    return valor


def tokens_do_uso(uso: Mapping[str, object]) -> tuple[int | None, int | None]:
    """Entrada e saída no `uso` de qualquer provedor; `None` = o provedor não disse."""
    entradas = [_inteiro(uso.get(chave)) for chave in CHAVES_DE_ENTRADA]
    saidas = [_inteiro(uso.get(chave)) for chave in CHAVES_DE_SAIDA]
    # O nosso nome e o do provedor podem vir juntos (não vêm hoje): o nosso vence, sem somar.
    entrada: int | None
    if entradas[0] is not None:
        entrada = entradas[0]
    else:
        conhecidas = [e for e in entradas[1:] if e is not None]
        entrada = sum(conhecidas) if conhecidas else None
    saida = next((s for s in saidas if s is not None), None)
    return entrada, saida


def estimar_tokens(caracteres: int) -> int:
    return math.ceil(max(0, caracteres) / CARACTERES_POR_TOKEN)


def custo_microusd(
    tokens_entrada: int,
    tokens_saida: int,
    preco_entrada: float | None,
    preco_saida: float | None,
) -> int | None:
    """Tokens × US$ por milhão = micro-dólares. Sem um dos preços, `None`."""
    if preco_entrada is None or preco_saida is None:
        return None
    return round(tokens_entrada * preco_entrada + tokens_saida * preco_saida)


def medicao_da_chamada(
    uso: Mapping[str, object],
    *,
    caracteres_entrada: Callable[[], int],
    caracteres_saida: int,
    precos: tuple[float | None, float | None],
    ms_primeiro_token: float | None,
    ms: float,
    fim: str,
) -> Medicao:
    """A medição de uma chamada. `caracteres_entrada` só é chamado sem o `usage` (montar o
    texto do contexto custa)."""
    entrada, saida = tokens_do_uso(uso)
    estimado = entrada is None or saida is None
    if entrada is None:
        entrada = estimar_tokens(caracteres_entrada())
    if saida is None:
        saida = estimar_tokens(caracteres_saida)
    reportado = _inteiro(uso.get(CHAVE_DO_CUSTO))
    custo = reportado if reportado is not None else custo_microusd(entrada, saida, *precos)
    return Medicao(
        tokens_entrada=entrada,
        tokens_saida=saida,
        estimado=estimado,
        custo_microusd=custo,
        ms_primeiro_token=ms_primeiro_token,
        ms=ms,
        fim=fim,
    )


def precos_do_motor(motor: object) -> tuple[float | None, float | None]:
    """O preço por milhão (entrada, saída) que o motor declara em `precos`; senão, desconhecido.
    Quem declara é o motor dos presets (o preço vem do catálogo do provedor)."""
    precos = getattr(motor, "precos", None)
    if not isinstance(precos, tuple) or len(precos) != 2:
        return None, None
    entrada, saida = precos

    def numero(valor: object) -> float | None:
        if isinstance(valor, bool) or not isinstance(valor, int | float) or valor < 0:
            return None
        return float(valor)

    return numero(entrada), numero(saida)


def _caracteres(delta: Delta) -> int:
    if isinstance(delta, Texto | Raciocinio):
        return len(delta.texto)
    if isinstance(delta, PedidoDeTool):
        return len(delta.tool_id) + sum(len(str(v)) for v in delta.args.values())
    return 0


def medir(
    deltas: Iterator[Delta],
    *,
    caracteres_entrada: Callable[[], int],
    precos: Callable[[], tuple[float | None, float | None]],
    ao_medir: Callable[[Medicao], None],
    relogio: Callable[[], float] = time.monotonic,
) -> Generator[Delta, None, None]:
    """Os mesmos deltas, na mesma ordem; quando o gerador acaba, `ao_medir(Medicao)` uma vez.

    O `close()` de quem consome chega ao motor (o `finally` daqui fecha o de dentro), então
    cancelar continua parando a geração como antes. `precos` é lido no fim (o motor dos presets
    só sabe o preset depois de gerar). Falha em `ao_medir` não derruba o turno: a medição é
    ajuda, não requisito."""
    comeco = relogio()
    primeiro: float | None = None
    saida = 0
    uso: Mapping[str, object] = {}
    fim = "cortada"
    try:
        for delta in deltas:
            if primeiro is None:
                primeiro = (relogio() - comeco) * 1000.0
            if isinstance(delta, Fim):
                uso, fim = delta.uso, str(delta.motivo)
            else:
                saida += _caracteres(delta)
            yield delta
    finally:
        fechar = getattr(deltas, "close", None)
        if callable(fechar):
            fechar()
        # A medição nunca derruba o turno: falha ao anotar é engolida aqui.
        with contextlib.suppress(Exception):
            ao_medir(
                medicao_da_chamada(
                    uso,
                    caracteres_entrada=caracteres_entrada,
                    caracteres_saida=saida,
                    precos=precos(),
                    ms_primeiro_token=primeiro,
                    ms=(relogio() - comeco) * 1000.0,
                    fim=fim,
                )
            )


@dataclass(slots=True)
class ConsumoDoTurno:
    """A soma das chamadas de um turno, para o `turno.fim`."""

    chamadas: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    estimado: bool = False
    custo_microusd: int | None = 0
    """`None` quando alguma chamada não tinha preço: a soma seria menor que o real."""

    def somar(self, medicao: Medicao) -> None:
        self.chamadas += 1
        self.tokens_entrada += medicao.tokens_entrada
        self.tokens_saida += medicao.tokens_saida
        self.estimado = self.estimado or medicao.estimado
        if self.custo_microusd is None or medicao.custo_microusd is None:
            self.custo_microusd = None
        else:
            self.custo_microusd += medicao.custo_microusd

    def campos(self) -> dict[str, object]:
        """Os campos do `turno.fim` (a allowlist da trilha os conhece)."""
        if not self.chamadas:
            return {"chamadas_ao_motor": 0}
        return {
            "chamadas_ao_motor": self.chamadas,
            "tokens_entrada": self.tokens_entrada,
            "tokens_saida": self.tokens_saida,
            "tokens_estimados": self.estimado,
            "custo_microusd": self.custo_microusd,
        }


def campos_da_medicao(medicao: Medicao) -> dict[str, object]:
    """Os campos do evento `motor.chamada`."""
    return {
        "tokens_entrada": medicao.tokens_entrada,
        "tokens_saida": medicao.tokens_saida,
        "tokens_estimados": medicao.estimado,
        "custo_microusd": medicao.custo_microusd,
        "ms_primeiro_token": medicao.ms_primeiro_token,
        "ms": medicao.ms,
        "fim": medicao.fim,
    }


__all__ = [
    "CARACTERES_POR_TOKEN",
    "ConsumoDoTurno",
    "Medicao",
    "campos_da_medicao",
    "custo_microusd",
    "estimar_tokens",
    "medicao_da_chamada",
    "medir",
    "precos_do_motor",
    "tokens_do_uso",
]
