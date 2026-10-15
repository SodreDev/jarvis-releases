"""Stub determinístico do `memoryd` (cartão F0-03): anota episódio, fora do caminho da voz.

O ledger de verdade é a §6.2 (cartão F0-05). Aqui o esqueleto só prova a fronteira: o
`memoryd` recebe do barramento, grava no **seu** arquivo e nunca responde no caminho crítico.
"""

from __future__ import annotations

import json
import sys

from jarvis.barramento.envelope import Envelope
from jarvis.processo import Processo, rodar_processo


def reagir(processo: Processo, envelope: Envelope, veredito: str) -> list[Envelope]:
    linha = {
        "event_id": envelope.event_id,
        "type": str(envelope.type),
        "epoch": envelope.epoch,
        "trust": str(envelope.trust),
        "veredito": veredito,
    }
    with (processo.raiz / "memoryd-episodios.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    return []  # memória não publica no caminho da voz


if __name__ == "__main__":
    sys.exit(rodar_processo("memoryd", reagir))
