"""ADR-0025, aceite (a): interromper uma resposta **em stream** em 20 pontos.

O caminho inteiro em memória, com o motor gerando enquanto o TTS fala: o cérebro (`s2`) publica
`ResponseChunk` numa linha de execução; o TTS sintetiza cada pedaço do epoch corrente e o põe na
fila de playback; a fila toca quadro a quadro; num ponto, o dono fala por cima. Três invariantes
em todos os pontos, as da ADR-0025:

1. **zero pedaço de epoch morto tocado** — nenhuma amostra sai depois do `Cancel`;
2. **zero `ResponseChunk` publicado depois do cancelamento**, e o motor parou de gerar;
3. **a conversa contém só o tocado** — o turno do Jarvis que volta ao modelo é prefixo do que
   foi falado e não tem nada além do que as amostras tocadas cobrem.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from jarvis.agentd.fala_em_stream import falar_stream_para
from jarvis.agentd.tts import MotorParametrico, SintetizadorEmStreaming
from jarvis.audio_io.playback import FilaDePlayback
from jarvis.audio_io.sumidouros import SumidouroEmMemoria
from jarvis.barramento.envelope import uuid7
from jarvis.barramento.epoch import DonoDoEpoch
from jarvis.s2.cerebro import Cerebro, Resposta
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.voz.interface import cancelado_por_epoch

pytestmark = pytest.mark.cancelamento

RESPOSTA = " ".join(
    f"Na etapa {indice} vem uma explicação clara para manter toda a resposta organizada e "
    "fácil de acompanhar."
    for indice in range(12)
)
QUADROS_POR_PEDACO = 6
"""Quantos quadros de 20 ms tocam a cada pedaço que chega: o motor gera enquanto o TTS fala."""
ATRASO_ENTRE_DELTAS_S = 0.0005
"""~0,5 ms por delta de 4 caracteres: o motor ainda está gerando enquanto os primeiros pedaços
tocam, que é o caso que a ADR-0025 existe para tratar."""
PONTOS_NA_GERACAO = 10
PONTOS_NO_PLAYBACK = 10


@dataclass
class Rodada:
    resposta: Resposta
    tocado: str
    falado: str
    amostras_depois_do_cancel: int
    publicados_depois_do_cancel: int
    conversa_do_jarvis: str | None
    ticks: int
    interrompeu: bool


@dataclass
class TurnoEmStream:
    """Um turno inteiro, com barge-in opcional no tick `interromper_em`."""

    interromper_em: int | None = None
    sessao: str = field(default_factory=uuid7)

    def rodar(self) -> Rodada:
        epoch = DonoDoEpoch(session_id=self.sessao)
        cancelado = cancelado_por_epoch(lambda: epoch.epoch_atual, epoch.epoch_atual)
        cerebro = Cerebro(
            motor=MotorRoteirizado(resposta=RESPOSTA, atraso_entre_deltas_s=ATRASO_ENTRE_DELTAS_S)
        )
        pedacos: queue.Queue[dict[str, Any] | None] = queue.Queue()
        publicados: list[tuple[bool, dict[str, Any]]] = []
        cancelou = threading.Event()

        def publicar(payload: dict[str, Any]) -> None:
            publicados.append((cancelou.is_set(), payload))
            pedacos.put(payload)

        resultado: dict[str, Resposta] = {}

        def s2() -> None:
            resultado["r"] = cerebro.responder(
                "e depois de quinta?", epoch=0, publicar=publicar, cancelado=cancelado
            )
            pedacos.put(None)

        sumidouro = SumidouroEmMemoria()
        fila = FilaDePlayback(sumidouro=sumidouro, session_id=self.sessao)
        sintese = SintetizadorEmStreaming(
            motor=MotorParametrico(), session_id=self.sessao, epoch=0, cancelado=cancelado
        )
        ticks = 0
        amostras_no_cancel: int | None = None

        def tocar(quadros: int) -> None:
            nonlocal ticks, amostras_no_cancel
            for _ in range(quadros):
                if self.interromper_em is not None and ticks == self.interromper_em:
                    novo = epoch.fala_comecou()
                    cancelou.set()
                    fila.cancelar(epoch_novo=epoch.epoch_atual)
                    amostras_no_cancel = sumidouro.amostras_consumidas
                    del novo
                fila.tick()
                ticks += 1

        def do_stream() -> Iterator[dict[str, Any]]:
            while True:
                try:
                    pedaco = pedacos.get(timeout=0.01)
                except queue.Empty:
                    if cancelado():
                        return
                    continue
                if pedaco is None:
                    return
                yield pedaco

        def enfileirar(pedaco: Any) -> bool:
            aceito = fila.enfileirar(pedaco)
            tocar(QUADROS_POR_PEDACO)
            return aceito

        fio = threading.Thread(target=s2, daemon=True)
        fio.start()
        fala = falar_stream_para(sintese, do_stream(), enfileirar)
        fio.join(timeout=5)
        while fila.pedacos_na_fila and amostras_no_cancel is None:
            tocar(1)
            if self.interromper_em is not None and ticks > self.interromper_em + 1:
                break
        tocar(10)  # depois do cancelamento, nada mais pode sair

        tocadas = (
            amostras_no_cancel if amostras_no_cancel is not None else sumidouro.amostras_consumidas
        )
        tocado = fala.texto_ate(tocadas)
        resposta = resultado["r"]
        cerebro.ouvido(resposta.response_id, tocado, interrompida=amostras_no_cancel is not None)
        do_jarvis = [m.texto for m in cerebro.conversa.turnos if m.papel == "jarvis"]
        return Rodada(
            resposta=resposta,
            tocado=tocado,
            falado=fala.texto,
            amostras_depois_do_cancel=(
                sumidouro.amostras_consumidas - amostras_no_cancel
                if amostras_no_cancel is not None
                else 0
            ),
            publicados_depois_do_cancel=sum(1 for depois, _ in publicados if depois),
            conversa_do_jarvis=do_jarvis[0] if do_jarvis else None,
            ticks=ticks,
            interrompeu=amostras_no_cancel is not None,
        )


@dataclass(frozen=True)
class Referencia:
    ticks: int
    """Ticks de um turno sem interrupção, até a fila esvaziar."""
    ticks_da_geracao: int
    """Ticks tocados enquanto o motor ainda entregava pedaços."""


@pytest.fixture(scope="module")
def referencia() -> Referencia:
    rodada = TurnoEmStream().rodar()
    return Referencia(
        ticks=rodada.ticks, ticks_da_geracao=QUADROS_POR_PEDACO * len(rodada.resposta.publicados)
    )


def _pontos(inicio: int, fim: int, quantos: int) -> list[int]:
    return [
        max(1, inicio + round((fim - inicio) * (i + 1) / (quantos + 1))) for i in range(quantos)
    ]


def test_sem_interrupcao_a_resposta_inteira_toca_e_volta_inteira() -> None:
    rodada = TurnoEmStream().rodar()

    assert not rodada.resposta.cancelada
    assert rodada.falado == " ".join(RESPOSTA.split())
    assert rodada.conversa_do_jarvis == rodada.falado


def _conferir(rodada: Rodada, tick: int) -> None:
    assert rodada.interrompeu, f"tick {tick} não chegou a acontecer"
    assert rodada.amostras_depois_do_cancel == 0, "áudio de epoch morto tocou"
    assert rodada.publicados_depois_do_cancel == 0, "o s2 publicou depois do cancelamento"
    assert rodada.resposta.deltas_depois_do_cancelamento == 0
    assert rodada.falado.startswith(rodada.tocado)
    if rodada.tocado:
        assert rodada.conversa_do_jarvis == rodada.tocado
    assert rodada.conversa_do_jarvis is None or len(rodada.conversa_do_jarvis) <= len(rodada.falado)


@pytest.mark.parametrize("ponto", range(PONTOS_NA_GERACAO))
def test_interromper_enquanto_o_motor_gera(ponto: int, referencia: Referencia) -> None:
    tick = _pontos(0, referencia.ticks_da_geracao, PONTOS_NA_GERACAO)[ponto]
    _conferir(TurnoEmStream(interromper_em=tick).rodar(), tick)


def test_a_maior_parte_dos_cortes_na_geracao_cancela_o_motor(referencia: Referencia) -> None:
    """Sem isto, os dez pontos "na geração" poderiam estar todos caindo depois do fim do
    stream e a suíte provaria só o caso do playback."""
    ticks = _pontos(0, referencia.ticks_da_geracao, PONTOS_NA_GERACAO)
    canceladas = sum(TurnoEmStream(interromper_em=t).rodar().resposta.cancelada for t in ticks)
    assert canceladas >= PONTOS_NA_GERACAO // 2, f"só {canceladas} cortaram o motor gerando"


@pytest.mark.parametrize("ponto", range(PONTOS_NO_PLAYBACK))
def test_interromper_durante_o_playback(ponto: int, referencia: Referencia) -> None:
    tick = _pontos(referencia.ticks_da_geracao, referencia.ticks, PONTOS_NO_PLAYBACK)[ponto]
    _conferir(TurnoEmStream(interromper_em=tick).rodar(), tick)
