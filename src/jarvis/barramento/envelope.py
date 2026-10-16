"""Envelope comum e vocabulário fechado do barramento (SPEC §3.1 e §3.2).

Os valores aqui são os mesmos de `schemas/events.v1.json`, que é a fonte de verdade
entre linguagens; `tests/unit/barramento/test_contrato.py` falha se divergirem.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self

SCHEMA_VERSION = "1"


class Prioridade(StrEnum):
    """P0–P4: decide qual computação preempta qual, nunca qual comando executa (§3.2)."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class Trust(StrEnum):
    """Atribuído por quem recebe do mundo, nunca declarado pelo emissor remoto (§3.1, P6)."""

    SYSTEM = "system"
    USER_VOICE = "user_voice"
    USER_UI = "user_ui"
    TOOL_RESULT = "tool_result"
    THIRD_PARTY = "third_party"


class Tipo(StrEnum):
    """Os doze tipos fechados da §3.2 (o 12º pela ADR-0025). Tipo fora desta lista é recusado."""

    AUDIO_ACTIVITY = "AudioActivity"
    PARTIAL_TRANSCRIPT = "PartialTranscript"
    FINAL_TRANSCRIPT = "FinalTranscript"
    TURN_PREDICTION = "TurnPrediction"
    DESKTOP_OBSERVATION = "DesktopObservation"
    TOOL_CALL_REQUESTED = "ToolCallRequested"
    POLICY_DECISION = "PolicyDecision"
    TOOL_RESULT = "ToolResult"
    PLAYBACK_PROGRESS = "PlaybackProgress"
    STATE_REVISION = "StateRevision"
    CANCEL = "Cancel"
    RESPONSE_CHUNK = "ResponseChunk"


class Fonte(StrEnum):
    """Processos da §2. Servidor MCP usa `mcp:<id>`, validado por `FONTE_VALIDA`."""

    AUDIO_IO = "audio-io"
    AGENTD = "agentd"
    S2 = "s2"
    POLICY = "policy"
    EXECUTOR = "executor"
    MEMORYD = "memoryd"
    UI = "ui"


FONTE_VALIDA = re.compile(
    r"^(audio-io|agentd|s2|policy|executor|memoryd|ui|mcp:[a-z0-9][a-z0-9_.-]{0,63})$"
)
UUID_V7_VALIDO = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def uuid7() -> str:
    """UUID v7 (RFC 9562): 48 bits de milissegundos Unix + aleatório, ordenável por tempo.

    A stdlib só ganhou `uuid.uuid7()` depois do 3.12 (a versão do projeto até a decisão D1),
    então o gerador é nosso. Monotonicidade dentro do mesmo milissegundo não é exigida pela
    §3.1 — a ordem forte do log vem de `seq` (ver `log.py`).
    """
    ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    aleatorio = int.from_bytes(os.urandom(10), "big")
    rand_a = (aleatorio >> 62) & 0xFFF
    rand_b = aleatorio & 0x3FFFFFFFFFFFFFFF
    bits = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    h = f"{bits:032x}"
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def agora_wall() -> str:
    """Relógio de parede em UTC, com `Z` — o `ts_wall` da §3.1."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def agora_mono_ns() -> int:
    """Relógio monotônico da máquina de origem — o `ts_mono_ns` da §3.1."""
    return time.monotonic_ns()


@dataclass(frozen=True, slots=True)
class Envelope:
    """Um evento do barramento. Imutável: reclassificar trust produz outro envelope."""

    session_id: str
    epoch: int
    source: str
    trust: Trust
    priority: Prioridade
    type: Tipo
    payload: dict[str, Any]
    event_id: str = field(default_factory=uuid7)
    ts_mono_ns: int = field(default_factory=agora_mono_ns)
    ts_wall: str = field(default_factory=agora_wall)
    schema_version: str = SCHEMA_VERSION

    def para_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "epoch": self.epoch,
            "ts_mono_ns": self.ts_mono_ns,
            "ts_wall": self.ts_wall,
            "source": self.source,
            "trust": str(self.trust),
            "priority": str(self.priority),
            "type": str(self.type),
            "payload": self.payload,
        }

    @classmethod
    def de_dict(cls, bruto: dict[str, Any]) -> Self:
        """Constrói a partir de um dicionário **já validado** pela borda (`contrato.py`)."""
        return cls(
            session_id=str(bruto["session_id"]),
            epoch=int(bruto["epoch"]),
            source=str(bruto["source"]),
            trust=Trust(bruto["trust"]),
            priority=Prioridade(bruto["priority"]),
            type=Tipo(bruto["type"]),
            payload=dict(bruto["payload"]),
            event_id=str(bruto["event_id"]),
            ts_mono_ns=int(bruto["ts_mono_ns"]),
            ts_wall=str(bruto["ts_wall"]),
            schema_version=str(bruto["schema_version"]),
        )

    def com_trust(self, trust: Trust) -> Envelope:
        """Mesmo evento com outro rótulo de confiança (usado pela fronteira de entrada)."""
        bruto = self.para_dict()
        bruto["trust"] = str(trust)
        return Envelope.de_dict(bruto)
