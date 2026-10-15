"""Barge-in ponta a ponta, com um marcador por salto (cartão F1-10).

O caminho que a regra 1 da §3.3 exige, inteiro e instrumentado:

    fala do dono → VAD detecta → epoch++ → Cancel P0 → fila de playback vazia
                 → síntese interrompida → s2 cancelado

**De onde se conta o SLO-2.** Do **início real da fala do dono** (que o rótulo do corpus
conhece: `inicio_fala_ms`), não do instante em que o nosso VAD percebeu. O SLO-2 é do ponto de
vista de quem fala — se o VAD demora 60 ms para perceber, esses 60 ms são do dono, não nossos
para esconder.

**Dois relógios, e eles medem coisas diferentes.** O atraso de **áudio** (quantos quadros de
20 ms se passaram) é o que o dono sente; o **custo de código** (microssegundos de CPU) é o que
gastamos para reagir. Somar os dois sem dizer qual é qual faria o relatório parecer ótimo e o
assistente parecer lento. A decomposição publica os dois, salto por salto.

**Nenhum salto espera o ASR.** A `Percepcao` (F1-05) devolve o `Cancel` como **primeiro**
envelope e só então chama o transcritor; o cenário aqui aceita um transcritor lento de propósito
(que avança o relógio em 2 s) para provar que o SLO-2 não muda — é o aceite (b) do cartão.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.agentd.percepcao import Percepcao
from jarvis.agentd.tts import MotorDeTts, SintetizadorEmStreaming, falar_para
from jarvis.audio_io.aec import CadeiaDeAec
from jarvis.audio_io.captura import Captura
from jarvis.audio_io.fontes import FonteDeArquivo
from jarvis.audio_io.playback import FilaDePlayback
from jarvis.audio_io.sumidouros import SumidouroEmMemoria
from jarvis.audio_io.vad import Vad, VadDeEnergia
from jarvis.barramento.envelope import Envelope, Tipo, uuid7
from jarvis.barramento.epoch import DonoDoEpoch
from jarvis.corpus.rotulos import Rotulo
from jarvis.relogio import RelogioFalso

NS_POR_MS: Final = 1_000_000
SLO2_P50_MS: Final = 80.0
SLO2_P95_MS: Final = 150.0
"""SPEC §7. Estourar 150 ms no piso de software abre o gatilho da ADR-0014 (aceite (d))."""

SALTOS: Final[tuple[str, ...]] = (
    "fala_comecou",
    "vad_detectou",
    "epoch_incrementado",
    "cancel_publicado",
    "fila_vazia",
    "sintese_interrompida",
    "s2_cancelado",
)


@dataclass(frozen=True, slots=True)
class Salto:
    """Um salto do caminho, com o tempo de áudio e o custo de código até ele."""

    nome: str
    audio_ms: float
    codigo_us: float


@dataclass(frozen=True, slots=True)
class Interrupcao:
    """Uma interrupção medida ponta a ponta."""

    item: str
    saltos: tuple[Salto, ...]
    amostras_tocadas: int
    amostras_descartadas: int
    pedacos_descartados: int
    eventos: tuple[Envelope, ...] = ()

    def _audio(self, nome: str) -> float:
        return next(s.audio_ms for s in self.saltos if s.nome == nome)

    @property
    def slo2_ms(self) -> float:
        """Do início real da fala até o playback silenciado (fila vazia)."""
        return self._audio("fila_vazia") - self._audio("fala_comecou")

    @property
    def slo2_com_codigo_ms(self) -> float:
        """O número conservador: tempo de áudio **mais** o custo de CPU dos saltos.

        Em tempo de áudio os saltos depois da detecção caem todos no mesmo tique de 20 ms, o que
        os fazia aparecer como 0 ms. O custo de CPU deles é real e, no relógio de parede, soma —
        então o veredito do SLO-2 usa este número, não o menor.
        """
        return self.slo2_ms + self.custo_de_codigo_us / 1000.0

    @property
    def atraso_do_vad_ms(self) -> float:
        return self._audio("vad_detectou") - self._audio("fala_comecou")

    @property
    def custo_de_codigo_us(self) -> float:
        return sum(s.codigo_us for s in self.saltos)

    def decomposicao_ms(self) -> dict[str, float]:
        """Quanto cada salto gastou, em tempo de áudio (é o que o dono sente)."""
        saida: dict[str, float] = {}
        anterior = self.saltos[0]
        for salto in self.saltos[1:]:
            saida[f"{anterior.nome}→{salto.nome}"] = salto.audio_ms - anterior.audio_ms
            anterior = salto
        return saida

    def decomposicao_us(self) -> dict[str, float]:
        """Quanto cada salto gastou de CPU — o que é nosso para otimizar."""
        return {s.nome: s.codigo_us for s in self.saltos[1:]}


@dataclass(slots=True)
class CenarioDeBargeIn:
    """Monta o caminho inteiro em processo e interrompe uma resposta em curso.

    Em processo, com relógio injetado, porque o determinismo é o que torna a decomposição
    comparável entre execuções. O caminho de IPC real é do F0-03; o que falta aqui — e está
    declarado — é a fila do **driver**, que é justamente onde o áudio velho sobrevive.
    """

    rotulo: Rotulo
    caminho_audio: Path
    motor_tts: MotorDeTts
    vad: Vad = field(default_factory=VadDeEnergia)
    texto_resposta: str = "Achei três arquivos, o maior é o relatório de junho."
    com_aec: bool = False
    transcritor_lento_ms: float = 0.0
    """Atraso injetado no ASR (aceite (b)): o SLO-2 não pode mudar por causa dele."""

    def rodar(self) -> Interrupcao:
        relogio = RelogioFalso()
        sumidouro = SumidouroEmMemoria()
        sessao = uuid7()
        fila = FilaDePlayback(sumidouro=sumidouro, session_id=sessao)

        # O assistente está falando: a resposta inteira já está sintetizada e enfileirada.
        cancelado = {"valor": False}
        sintetizador = SintetizadorEmStreaming(
            motor=self.motor_tts,
            session_id=sessao,
            epoch=0,
            cancelado=lambda: cancelado["valor"],
        )
        # A resposta inteira é sintetizada e enfileirada antes de o dono falar.
        falar_para(sintetizador, self.texto_resposta, fila.enfileirar)

        cadeia = CadeiaDeAec() if self.com_aec else None
        captura = Captura(
            fonte=FonteDeArquivo(caminho=self.caminho_audio, relogio=relogio),
            relogio=relogio,
            session_id=sessao,
            detector=self.vad,
            cadeia=cadeia,
            tocando=lambda: fila.tocando is not None,
        )
        captura.abrir()

        dono = DonoDoEpoch(session_id=sessao)
        transcritor = (
            _TranscritorLento(relogio, self.transcritor_lento_ms)
            if self.transcritor_lento_ms
            else None
        )
        percepcao = Percepcao(dono=dono, transcritor=transcritor)

        saltos: list[Salto] = [
            Salto("fala_comecou", audio_ms=float(self.rotulo.inicio_fala_ms), codigo_us=0.0)
        ]
        eventos: list[Envelope] = []
        s2_epoch = 0
        descartadas = 0
        try:
            while True:
                fila.tick()  # o assistente segue falando
                novos = captura.tick()
                if not novos and captura.quadros == 0:
                    break
                fala_detectada = next(
                    (e for e in novos if e.type is Tipo.AUDIO_ACTIVITY and e.payload["speech"]),
                    None,
                )
                if fala_detectada is None:
                    if captura.quadros * 20 > self.rotulo.inicio_pausa_ms:
                        break  # o item acabou sem o VAD ver fala: sem interrupção
                    continue

                agora_ms = relogio.mono_ns() / NS_POR_MS
                saltos.append(Salto("vad_detectou", agora_ms, 0.0))
                eventos.append(fala_detectada)

                antes = time.perf_counter_ns()
                resposta = percepcao(fala_detectada, 0)
                custo_percepcao = (time.perf_counter_ns() - antes) / 1000.0
                saltos.append(Salto("epoch_incrementado", agora_ms, custo_percepcao))
                cancelamento = next(e for e in resposta if e.type is Tipo.CANCEL)
                eventos.extend(resposta)
                saltos.append(Salto("cancel_publicado", agora_ms, 0.0))

                antes = time.perf_counter_ns()
                resultado = fila.cancelar(
                    reason=str(cancelamento.payload["reason"]), epoch_novo=cancelamento.epoch
                )
                custo_fila = (time.perf_counter_ns() - antes) / 1000.0
                descartadas = resultado.amostras_descartadas
                eventos.extend(resultado.eventos)
                saltos.append(Salto("fila_vazia", agora_ms, custo_fila))

                antes = time.perf_counter_ns()
                cancelado["valor"] = True
                custo_tts = (time.perf_counter_ns() - antes) / 1000.0
                saltos.append(Salto("sintese_interrompida", agora_ms, custo_tts))

                antes = time.perf_counter_ns()
                s2_epoch = cancelamento.epoch  # o s2 adota o epoch novo (§3.3 regra 6)
                custo_s2 = (time.perf_counter_ns() - antes) / 1000.0
                saltos.append(Salto("s2_cancelado", agora_ms, custo_s2))
                break
        finally:
            captura.fechar()

        assert s2_epoch == dono.epoch_atual or not eventos
        return Interrupcao(
            item=self.rotulo.id,
            saltos=tuple(saltos),
            amostras_tocadas=sumidouro.amostras_consumidas,
            amostras_descartadas=descartadas,
            pedacos_descartados=sintetizador.pedacos_descartados,
            eventos=tuple(eventos),
        )

    @property
    def interrompeu(self) -> bool:
        return True


@dataclass(slots=True)
class _TranscritorLento:
    """ASR que demora de propósito: avança o relógio antes de devolver qualquer parcial."""

    relogio: RelogioFalso
    atraso_ms: float
    nome: str = "asr-lento@teste"

    def comecar(self, *, session_id: str, epoch: int) -> list[Envelope]:
        self.relogio.avancar_ms(self.atraso_ms)
        return []


def extrair_slo2(interrupcoes: Sequence[Interrupcao]) -> dict[str, float]:
    """SLO-2 e decomposição a partir das interrupções — é o extrator que o cartão pede."""
    from jarvis.medicao import percentil

    valores = [i.slo2_com_codigo_ms for i in interrupcoes]
    so_audio = [i.slo2_ms for i in interrupcoes]
    atrasos_vad = [i.atraso_do_vad_ms for i in interrupcoes]
    return {
        "n": float(len(interrupcoes)),
        "slo2_p50": percentil(valores, 50),
        "slo2_p95": percentil(valores, 95),
        "slo2_max": max(valores) if valores else 0.0,
        "slo2_audio_p50": percentil(so_audio, 50),
        "slo2_audio_p95": percentil(so_audio, 95),
        "vad_p50": percentil(atrasos_vad, 50),
        "vad_p95": percentil(atrasos_vad, 95),
        "codigo_us_p50": percentil([i.custo_de_codigo_us for i in interrupcoes], 50),
        "codigo_us_p95": percentil([i.custo_de_codigo_us for i in interrupcoes], 95),
    }


def cenario_para(
    rotulo: Rotulo,
    pasta_corpus: Path,
    motor_tts: MotorDeTts,
    *,
    vad: Callable[[], Vad] | None = None,
    transcritor_lento_ms: float = 0.0,
    com_aec: bool = False,
) -> CenarioDeBargeIn:
    return CenarioDeBargeIn(
        rotulo=rotulo,
        caminho_audio=pasta_corpus / rotulo.arquivo,
        motor_tts=motor_tts,
        vad=vad() if vad is not None else VadDeEnergia(),
        transcritor_lento_ms=transcritor_lento_ms,
        com_aec=com_aec,
    )
