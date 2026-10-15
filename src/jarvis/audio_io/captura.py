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

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from jarvis.audio_io.aec import CadeiaDeAec
from jarvis.audio_io.energia import DetectorDeEnergia
from jarvis.audio_io.fontes import FonteDeAudio
from jarvis.audio_io.quadro import MS_POR_QUADRO, PISO_DB, Quadro
from jarvis.audio_io.replay import atividade
from jarvis.audio_io.vad import Vad
from jarvis.barramento.envelope import Envelope
from jarvis.relogio import Relogio

SEGUNDOS_POR_QUADRO = MS_POR_QUADRO / 1000.0


@dataclass(slots=True)
class Captura:
    """O lado do microfone do `audio-io`: um tick, um quadro, zero ou um evento."""

    fonte: FonteDeAudio
    relogio: Relogio
    session_id: str
    detector: Vad = field(default_factory=DetectorDeEnergia)
    """Qualquer `Vad` (F1-05). O padrão é o limiar do F1-01, que não precisa de modelo; o
    processo usa `vad_do_ambiente()`, que prefere o `silero-vad` quando o peso existe."""
    epoch: int = 0
    privacidade: bool = False
    cadeia: CadeiaDeAec | None = None
    """A cadeia AEC → NR → AGC (cartão F1-04). Sem ela, `aec_ok` é verdadeiro por omissão."""
    tocando: Callable[[], bool] | None = None
    """Diz se há playback em curso — é quando a referência de loopback é obrigatória."""

    aec_ok: bool = True
    ultimo_erle_db: float = 0.0

    amostras_capturadas: int = 0
    quadros: int = 0
    ultimo_quadro: Quadro | None = None
    """O último quadro capturado (já pela cadeia, quando há AEC): é o que vai para o canal de
    áudio da ADR-0015. Guardar em vez de devolver mantém `tick` com uma responsabilidade só —
    publicar evento — e deixa quem quer áudio pegar o áudio."""
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

        aec_antes = self.aec_ok
        if self.cadeia is not None:
            # O detector vê o áudio **depois** da cadeia: é o resíduo que importa, não o eco.
            processado = self.cadeia.processar(
                quadro, tocando=self.tocando() if self.tocando is not None else False
            )
            quadro = processado.quadro
            self.aec_ok = processado.aec_ok
            self.ultimo_erle_db = processado.erle_db

        self.ultimo_quadro = quadro
        mudou = self.detector.ver(quadro)
        if mudou is None and self.aec_ok == aec_antes:
            return []
        # `aec_ok` mudando é fato que o `agentd` precisa ver (é ele que emite Cancel(aec_fail)),
        # mesmo sem transição de fala.
        fala = self.detector.falando if mudou is None else mudou
        return [
            self._evento(
                fala=bool(fala), energia_db=quadro.energia_db, ts_mono_ns=quadro.ts_mono_ns
            )
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
