"""Playback cancelável e `played_ms` que vem das amostras consumidas (cartão F1-03).

Três regras da SPEC moram aqui:

- **§3.3 regra 2** — `audio-io` esvazia a fila de playback **no mesmo tick** do `Cancel`. Não
  é "para de enfileirar": é jogar fora o que já estava enfileirado, na mesma chamada.
- **§3.3 regra 4** — o histórico registra só `played_ms` real. Então `played_ms` não é
  "quanto eu mandei tocar": é `amostras_consumidas` do sumidouro, lidas **dele**, depois de
  consumir. Áudio enfileirado e não tocado não existe para o modelo.
- **§3.3 regra 6** — pedaço com `epoch` menor que o atual é descartado e nunca toca.

Quem emite `Cancel` é o `agentd` (§3.2, origem canônica), não o `audio-io`. Esta fila **reage**
ao cancelamento: devolve o `PlaybackProgress` final do pedaço truncado e quantas amostras foram
jogadas fora.

`PlaybackProgress` é **fato**, não hipótese (não entra no coalescing do barramento), então ele
sai nos momentos que mudam o histórico: fim de pedaço e cancelamento. Progresso periódico para
interface existe, mas é opcional (`intervalo_de_progresso_ms`) e desligado por padrão — 50
fatos por segundo no barramento seria ruído, não informação.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from jarvis.audio_io.quadro import (
    AMOSTRAS_POR_QUADRO,
    BYTES_POR_AMOSTRA,
    BYTES_POR_QUADRO,
    TAXA_PADRAO,
)
from jarvis.audio_io.sumidouros import SumidouroDeAudio
from jarvis.barramento.contrato import validar
from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust

MOTIVOS: Final[frozenset[str]] = frozenset(
    {"barge_in", "stop_word", "privacy", "aec_fail", "timeout"}
)
"""Os motivos de `Cancel` da §3.2. Motivo fora da lista é erro aqui, não string livre."""


@dataclass(frozen=True, slots=True)
class Pedaco:
    """Um pedaço de áudio de TTS, com o `epoch` em que ele foi pedido."""

    chunk_id: str
    epoch: int
    amostras: bytes

    @property
    def n_amostras(self) -> int:
        return len(self.amostras) // BYTES_POR_AMOSTRA

    @property
    def duracao_ms(self) -> float:
        return 1000.0 * self.n_amostras / TAXA_PADRAO


@dataclass(frozen=True, slots=True)
class Cancelamento:
    """O que o cancelamento produziu: eventos a publicar e o tamanho do prejuízo."""

    eventos: list[Envelope] = field(default_factory=list)
    amostras_descartadas: int = 0
    pedacos_descartados: int = 0
    played_ms: int = 0
    """`played_ms` do pedaço que estava tocando — o que o histórico pode registrar."""


@dataclass(slots=True)
class FilaDePlayback:
    """A fila de playback do `audio-io`. Esvaziável no mesmo tick, por contrato."""

    sumidouro: SumidouroDeAudio
    session_id: str
    epoch_atual: int = 0
    intervalo_de_progresso_ms: float = 0.0
    taxa: int = TAXA_PADRAO
    escuta: Callable[[bytes], None] | None = None
    """Loopback de referência: recebe cada fatia que **saiu** para o sumidouro (F1-04)."""
    pausado: bool = False
    """Pausa sem descartar. É o que o `audio-io` faz enquanto `aec_ok` é falso: continuar
    falando sem AEC é o caminho curto para o assistente se interromper sozinho."""

    descartados_por_epoch: int = 0
    _fila: deque[Pedaco] = field(default_factory=deque, repr=False)
    _tocando: Pedaco | None = field(default=None, repr=False)
    _consumido_do_pedaco: int = field(default=0, repr=False)
    _base_do_sumidouro: int = field(default=0, repr=False)
    _ultimo_progresso_ms: int = field(default=0, repr=False)

    # --- consulta -------------------------------------------------------------------
    @property
    def tocando(self) -> Pedaco | None:
        return self._tocando

    @property
    def pedacos_na_fila(self) -> int:
        return len(self._fila) + (1 if self._tocando is not None else 0)

    @property
    def amostras_enfileiradas(self) -> int:
        """Amostras que ainda **não** saíram: o que um `Cancel` jogaria fora agora."""
        pendente = sum(p.n_amostras for p in self._fila)
        if self._tocando is not None:
            # `_consumido_do_pedaco` está em BYTES e `n_amostras` em amostras: somar os dois
            # direto é o bug que o teste do aceite (a) pegou (sobra 600 ms onde há 800 ms).
            consumidas = self._consumido_do_pedaco // BYTES_POR_AMOSTRA
            pendente += self._tocando.n_amostras - consumidas
        return pendente

    @property
    def played_ms(self) -> int:
        """Milissegundos do pedaço em curso, contados nas amostras **consumidas**."""
        consumidas = self.sumidouro.amostras_consumidas - self._base_do_sumidouro
        return int(1000 * max(0, consumidas) / self.taxa)

    # --- operação -------------------------------------------------------------------
    def enfileirar(self, pedaco: Pedaco) -> bool:
        """Aceita o pedaço, ou o descarta por `epoch` velho (§3.3 regra 6) devolvendo `False`."""
        if pedaco.epoch < self.epoch_atual:
            self.descartados_por_epoch += 1
            return False
        if len(pedaco.amostras) % BYTES_POR_AMOSTRA:
            raise ValueError(f"pedaço {pedaco.chunk_id}: bytes ímpares não são PCM16")
        self._fila.append(pedaco)
        return True

    def tick(self) -> list[Envelope]:
        """Consome um quadro de 20 ms do pedaço em curso e devolve os eventos que isso gerou."""
        if self.pausado:
            return []
        if self._tocando is None and not self._iniciar_proximo():
            return []
        assert self._tocando is not None

        inicio = self._consumido_do_pedaco
        fatia = self._tocando.amostras[inicio : inicio + BYTES_POR_QUADRO]
        # O avanço é o que o sumidouro **consumiu**, não o que oferecemos: dispositivo saturado
        # aceita menos do que um quadro, e tratar o oferecido como tocado perderia áudio de
        # verdade e inflaria `played_ms` (§3.3 regra 4).
        consumidas = self.sumidouro.escrever(fatia)
        self._consumido_do_pedaco += consumidas * BYTES_POR_AMOSTRA
        if self.escuta is not None and consumidas:
            # A referência da AEC é o que saiu, não o que foi oferecido.
            self.escuta(fatia[: consumidas * BYTES_POR_AMOSTRA])

        eventos: list[Envelope] = []
        terminou = self._consumido_do_pedaco >= len(self._tocando.amostras)
        if terminou:
            eventos.append(self._progresso(self._tocando))
            self._tocando = None
            self._consumido_do_pedaco = 0
        elif self.intervalo_de_progresso_ms > 0:
            agora = self.played_ms
            if agora - self._ultimo_progresso_ms >= self.intervalo_de_progresso_ms:
                self._ultimo_progresso_ms = agora
                eventos.append(self._progresso(self._tocando))
        return eventos

    def cancelar(self, *, reason: str = "barge_in", epoch_novo: int | None = None) -> Cancelamento:
        """Esvazia a fila **agora** (§3.3 regra 2) e devolve o `played_ms` do que tocou mesmo."""
        if reason not in MOTIVOS:
            raise ValueError(f"motivo {reason!r} não é um dos da §3.2: {sorted(MOTIVOS)}")

        descartadas = self.amostras_enfileiradas
        pedacos = self.pedacos_na_fila
        eventos: list[Envelope] = []
        tocado_ms = 0
        if self._tocando is not None:
            tocado_ms = self.played_ms
            eventos.append(self._progresso(self._tocando))

        self._fila.clear()
        self._tocando = None
        self._consumido_do_pedaco = 0
        self._ultimo_progresso_ms = 0
        self.sumidouro.limpar()
        if epoch_novo is not None:
            self.epoch_atual = epoch_novo
        return Cancelamento(
            eventos=eventos,
            amostras_descartadas=descartadas,
            pedacos_descartados=pedacos,
            played_ms=tocado_ms,
        )

    # --- interno --------------------------------------------------------------------
    def _iniciar_proximo(self) -> bool:
        while self._fila:
            pedaco = self._fila.popleft()
            if pedaco.epoch < self.epoch_atual:
                self.descartados_por_epoch += 1
                continue
            self._tocando = pedaco
            self._consumido_do_pedaco = 0
            self._base_do_sumidouro = self.sumidouro.amostras_consumidas
            self._ultimo_progresso_ms = 0
            return True
        return False

    def _progresso(self, pedaco: Pedaco) -> Envelope:
        return validar(
            Envelope(
                session_id=self.session_id,
                epoch=pedaco.epoch,
                source="audio-io",
                trust=Trust.SYSTEM,
                priority=Prioridade.P1,
                type=Tipo.PLAYBACK_PROGRESS,
                payload={
                    "chunk_id": pedaco.chunk_id,
                    "played_ms": self.played_ms,
                    "epoch": pedaco.epoch,
                },
            )
        )


def em_pedacos(
    amostras: bytes, *, chunk_id: str, epoch: int, ms_por_pedaco: float = 200.0
) -> list[Pedaco]:
    """Fatia áudio de TTS em pedaços (como o `s2` entregaria), numerados a partir de 1."""
    por_pedaco = max(1, round(ms_por_pedaco / 20.0)) * AMOSTRAS_POR_QUADRO * BYTES_POR_AMOSTRA
    return [
        Pedaco(
            chunk_id=f"{chunk_id}-{i + 1}",
            epoch=epoch,
            amostras=amostras[inicio : inicio + por_pedaco],
        )
        for i, inicio in enumerate(range(0, len(amostras), por_pedaco))
    ]
