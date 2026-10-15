"""Detector de energia — o que decide "tem som" até o VAD chegar (cartão F1-01).

**Isto não é o VAD.** O VAD do projeto é o `silero-vad` (MIT, já verificado na porta de
licença), com histerese e janela de 512 amostras, e é o cartão F1-05. O que existe aqui é
um limiar de energia, para que a cascata do F1-01 tenha uma decisão a registrar na trilha
e para que o F1-04 possa provar o problema que a AEC resolve sem depender de um cartão
futuro. Todo relatório que usar este detector tem de dizer o nome dele.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from jarvis.audio_io.quadro import Quadro

LIMIAR_PADRAO_DB: Final = -45.0
"""Entre o silêncio digital (piso) e a fala simulada (~-20 dBFS). Declarado, não calibrado."""


@dataclass(slots=True)
class DetectorDeEnergia:
    """Diz quando o estado muda. `None` no primeiro quadro significa "ainda não sei".

    Cumpre o protocolo `Vad` do cartão F1-05 (tem `nome`, `falando`, `ver` e
    `ultima_probabilidade`), mas **sem histerese**: é o limiar cru do F1-01, que a trilha de
    replay usa justamente porque não suaviza nada. O VAD de energia com histerese é
    `jarvis.audio_io.vad.VadDeEnergia`, e o do produto é o `silero-vad`.
    """

    limiar_db: float = LIMIAR_PADRAO_DB
    falando: bool | None = None
    nome: str = "limiar-de-energia@1"
    ultima_probabilidade: float = 0.0

    def ver(self, quadro: Quadro) -> bool | None:
        """Devolve o novo estado quando ele muda; `None` quando nada mudou."""
        agora = quadro.energia_db >= self.limiar_db
        self.ultima_probabilidade = 1.0 if agora else 0.0
        if agora == self.falando:
            return None
        self.falando = agora
        return agora
