"""Stub determinístico do `s2`: estado de trabalho e pedido de tool, sem LLM (cartão F0-03).

O que este esqueleto prova: o reasoner reage a evento (nunca a laço cego), pede capacidade
pelo `tool_id` do catálogo e **não publica fala de epoch morto**.
"""

from __future__ import annotations

import sys

from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust, uuid7
from jarvis.processo import Processo, rodar_processo

TOOL_DO_ESQUELETO = "system.read.status"


def reagir(processo: Processo, envelope: Envelope, veredito: str) -> list[Envelope]:
    if envelope.epoch < processo.epoch:
        # §3.3 regra 6 e aceite (c): nada de epoch morto sai daqui, nem como fala.
        return []
    if envelope.type is Tipo.CANCEL:
        processo.epoch = envelope.epoch
        return []
    if envelope.type is Tipo.PARTIAL_TRANSCRIPT:
        # Cartão F1-06, §3.4: o parcial é **hipótese**. Dez parciais em 200 ms não viram dez
        # raciocínios: o barramento coalesce (PartialTranscript está em TIPOS_COALESCIVEIS) e o
        # que chega aqui é a hipótese mais nova — uma revisão de estado, não dez.
        return [_revisao_de_hipotese(processo, envelope)]
    if envelope.type is Tipo.FINAL_TRANSCRIPT:
        return [_pedido_de_tool(processo, envelope)]
    if envelope.type is Tipo.TOOL_RESULT and veredito != "aceitar_stale":
        return [_revisao_de_estado(processo, envelope)]
    return []


def _revisao_de_hipotese(processo: Processo, origem: Envelope) -> Envelope:
    """Revisão de estado a partir de um parcial: o que o dono parece estar pedindo, por ora."""
    return Envelope(
        session_id=processo.session_id,
        epoch=origem.epoch,
        source="s2",
        trust=Trust.SYSTEM,
        priority=Prioridade.P2,
        type=Tipo.STATE_REVISION,
        payload={
            "task_id": f"hipotese-{origem.epoch}",
            "epoch": origem.epoch,
            "objetivo": "entender o pedido em curso",
            "evidencia": [],
            "incertezas": ["transcrição parcial, pode mudar"],
            "tarefas": [{"id": f"hipotese-{origem.epoch}", "estado": "Draft"}],
            "fala_ouvida": str(origem.payload["text"]),
            "audio_tocado_ms": 0,
            "cenario": {"nome": "trabalho", "p": 0.5, "ttl_s": 300},
        },
    )


def _pedido_de_tool(processo: Processo, origem: Envelope) -> Envelope:
    return Envelope(
        session_id=processo.session_id,
        epoch=origem.epoch,
        source="s2",
        trust=Trust.SYSTEM,
        priority=Prioridade.P2,
        type=Tipo.TOOL_CALL_REQUESTED,
        payload={
            "call_id": f"c-{uuid7()[:8]}",
            "tool_id": TOOL_DO_ESQUELETO,
            "args": {"sobre": origem.payload["text"]},
            "dry_run": True,
        },
    )


def _revisao_de_estado(processo: Processo, origem: Envelope) -> Envelope:
    return Envelope(
        session_id=processo.session_id,
        epoch=origem.epoch,
        source="s2",
        trust=Trust.SYSTEM,
        priority=Prioridade.P2,
        type=Tipo.STATE_REVISION,
        payload={
            "task_id": str(origem.payload["call_id"]),
            "epoch": origem.epoch,
            "objetivo": "responder ao pedido do dono",
            "evidencia": [
                {"ref": str(origem.payload["call_id"]), "resumo": str(origem.payload["status"])}
            ],
            "incertezas": [],
            "tarefas": [{"id": str(origem.payload["call_id"]), "estado": "Succeeded"}],
            "fala_ouvida": "",
            "audio_tocado_ms": 0,
            "cenario": {"nome": "esqueleto", "p": 1.0, "ttl_s": 60},
        },
    )


if __name__ == "__main__":
    sys.exit(rodar_processo("s2", reagir))
