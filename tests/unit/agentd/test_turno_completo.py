"""O turno sintético do F1-11: cada turno tem o seu `call_id`, mesmo no mesmo milissegundo."""

from __future__ import annotations

import time

import pytest

import jarvis.barramento.envelope as envelope
from jarvis.agentd.turno_completo import TurnoCompleto
from jarvis.barramento.envelope import Envelope, Tipo

MILISSEGUNDO_PARADO = 1_760_000_000.123
"""Qualquer instante serve: o que importa é ser o mesmo para os dois turnos."""


class RelogioParado:
    """O `time` que o gerador de uuid7 enxerga, com o relógio de parede congelado.

    Só o relógio de parede para: é dele que saem os 48 bits de milissegundo do uuid7. O
    monotônico continua o de verdade, porque é dele que o `ts_mono_ns` dos eventos depende.
    """

    @staticmethod
    def time() -> float:
        return MILISSEGUNDO_PARADO

    @staticmethod
    def monotonic_ns() -> int:
        return time.monotonic_ns()


def pedido(eventos: tuple[Envelope, ...]) -> Envelope:
    (unico,) = (e for e in eventos if e.type is Tipo.TOOL_CALL_REQUESTED)
    return unico


def test_dois_turnos_no_mesmo_milissegundo_tem_call_id_distinto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O `call_id` era `c-{uuid7()[:8]}`: o começo de um uuid7 é o relógio, e dois turnos da
    mesma janela de 65,5 s dividiam o id. Com o relógio parado, a janela deixa de depender da
    hora do teste — e o id só pode diferir pela parte aleatória."""
    monkeypatch.setattr(envelope, "time", RelogioParado)
    turno = TurnoCompleto()

    primeiro = pedido(turno.rodar().eventos)
    segundo = pedido(turno.rodar().eventos)

    assert primeiro.event_id[:13] == segundo.event_id[:13], "o mesmo milissegundo está forçado"
    assert primeiro.payload["call_id"] != segundo.payload["call_id"]
