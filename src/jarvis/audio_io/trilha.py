"""Trilha de eventos: o que a cascata decidiu, em JSONL comparável (cartão F1-01).

A trilha guarda só o que é determinístico e essencial — `type`, `epoch`, `ts_mono_ns` (do
relógio injetado) e as chaves do payload que descrevem a decisão. Fica de fora o que muda
a cada execução sem significar nada: `event_id` (uuid v7) e `ts_wall`.

É com isto que o aceite (d) do cartão funciona: duas trilhas, e a primeira divergência
aparece com índice, chave e os dois valores — em vez de "deu diferente".
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Self

from jarvis.barramento.envelope import Envelope

CHAVES_ESSENCIAIS: Final[dict[str, tuple[str, ...]]] = {
    "AudioActivity": ("speech", "device_id", "energy_db", "aec_ok"),
    "PlaybackProgress": ("chunk_id", "played_ms", "epoch"),
    "Cancel": ("epoch_invalidado", "reason"),
    "PartialTranscript": ("text", "stability", "t_start_ms", "t_end_ms"),
    "FinalTranscript": ("text", "t_start_ms", "t_end_ms"),
    "TurnPrediction": ("p_eot", "detector", "decision"),
}
CASAS_DECIMAIS: Final = 3
"""Arredondar o que é float na trilha evita diferença de formatação virar divergência."""


@dataclass(frozen=True, slots=True)
class EventoDeTrilha:
    """Uma linha da trilha."""

    type: str
    epoch: int
    ts_mono_ns: int
    payload: dict[str, Any]

    @classmethod
    def de_envelope(cls, envelope: Envelope) -> Self:
        chaves = CHAVES_ESSENCIAIS.get(str(envelope.type), tuple(sorted(envelope.payload)))
        payload = {
            chave: (round(valor, CASAS_DECIMAIS) if isinstance(valor, float) else valor)
            for chave, valor in ((c, envelope.payload[c]) for c in chaves if c in envelope.payload)
        }
        return cls(
            type=str(envelope.type),
            epoch=envelope.epoch,
            ts_mono_ns=envelope.ts_mono_ns,
            payload=payload,
        )

    def para_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "epoch": self.epoch,
            "ts_mono_ns": self.ts_mono_ns,
            "payload": self.payload,
        }

    @classmethod
    def de_dict(cls, bruto: dict[str, Any]) -> Self:
        return cls(
            type=str(bruto["type"]),
            epoch=int(bruto["epoch"]),
            ts_mono_ns=int(bruto["ts_mono_ns"]),
            payload=dict(bruto["payload"]),
        )


@dataclass(frozen=True, slots=True)
class Divergencia:
    """A primeira diferença entre duas trilhas, com o suficiente para agir."""

    indice: int
    o_que: str
    esperado: Any = None
    obtido: Any = None

    def __str__(self) -> str:
        if self.esperado is None and self.obtido is None:
            return f"evento {self.indice}: {self.o_que}"
        return (
            f"evento {self.indice}: {self.o_que} (esperado {self.esperado!r}, veio {self.obtido!r})"
        )


def escrever(caminho: Path, eventos: Sequence[EventoDeTrilha]) -> None:
    linhas = [
        json.dumps(evento.para_dict(), ensure_ascii=False, sort_keys=True) for evento in eventos
    ]
    caminho.write_text("\n".join(linhas) + ("\n" if linhas else ""), encoding="utf-8")


def ler(caminho: Path) -> list[EventoDeTrilha]:
    texto = caminho.read_text(encoding="utf-8")
    return [
        EventoDeTrilha.de_dict(json.loads(linha)) for linha in texto.splitlines() if linha.strip()
    ]


def comparar(a: Sequence[EventoDeTrilha], b: Sequence[EventoDeTrilha]) -> Divergencia | None:
    """Primeira divergência entre duas trilhas, ou `None` se são iguais."""
    for i, (esquerda, direita) in enumerate(zip(a, b, strict=False)):
        if esquerda.type != direita.type:
            return Divergencia(i, "tipo diferente", esquerda.type, direita.type)
        if esquerda.epoch != direita.epoch:
            return Divergencia(i, "epoch diferente", esquerda.epoch, direita.epoch)
        if esquerda.ts_mono_ns != direita.ts_mono_ns:
            return Divergencia(i, "ts_mono_ns diferente", esquerda.ts_mono_ns, direita.ts_mono_ns)
        for chave in sorted(set(esquerda.payload) | set(direita.payload)):
            if esquerda.payload.get(chave) != direita.payload.get(chave):
                return Divergencia(
                    i,
                    f"payload.{chave} diferente",
                    esquerda.payload.get(chave),
                    direita.payload.get(chave),
                )
    if len(a) != len(b):
        return Divergencia(min(len(a), len(b)), "trilhas de tamanhos diferentes", len(a), len(b))
    return None
