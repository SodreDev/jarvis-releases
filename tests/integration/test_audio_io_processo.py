"""Cartão F1-03: o processo `audio-io` de verdade captura, toca e esvazia no `Cancel`.

Barge-in ponta a ponta com processos (não com as peças em memória): `audio-io` captura o
roteiro sintético, o `agentd` vê `speech_started` e emite `Cancel` (regra 1 da §3.3), e o
`audio-io` esvazia a fila de playback publicando o `PlaybackProgress` com o `played_ms` que
realmente saiu.

Como no F0-03: tudo em pasta temporária e nenhum processo procurado por nome — o supervisor
encerra só os PIDs que ele mesmo criou.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.barramento import LogDeEventos, Tipo
from jarvis.supervisao import Supervisor

LIMITE = 30.0


@pytest.fixture
def supervisor(tmp_path: Path) -> Iterator[Supervisor]:
    supervisor = Supervisor(raiz=tmp_path / "exec")
    yield supervisor
    supervisor.parar_tudo()


def esperar(raiz: Path, tipo: Tipo, *, limite: float = LIMITE) -> list[Tipo]:
    fim = time.monotonic() + limite
    vistos: list[Tipo] = []
    arquivo = raiz / "eventos.sqlite"
    while time.monotonic() < fim:
        if arquivo.exists():
            with LogDeEventos(arquivo) as log:
                vistos = [r.envelope.type for r in log.ler()]
            if tipo in vistos:
                return vistos
        time.sleep(0.05)
    raise AssertionError(f"{tipo} não apareceu em {limite}s; log tem {vistos}")


def test_captura_de_verdade_publica_audio_activity_no_barramento(
    supervisor: Supervisor,
) -> None:
    """A captura do processo é a do F1-01: fonte sintética, quadros de 20 ms, sem dispositivo."""
    supervisor.iniciar("agentd", "--parar-em", "Cancel", "--timeout", str(LIMITE))
    supervisor.esperar_barramento()
    supervisor.iniciar("audio-io", "--capturar", "--timeout", "5")

    vistos = esperar(supervisor.raiz, Tipo.AUDIO_ACTIVITY)

    assert vistos[0] is Tipo.AUDIO_ACTIVITY
    with LogDeEventos(supervisor.raiz / "eventos.sqlite") as log:
        primeiro = next(iter(log.ler())).envelope
    assert primeiro.source == "audio-io"
    assert primeiro.payload["device_id"].startswith("sintetico:")
    assert primeiro.trust == "user_voice"


def test_cancel_do_agentd_esvazia_a_fila_e_publica_played_ms_real(
    supervisor: Supervisor,
) -> None:
    """§3.3 regra 2 e regra 4, com processos: o que não tocou não aparece no histórico."""
    supervisor.iniciar("agentd", "--parar-em", "Cancel", "--timeout", str(LIMITE))
    supervisor.esperar_barramento()
    supervisor.iniciar("audio-io", "--capturar", "--enfileirar-ms", "2000", "--timeout", "10")

    # O `Cancel` só sai quando a fala começa (220 ms no roteiro), e o playback publica
    # progresso a cada fim de pedaço antes disso — então quem se espera é o `Cancel`.
    esperar(supervisor.raiz, Tipo.CANCEL)
    time.sleep(0.3)  # deixa a reação do audio-io chegar ao log

    with LogDeEventos(supervisor.raiz / "eventos.sqlite") as log:
        registros = [r.envelope for r in log.ler()]

    tipos = [e.type for e in registros]
    corte = tipos.index(Tipo.CANCEL)
    cancel = registros[corte]
    depois = [e for e in registros[corte + 1 :] if e.type is Tipo.PLAYBACK_PROGRESS]

    assert cancel.source == "agentd", "quem emite Cancel é o agentd (§3.2)"
    assert depois, "o audio-io tem de publicar o played_ms do pedaço truncado"
    truncado = depois[0]
    assert truncado.source == "audio-io"
    assert truncado.payload["chunk_id"].startswith("tts-")
    # Dos 2 s enfileirados, o que conta é o que saiu: muito menos que o enfileirado.
    assert 0 <= truncado.payload["played_ms"] <= 200
    # E nada mais toca depois do cancelamento: a fila foi esvaziada no mesmo tick.
    assert len(depois) == 1, [e.payload for e in depois]
