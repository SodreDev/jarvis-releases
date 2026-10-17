"""ADR-0025, aceites (d), (e) e (f): uma hora simulada de conversa com 50 avisos.

Relógio virtual em passos de 100 ms: o dono fala em momentos aleatórios (semente comitada), as
notificações chegam em momentos aleatórios, o cérebro real (`Cerebro`) monta os pedaços de fala
e a fila real (`FilaDeAvisos`) decide quando liberar. Cada pedaço "toca" pelo número de palavras;
o dono falando por cima corta o que estiver tocando. As invariantes, as do dono e as da D22:

- nenhuma liberação espontânea com o dono falando, o TTS tocando ou menos de 1,5 s de silêncio;
- entre dois avisos falados espontaneamente, pelo menos 2 min;
- a mensagem do dono leva **todos** os pendentes;
- aviso cortado volta para a fila e, no fim, **nenhum aviso se perde**: todos tocaram.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from jarvis.agentd.fila_de_avisos import PISO_LIVRE_S, TETO_DE_FALA_S, Entrega, FilaDeAvisos
from jarvis.barramento import Envelope, Tipo, Trust, prioridade_canonica, validar
from jarvis.s2.avisos import AvisoLiberado
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor_roteirizado import MotorRoteirizado

SESSAO = "01a1c000-0000-7000-8000-000000000005"
SEMENTE = 20_261_016
PASSO_S = 0.1
DURACAO_S = 3600.0
AVISOS = 50
SEGUNDOS_POR_PALAVRA = 0.3


@dataclass
class Tocando:
    pedacos: list[tuple[float, list[str]]]
    """(instante em que o pedaço acaba de tocar, notif_ids que ele carrega)."""
    espontaneo: bool


@dataclass
class Simulacao:
    fila: FilaDeAvisos = field(default_factory=lambda: FilaDeAvisos(session_id=SESSAO))
    cerebro: Cerebro = field(
        default_factory=lambda: Cerebro(motor=MotorRoteirizado(resposta="Certo, entendi."))
    )
    tocando: Tocando | None = None
    dono_falando: bool = False
    silencio_desde: float = 0.0
    liberacoes_espontaneas: list[float] = field(default_factory=list)
    falados: list[float] = field(default_factory=list)
    cortes: int = 0
    violacoes: list[str] = field(default_factory=list)

    def _avisos(self, envelope: Envelope) -> list[AvisoLiberado]:
        return [
            AvisoLiberado(
                n, self.fila.avisos[n].tipo, self.fila.avisos[n].origem, self.fila.avisos[n].resumo
            )
            for n in envelope.payload["notif_ids"]
        ]

    def _tocar(self, publicados: list[dict[str, Any]], agora: float, *, espontaneo: bool) -> None:
        fim = agora
        pedacos = []
        for pedaco in publicados:
            if not pedaco["text"]:
                continue
            fim += SEGUNDOS_POR_PALAVRA * len(pedaco["text"].split())
            pedacos.append((fim, list(pedaco.get("notif_ids", []))))
        self.tocando = Tocando(pedacos, espontaneo)
        self.fila.tts_tocando(True, agora)

    def _encerrar_fala(self, agora: float, *, cortada: bool) -> None:
        assert self.tocando is not None
        tocados: dict[str, bool] = {}
        for fim, notif_ids in self.tocando.pedacos:
            for n in notif_ids:
                tocados[n] = tocados.get(n, True) and fim <= agora
        entregues = [n for n, ok in tocados.items() if ok]
        if entregues:
            self.fila.tocou(entregues, agora)
            self.falados.append(agora)
        self.fila.cortado([n for n, ok in tocados.items() if not ok])
        self.cortes += cortada and any(not ok for ok in tocados.values())
        self.tocando = None
        self.fila.tts_tocando(False, agora)
        self.silencio_desde = agora

    def passo(self, agora: float, *, comeca: bool, termina: bool, chegou: str | None) -> None:
        if chegou is not None:
            payload = {
                "notif_id": chegou,
                "origem": "tarefa · simulada",
                "tipo": "concluida",
                "resumo": f"a tarefa {chegou} terminou",
            }
            self.fila.receber(
                validar(
                    Envelope(
                        session_id=SESSAO,
                        epoch=0,
                        source="executor",
                        trust=Trust.SYSTEM,
                        priority=prioridade_canonica(Tipo.NOTIFICATION, payload),
                        type=Tipo.NOTIFICATION,
                        payload=payload,
                    )
                ),
                agora,
            )
        if comeca:
            self.dono_falando = True
            self.fila.dono_falando(True, agora)
            if self.tocando is not None:
                self._encerrar_fala(agora, cortada=True)  # barge-in: o dono vence (P3)
        if termina:
            self.dono_falando = False
            self.fila.dono_falando(False, agora)
            self.silencio_desde = agora
            pendentes = {a.notif_id for a in self.fila.avisos.values() if a.pendente}
            liberacao = self.fila.mensagem_do_dono(f"t-{agora:.1f}", agora)
            avisos = self._avisos(liberacao) if liberacao else []
            if {a.notif_id for a in avisos} != pendentes:
                self.violacoes.append(f"{agora:.1f}: a mensagem não levou todos os pendentes")
            publicados: list[dict[str, Any]] = []
            self.cerebro.responder("e então?", epoch=0, publicar=publicados.append, avisos=avisos)
            self._tocar(publicados, agora, espontaneo=False)
        if self.tocando is not None and agora >= self.tocando.pedacos[-1][0]:
            self._encerrar_fala(agora, cortada=False)
        if self.tocando is None and not self.dono_falando:
            liberacao = self.fila.liberar(agora)
            if liberacao is not None:
                if agora - self.silencio_desde < PISO_LIVRE_S - 1e-9:
                    self.violacoes.append(
                        f"{agora:.1f}: liberou com {agora - self.silencio_desde:.1f} s de silêncio"
                    )
                if self.falados and agora - self.falados[-1] < TETO_DE_FALA_S - 1e-9:
                    self.violacoes.append(
                        f"{agora:.1f}: menos de 2 min depois do último aviso falado"
                    )
                self.liberacoes_espontaneas.append(agora)
                publicados = []
                self.cerebro.avisar(self._avisos(liberacao), epoch=0, publicar=publicados.append)
                self._tocar(publicados, agora, espontaneo=True)


def _roteiro(sorteio: random.Random) -> tuple[list[tuple[float, float]], dict[int, str]]:
    falas: list[tuple[float, float]] = []
    instante = 0.0
    while True:
        instante += sorteio.expovariate(1 / 90)
        duracao = sorteio.uniform(1.0, 6.0)
        if instante + duracao > DURACAO_S:
            break
        falas.append((instante, instante + duracao))
        instante += duracao
    chegadas = {
        round(sorteio.uniform(0, DURACAO_S - 300) / PASSO_S): f"n{i}" for i in range(AVISOS)
    }
    return falas, chegadas


def test_uma_hora_de_conversa_com_cinquenta_avisos() -> None:
    sorteio = random.Random(SEMENTE)
    falas, chegadas = _roteiro(sorteio)
    assert len(chegadas) == AVISOS, "duas chegadas no mesmo passo: troque a semente"
    inicios = {round(i / PASSO_S) for i, _ in falas}
    fins = {round(f / PASSO_S) for _, f in falas}
    simulacao = Simulacao()

    # A hora simulada, e depois o silêncio que for preciso para a fila esvaziar no teto de 2 min.
    passos = round((DURACAO_S + AVISOS * (TETO_DE_FALA_S + 10)) / PASSO_S)
    for passo in range(passos):
        simulacao.passo(
            passo * PASSO_S,
            comeca=passo in inicios,
            termina=passo in fins,
            chegou=chegadas.get(passo),
        )

    assert simulacao.violacoes == []
    entregas = [a.entrega for a in simulacao.fila.avisos.values()]
    assert entregas == [Entrega.FALADO] * AVISOS, "algum aviso se perdeu"
    assert simulacao.cortes > 0, "nenhum barge-in caiu num aviso: a prova da regra 15 é vazia"
    assert simulacao.liberacoes_espontaneas, "nenhuma liberação por piso livre aconteceu"
    espacamentos = [
        b - a
        for a, b in zip(
            simulacao.liberacoes_espontaneas, simulacao.liberacoes_espontaneas[1:], strict=False
        )
    ]
    assert all(e >= TETO_DE_FALA_S - PASSO_S for e in espacamentos)
