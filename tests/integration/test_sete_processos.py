"""Aceite F0-03: os sete processos de verdade, com o evento sintético atravessando (§2).

Este teste lança processos. Duas regras do projeto valem aqui: tudo acontece em pasta
temporária (nunca na sessão do dono) e **nenhum processo é procurado por nome** — o supervisor
só encerra os `Popen` que ele mesmo criou, pelo PID registrado.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.barramento import LogDeEventos, Tipo
from jarvis.supervisao import Supervisor

LIMITE = 30.0
CADEIA_ESPERADA = [
    Tipo.AUDIO_ACTIVITY,  # audio-io recebe do mundo
    Tipo.CANCEL,  # agentd: speech_started sobe o epoch antes do ASR (regra 1)
    Tipo.FINAL_TRANSCRIPT,  # agentd: percepção
    Tipo.TOOL_CALL_REQUESTED,  # s2 propõe
    Tipo.POLICY_DECISION,  # policy autoriza (decisão antes do efeito)
    Tipo.TOOL_RESULT,  # executor devolve
    Tipo.STATE_REVISION,  # s2 volta com o estado: o evento "voltou"
]


@pytest.fixture
def supervisor(tmp_path: Path) -> Iterator[Supervisor]:
    supervisor = Supervisor(raiz=tmp_path / "exec")
    yield supervisor
    supervisor.parar_tudo()


def tipos_no_log(raiz: Path) -> list[Tipo]:
    arquivo = raiz / "eventos.sqlite"
    if not arquivo.exists():
        return []
    with LogDeEventos(arquivo) as log:
        return [r.envelope.type for r in log.ler()]


def esperar(raiz: Path, tipo: Tipo, *, limite: float = LIMITE) -> list[Tipo]:
    """Espera um tipo aparecer no log, sem laço cego: devolve a cadeia vista."""
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        tipos = tipos_no_log(raiz)
        if tipo in tipos:
            return tipos
        time.sleep(0.05)
    raise AssertionError(f"{tipo} não apareceu em {limite}s; log tem {tipos_no_log(raiz)}")


def subir_tudo(supervisor: Supervisor, *, sem: str = "") -> None:
    supervisor.iniciar("agentd", "--parar-em", "StateRevision", "--timeout", str(LIMITE))
    supervisor.esperar_barramento()
    for nome in ("s2", "policy", "executor", "memoryd", "ui"):
        if nome != sem:
            supervisor.iniciar(nome, "--timeout", str(LIMITE))
    supervisor.iniciar("audio-io", "--emitir-fala", "--timeout", str(LIMITE))


def test_evento_sintetico_atravessa_os_sete_processos_com_epoch_preservado(
    supervisor: Supervisor,
) -> None:
    """Aceite (a): audio-io → agentd → s2 → policy → executor e volta, com epoch e sessão."""
    raiz = supervisor.raiz
    subir_tudo(supervisor)

    esperar(raiz, Tipo.STATE_REVISION)
    sessao = (raiz / "sessao").read_text(encoding="utf-8").strip()

    with LogDeEventos(raiz / "eventos.sqlite") as log:
        registros = list(log.ler())
        assert [r.envelope.type for r in registros] == CADEIA_ESPERADA
        assert log.verificar_cadeia() == len(CADEIA_ESPERADA)

        # Uma sessão só, do primeiro ao último evento.
        assert {r.envelope.session_id for r in registros} == {sessao}

        # O epoch sobe uma vez (no barge-in sintético) e depois é preservado ponta a ponta.
        por_tipo = {r.envelope.type: r.envelope for r in registros}
        assert por_tipo[Tipo.AUDIO_ACTIVITY].epoch == 0
        depois_do_cancel = [e for t, e in por_tipo.items() if t is not Tipo.AUDIO_ACTIVITY]
        assert {e.epoch for e in depois_do_cancel} == {1}

        # O mesmo call_id atravessa s2 → policy → executor → s2.
        call_id = por_tipo[Tipo.TOOL_CALL_REQUESTED].payload["call_id"]
        assert por_tipo[Tipo.POLICY_DECISION].payload["call_id"] == call_id
        assert por_tipo[Tipo.TOOL_RESULT].payload["call_id"] == call_id
        assert por_tipo[Tipo.STATE_REVISION].payload["task_id"] == call_id

        # Cada processo publicou do seu lugar, e o trust veio da fronteira.
        assert por_tipo[Tipo.AUDIO_ACTIVITY].trust == "user_voice"
        assert por_tipo[Tipo.TOOL_RESULT].trust == "tool_result"

    # memoryd e ui também estavam no barramento (os sete, não cinco).
    assert (raiz / "memoryd-episodios.jsonl").exists()
    assert (raiz / "cursor-ui").exists()


def test_processo_reaberto_recebe_o_que_perdeu_e_nao_duplica_efeito(
    supervisor: Supervisor,
) -> None:
    """Aceite (b): matar e reabrir no meio não perde log nem repete efeito."""
    raiz = supervisor.raiz
    subir_tudo(supervisor, sem="executor")

    # Sem executor, a cadeia para na decisão de política — e nada se perde.
    esperar(raiz, Tipo.POLICY_DECISION)
    assert Tipo.TOOL_RESULT not in tipos_no_log(raiz)

    # Ele sobe depois e recebe do log o que passou enquanto estava fora.
    supervisor.iniciar("executor", "--timeout", str(LIMITE))
    esperar(raiz, Tipo.STATE_REVISION)
    assert tipos_no_log(raiz) == CADEIA_ESPERADA

    # Agora o pior caso: o executor morre e volta tendo perdido o cursor, então recebe a
    # mesma PolicyDecision outra vez. O efeito não pode acontecer duas vezes.
    assert supervisor.parar("executor") is not None
    (raiz / "cursor-executor").unlink()
    supervisor.iniciar("executor", "--timeout", "3")
    time.sleep(3.5)

    tipos = tipos_no_log(raiz)
    assert tipos.count(Tipo.TOOL_RESULT) == 1, tipos
    with LogDeEventos(raiz / "eventos.sqlite") as log:
        assert log.verificar_cadeia() == len(tipos)  # nada foi perdido nem reescrito


def test_s2_nao_publica_nada_de_epoch_morto() -> None:
    """Aceite (c), na unidade: o stub do s2 recusa reagir a evento de epoch velho."""
    from jarvis.processo import Processo
    from jarvis.s2.__main__ import reagir
    from tests.fabricas import evento

    processo = Processo(nome="s2", raiz=Path(), reacao=reagir, session_id="x", epoch=3)
    velho = evento(Tipo.FINAL_TRANSCRIPT, "01a14079-bebc-7e23-8521-d6ad00000000", epoch=2)
    atual = evento(Tipo.FINAL_TRANSCRIPT, "01a14079-bebc-7e23-8521-d6ad00000000", epoch=3)

    assert reagir(processo, velho, "aceitar") == []
    assert len(reagir(processo, atual, "aceitar")) == 1


def test_resultado_stale_nao_vira_revisao_de_estado() -> None:
    """§3.3 regra 3: leitura que sobreviveu ao cancelamento espera reavaliação, não fala."""
    from jarvis.processo import Processo
    from jarvis.s2.__main__ import reagir
    from tests.fabricas import evento

    processo = Processo(nome="s2", raiz=Path(), reacao=reagir, session_id="x", epoch=1)
    resultado = evento(
        Tipo.TOOL_RESULT, "01a14079-bebc-7e23-8521-d6ad00000000", epoch=1, read_only=True
    )

    assert reagir(processo, resultado, "aceitar_stale") == []
    assert len(reagir(processo, resultado, "aceitar")) == 1
