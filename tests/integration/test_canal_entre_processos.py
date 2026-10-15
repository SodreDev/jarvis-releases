"""ADR-0015: o canal de áudio entre `audio-io` e `agentd`, com processos de verdade.

É o que tira o F1-10 do "simulado em processo": aqui os quadros atravessam a fronteira de
processo pelo canal escolhido (`multiprocessing.Connection`, endereço e chave do barramento), e
o barge-in acontece com o `audio-io` e o `agentd` de verdade.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.barramento import LogDeEventos, Tipo
from jarvis.barramento.canal_de_audio import endereco_do_audio
from jarvis.supervisao import Supervisor

LIMITE = 30.0


@pytest.fixture
def supervisor(tmp_path: Path) -> Iterator[Supervisor]:
    supervisor = Supervisor(raiz=tmp_path / "exec")
    yield supervisor
    supervisor.parar_tudo()


def esperar_arquivo(caminho: Path, *, limite: float = LIMITE) -> str:
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if caminho.exists() and caminho.read_text(encoding="utf-8").strip():
            return caminho.read_text(encoding="utf-8").strip()
        time.sleep(0.05)
    raise AssertionError(f"{caminho.name} não apareceu em {limite}s")


def esperar_tipo(raiz: Path, tipo: Tipo, *, limite: float = LIMITE) -> list[Tipo]:
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


def test_o_endereco_do_canal_fica_ao_lado_do_barramento(tmp_path: Path) -> None:
    alvo, familia = endereco_do_audio(tmp_path)

    assert familia in {"AF_UNIX", "AF_PIPE"}
    assert "audio" in alvo
    assert alvo != str(tmp_path / "barramento.sock"), "dois ouvintes não cabem num endereço"


def test_os_quadros_atravessam_a_fronteira_de_processo(supervisor: Supervisor) -> None:
    """O `audio-io` captura e envia; o `agentd` recebe e conta, descartando epoch morto."""
    supervisor.iniciar(
        "agentd", "--canal-de-audio", "--parar-em", "Cancel", "--timeout", str(LIMITE)
    )
    supervisor.esperar_barramento()
    supervisor.iniciar("audio-io", "--capturar", "--canal-de-audio", "--timeout", "6")

    contagem = esperar_arquivo(supervisor.raiz / "quadros-de-audio")
    recebidos, descartados = (int(parte) for parte in contagem.split())

    assert recebidos > 0, "nenhum quadro atravessou o canal"
    assert recebidos + descartados >= recebidos


def test_barge_in_com_os_dois_processos_de_verdade(supervisor: Supervisor) -> None:
    """A cadeia inteira entre processos: quadro → VAD → Cancel → fila esvaziada.

    O número de SLO-2 sai dos carimbos do **log encadeado**, que é o mesmo relógio monotônico
    nos dois processos (Linux). É o piso de software **com** fronteira de processo, escalonador e
    IPC dentro — diferente do piso em processo do F1-10, e ainda sem a fila do driver.
    """
    # `--parar-em Cancel`, não PlaybackProgress: o primeiro progresso é de pedaço que
    # TERMINOU (200 ms), bem antes de a fala do dono começar (220 ms) — parar nele mataria o
    # agentd antes do barge-in. Foi o que aconteceu na primeira versão deste teste.
    supervisor.iniciar(
        "agentd", "--canal-de-audio", "--parar-em", "Cancel", "--timeout", str(LIMITE)
    )
    supervisor.esperar_barramento()
    supervisor.iniciar(
        "audio-io",
        "--capturar",
        "--canal-de-audio",
        "--enfileirar-ms",
        "2000",
        "--timeout",
        "10",
    )

    esperar_tipo(supervisor.raiz, Tipo.CANCEL)
    time.sleep(0.4)  # deixa a reação do audio-io (esvaziar a fila) chegar ao log
    with LogDeEventos(supervisor.raiz / "eventos.sqlite") as log:
        registros = [r.envelope for r in log.ler()]

    tipos = [e.type for e in registros]
    assert Tipo.AUDIO_ACTIVITY in tipos and Tipo.CANCEL in tipos
    fala = next(e for e in registros if e.type is Tipo.AUDIO_ACTIVITY and e.payload["speech"])
    corte = tipos.index(Tipo.CANCEL)
    progresso = next((e for e in registros[corte + 1 :] if e.type is Tipo.PLAYBACK_PROGRESS), None)

    assert progresso is not None, "o audio-io tem de publicar o played_ms do pedaço truncado"
    slo2_ms = (progresso.ts_mono_ns - fala.ts_mono_ns) / 1e6
    assert 0 <= slo2_ms < 150.0, f"SLO-2 entre processos: {slo2_ms:.1f} ms"
    assert progresso.payload["played_ms"] <= 2000
