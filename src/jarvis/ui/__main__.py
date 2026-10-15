"""Stub determinístico da `ui` (cartão F0-03): anota o que exigiria o dono na tela.

Confirmação de risco alto **não** é automática e nem por voz (SPEC §2): aqui o esqueleto só
registra o pedido; quem confirma é o dono, na fase que tiver tela.
"""

from __future__ import annotations

import json
import sys

from jarvis.barramento.envelope import Envelope, Tipo
from jarvis.processo import Processo, rodar_processo


def reagir(processo: Processo, envelope: Envelope, _veredito: str) -> list[Envelope]:
    if envelope.type is Tipo.POLICY_DECISION and str(envelope.payload["verdict"]) == "confirm":
        pedido = {
            "call_id": str(envelope.payload["call_id"]),
            "motivo": str(envelope.payload["reason"]),
            "epoch": envelope.epoch,
        }
        with (processo.raiz / "ui-confirmacoes.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(pedido, ensure_ascii=False) + "\n")
    return []


if __name__ == "__main__":
    sys.exit(rodar_processo("ui", reagir))
