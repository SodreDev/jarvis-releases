"""Captura: quadro de 20 ms → `AudioActivity`, com o botão de privacidade na fonte (F1-03).

O laço é **por tick**, não por iterador infinito: quem chama decide quando o próximo quadro
acontece. É isso que deixa o mesmo código rodar em tempo real (relógio do sistema) e dentro de
um teste determinístico (relógio falso), e é isso que deixa a privacidade cortar **antes** de
alguém puxar amostra da fonte.

O botão de privacidade é da §2 e do princípio P3 (interromper vence tudo): com ele ligado,
nenhuma amostra sai da fonte — não é filtro na interface nem evento marcado como "ignorar".
Ao ligar no meio da fala sai **um** último `AudioActivity(speech=false)` com a energia no piso,
para ninguém no barramento continuar achando que o dono está falando; depois disso, silêncio
total de eventos.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from jarvis.audio_io.energia import DetectorDeEnergia
from jarvis.audio_io.fontes import FonteDeAudio
from jarvis.audio_io.quadro import MS_POR_QUADRO, PISO_DB, Quadro
from jarvis.audio_io.replay import atividade
from jarvis.barramento.envelope import Envelope
from jarvis.relogio import Relogio

SEGUNDOS_POR_QUADRO = MS_POR_QUADRO / 1000.0


@dataclass(slots=True)
class Captura:
    """O lado do microfone do `audio-io`: um tick, um quadro, zero ou um evento."""

    fonte: FonteDeAudio
    relogio: Relogio
    session_id: str
    detector: DetectorDeEnergia = field(default_factory=DetectorDeEnergia)
    epoch: int = 0
    privacidade: bool = False
    aec_ok: bool = True
    """Vem da cadeia de AEC (cartão F1-04). Aqui é sempre verdadeiro e vai no evento como tal."""

    amostras_capturadas: int = 0
    quadros: int = 0
    ticks_em_privacidade: int = 0
    _quadros: Iterator[Quadro] | None = field(default=None, repr=False)
    _privacidade_anunciada: bool = field(default=True, repr=False)

    def abrir(self) -> None:
        self.fonte.abrir()
        self._quadros = iter(self.fonte.quadros())

    def fechar(self) -> None:
        self._quadros = None
        self.fonte.fechar()

    def ligar_privacidade(self) -> None:
        """Corta na fonte. O anúncio do corte sai no próximo tick, uma única vez."""
        if not self.privacidade:
            self.privacidade = True
            self._privacidade_anunciada = False

    def desligar_privacidade(self) -> None:
        self.privacidade = False
        self._privacidade_anunciada = True

    def tick(self) -> list[Envelope]:
        """Um quadro de 20 ms. Devolve os eventos que esse quadro gerou (zero ou um)."""
        if self._quadros is None:
            raise RuntimeError("captura não foi aberta")

        if self.privacidade:
            self.ticks_em_privacidade += 1
            self.relogio.dormir(SEGUNDOS_POR_QUADRO)
            if self._privacidade_anunciada:
                return []
            self._privacidade_anunciada = True
            if not self.detector.falando:
                return []
            self.detector.falando = False
            return [self._evento(fala=False, energia_db=PISO_DB, ts_mono_ns=self.relogio.mono_ns())]

        quadro = next(self._quadros, None)
        if quadro is None:
            return []
        self.quadros += 1
        self.amostras_capturadas += quadro.n_amostras
        mudou = self.detector.ver(quadro)
        if mudou is None:
            return []
        return [
            self._evento(fala=mudou, energia_db=quadro.energia_db, ts_mono_ns=quadro.ts_mono_ns)
        ]

    def _evento(self, *, fala: bool, energia_db: float, ts_mono_ns: int) -> Envelope:
        return atividade(
            session_id=self.session_id,
            epoch=self.epoch,
            device_id=self.fonte.device_id,
            fala=fala,
            energia_db=energia_db,
            ts_mono_ns=ts_mono_ns,
            aec_ok=self.aec_ok,
        )
