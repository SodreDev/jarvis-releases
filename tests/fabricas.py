"""Fábricas de evento válido para os testes do barramento (SPEC §3.2)."""

from __future__ import annotations

from typing import Any

from jarvis.barramento import Envelope, Tipo, Trust, prioridade_canonica

PAYLOADS: dict[Tipo, dict[str, Any]] = {
    Tipo.AUDIO_ACTIVITY: {
        "speech": False,
        "device_id": "alsa:0",
        "energy_db": -42.5,
        "aec_ok": True,
    },
    Tipo.PARTIAL_TRANSCRIPT: {
        "text": "liga o",
        "stability": 0.4,
        "t_start_ms": 0,
        "t_end_ms": 320,
        "lang": "pt-BR",
    },
    Tipo.FINAL_TRANSCRIPT: {
        "text": "liga o rádio",
        "confidence": 0.93,
        "t_start_ms": 0,
        "t_end_ms": 900,
    },
    Tipo.TURN_PREDICTION: {"p_eot": 0.82, "detector": "semantico-v0", "decision": "yield"},
    Tipo.DESKTOP_OBSERVATION: {"kind": "janela_ativa", "app_id": "org.kde.dolphin", "payload": {}},
    Tipo.TOOL_CALL_REQUESTED: {
        "call_id": "c-1",
        "tool_id": "files.move_to_trash",
        "args": {"path": "nota.txt"},
        "dry_run": True,
    },
    Tipo.POLICY_DECISION: {"call_id": "c-1", "verdict": "allow", "reason": "dentro da raiz"},
    Tipo.TOOL_RESULT: {
        "call_id": "c-1",
        "status": "ok",
        "payload_ref": "blob:1",
        "postcondition": "verified",
        "read_only": True,
    },
    Tipo.PLAYBACK_PROGRESS: {"chunk_id": "k-1", "played_ms": 240, "epoch": 0},
    Tipo.STATE_REVISION: {
        "task_id": "t-1",
        "epoch": 0,
        "objetivo": "responder",
        "evidencia": [],
        "incertezas": [],
        "tarefas": [{"id": "t-1", "estado": "Planned"}],
        "fala_ouvida": "",
        "audio_tocado_ms": 0,
        "cenario": {"nome": "trabalho", "p": 0.8, "ttl_s": 300},
    },
    Tipo.CANCEL: {"epoch_invalidado": 0, "reason": "barge_in"},
    Tipo.RESPONSE_CHUNK: {
        "response_id": "r-1",
        "turn_id": "t-1",
        "epoch": 0,
        "seq": 0,
        "text": "Depois de quinta",
        "boundary": "limite",
        "last": False,
    },
    Tipo.NOTIFICATION: {
        "notif_id": "n-1",
        "origem": "tarefa · pesquisa",
        "tipo": "concluida",
        "resumo": "a pesquisa terminou",
    },
    Tipo.NOTIFICATION_RELEASE: {"notif_ids": ["n-1"], "motivo": "piso_livre"},
}

FONTE_PADRAO: dict[Tipo, str] = {
    Tipo.AUDIO_ACTIVITY: "audio-io",
    Tipo.PARTIAL_TRANSCRIPT: "agentd",
    Tipo.FINAL_TRANSCRIPT: "agentd",
    Tipo.TURN_PREDICTION: "agentd",
    Tipo.DESKTOP_OBSERVATION: "executor",
    Tipo.TOOL_CALL_REQUESTED: "s2",
    Tipo.POLICY_DECISION: "policy",
    Tipo.TOOL_RESULT: "executor",
    Tipo.PLAYBACK_PROGRESS: "audio-io",
    Tipo.STATE_REVISION: "s2",
    Tipo.CANCEL: "agentd",
    Tipo.RESPONSE_CHUNK: "s2",
    Tipo.NOTIFICATION: "executor",
    Tipo.NOTIFICATION_RELEASE: "agentd",
}

TRUST_PADRAO: dict[Tipo, Trust] = {
    Tipo.DESKTOP_OBSERVATION: Trust.THIRD_PARTY,
    Tipo.FINAL_TRANSCRIPT: Trust.USER_VOICE,
    Tipo.PARTIAL_TRANSCRIPT: Trust.USER_VOICE,
    Tipo.TOOL_RESULT: Trust.TOOL_RESULT,
}


def evento(
    tipo: Tipo,
    session_id: str,
    *,
    epoch: int = 0,
    source: str | None = None,
    trust: Trust | None = None,
    **mudancas: Any,
) -> Envelope:
    """Envelope válido do tipo pedido, com o payload canônico e as mudanças aplicadas."""
    payload = {**PAYLOADS[tipo], **mudancas}
    com_epoch = (Tipo.PLAYBACK_PROGRESS, Tipo.STATE_REVISION, Tipo.RESPONSE_CHUNK)
    if tipo in com_epoch and "epoch" not in mudancas:
        payload["epoch"] = epoch
    return Envelope(
        session_id=session_id,
        epoch=epoch,
        source=source if source is not None else FONTE_PADRAO[tipo],
        trust=trust if trust is not None else TRUST_PADRAO.get(tipo, Trust.SYSTEM),
        priority=prioridade_canonica(tipo, payload),
        type=tipo,
        payload=payload,
    )
