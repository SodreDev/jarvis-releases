"""Stub determinístico do `executor` (cartão F0-03).

Duas propriedades deste arquivo são testadas por varredura de código, não por intenção:

* **não existe caminho para shell** — nada de `subprocess`, `os.system`, `eval` ou `exec`
  dentro de `jarvis.executor` (aceite F0-03 d);
* **efeito não duplica** — cada `call_id` é executado uma vez, com o registro persistido em
  disco, para que reiniciar o processo não repita o efeito (aceite F0-03 b).
"""

from __future__ import annotations

import sys
from pathlib import Path

from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust
from jarvis.processo import Processo, rodar_processo

TOOLS_DE_LEITURA = frozenset({"system.read.status"})


def arquivo_de_efeitos(raiz: Path) -> Path:
    return raiz / "executor-efeitos.jsonl"


def ja_executou(raiz: Path, call_id: str) -> bool:
    arquivo = arquivo_de_efeitos(raiz)
    if not arquivo.exists():
        return False
    return any(linha.strip() == call_id for linha in arquivo.read_text(encoding="utf-8").split())


def marcar_executado(raiz: Path, call_id: str) -> None:
    with arquivo_de_efeitos(raiz).open("a", encoding="utf-8") as f:
        f.write(f"{call_id}\n")


def reagir(processo: Processo, envelope: Envelope, _veredito: str) -> list[Envelope]:
    if envelope.type is not Tipo.POLICY_DECISION:
        return []
    if str(envelope.payload["verdict"]) != "allow":
        return []
    call_id = str(envelope.payload["call_id"])
    if ja_executou(processo.raiz, call_id):
        return []  # idempotência: o mesmo call_id nunca roda duas vezes
    marcar_executado(processo.raiz, call_id)
    return [
        Envelope(
            session_id=processo.session_id,
            epoch=envelope.epoch,
            source="executor",
            trust=Trust.TOOL_RESULT,
            priority=Prioridade.P2,
            type=Tipo.TOOL_RESULT,
            payload={
                "call_id": call_id,
                "status": "ok",
                "payload_ref": f"inline:{call_id}",
                "postcondition": "verified",
                "read_only": True,
            },
        )
    ]


if __name__ == "__main__":
    sys.exit(rodar_processo("executor", reagir))
