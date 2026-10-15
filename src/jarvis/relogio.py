"""Relógio monotônico injetável: latência medida sem `sleep` e teste que não dá flake.

Por que existe (cartão F1-01): a F1 mede tempo em quase todo cartão. Se o caminho de áudio
chamar `time.monotonic_ns()` e `time.sleep()` direto, o teste passa a medir a máquina de CI
em vez do nosso código — e a asserção de latência fica frágil. Então todo lugar que olha o
tempo recebe um `Relogio`: em produção é o do sistema; em teste é o falso, que só anda
quando alguém manda andar.

A fonte de áudio também usa `dormir` para **ritmar** a entrega de quadros: com o relógio do
sistema ela entrega em tempo real; com o falso, instantaneamente e com o mesmo carimbo de
tempo virtual em toda execução.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

NS_POR_MS: Final = 1_000_000
NS_POR_S: Final = 1_000_000_000


@runtime_checkable
class Relogio(Protocol):
    """O tempo, como o resto do código o vê."""

    def mono_ns(self) -> int:
        """Relógio monotônico em nanossegundos."""
        ...

    def dormir(self, segundos: float) -> None:
        """Espera (de verdade, no sistema; virtualmente, no falso)."""
        ...


@dataclass(slots=True)
class RelogioDoSistema:
    """O relógio de produção. Monotônico, nunca volta atrás."""

    def mono_ns(self) -> int:
        return time.monotonic_ns()

    def dormir(self, segundos: float) -> None:
        if segundos > 0:
            time.sleep(segundos)


@dataclass(slots=True)
class RelogioFalso:
    """Tempo virtual: anda só por `avancar_*` ou `dormir`. Determinístico por construção."""

    agora_ns: int = 0
    dormidas_ns: list[int] = field(default_factory=list)

    def mono_ns(self) -> int:
        return self.agora_ns

    def dormir(self, segundos: float) -> None:
        ns = round(segundos * NS_POR_S)
        self.dormidas_ns.append(ns)
        self.avancar_ns(ns)

    def avancar_ns(self, ns: int) -> int:
        if ns < 0:
            raise ValueError("relógio monotônico não volta atrás")
        self.agora_ns += ns
        return self.agora_ns

    def avancar_ms(self, ms: float) -> int:
        return self.avancar_ns(round(ms * NS_POR_MS))
