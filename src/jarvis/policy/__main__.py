"""Stub determinístico do PDP (cartão F0-03). Decide por tabela, nunca pergunta ao modelo.

A política de verdade é o cartão F0-06; aqui só existe o que o esqueleto precisa provar: a
decisão é de código, vem antes do efeito e sai como evento auditável.
"""

from __future__ import annotations

import sys

from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust
from jarvis.processo import Processo, rodar_processo

PERMITIDAS_PARA_LEITURA = frozenset({"system.read.status"})


def reagir(processo: Processo, envelope: Envelope, _veredito: str) -> list[Envelope]:
    if envelope.type is not Tipo.TOOL_CALL_REQUESTED:
        return []
    tool_id = str(envelope.payload["tool_id"])
    dry_run = bool(envelope.payload["dry_run"])
    if tool_id in PERMITIDAS_PARA_LEITURA and dry_run:
        verdict, motivo = "allow", "leitura em dry_run dentro do catálogo do esqueleto"
    elif tool_id in PERMITIDAS_PARA_LEITURA:
        verdict, motivo = "confirm", "efeito exige confirmação do dono"
    else:
        verdict, motivo = "deny", f"{tool_id} não está no catálogo autorizado"
    return [
        Envelope(
            session_id=processo.session_id,
            epoch=envelope.epoch,
            source="policy",
            trust=Trust.SYSTEM,
            priority=Prioridade.P2,
            type=Tipo.POLICY_DECISION,
            payload={
                "call_id": str(envelope.payload["call_id"]),
                "verdict": verdict,
                "reason": motivo,
            },
        )
    ]


if __name__ == "__main__":
    sys.exit(rodar_processo("policy", reagir))
