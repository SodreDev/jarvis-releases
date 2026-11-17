"""A voz e os ouvidos do Jarvis dentro da ligação (ADR-0074, fatia B), atrás de interfaces.

- `SaidaNaFonteVirtual` é a `Saida` do agente da chamada de verdade: sintetiza a fala e a toca no
  sink da mistura (`jarvis_mix`), que a fonte virtual (`jarvis_mic`) entrega ao app de chamada.
  Em volta de cada fala vale a `PoliticaDeEco` (decisão do dono, 2026-11-17: fone às vezes): sem
  fone, o microfone real fica mudo na mistura enquanto o Jarvis fala; com fone, a voz também toca
  na saída do dono (ele ouve) e nada é abafado. Sem a mistura ligada, a fala **não sai** — e o
  agente recebe o veredito, em vez de achar que falou;
- `EscutaDaChamada` ouve os **dois canais** — o outro lado (`jarvis_outro_lado.monitor`, só o
  fluxo do app de chamada) e o microfone real — com um VAD por canal, e transcreve cada trecho
  num ASR **em paralelo** (uma linha por canal, a ordem de cada um preservada). Canal remoto =
  quem liga (vai ao `Chamada.ouvir`); canal local = o dono: o **começo** da fala dele corta a voz
  do Jarvis na hora (sem esperar o ASR) e o texto vai ao Jarvis como evento. Sem fone, a voz de
  quem liga sai no alto-falante e o mic real a pega: enquanto o canal remoto fala (e um pouco
  depois), o que o mic ouve **não** é tomado como o dono — o dono falando por cima de quem liga,
  sem fone, não corta (limite registrado no estudo);
- `SessaoDeAudio` liga tudo para uma chamada: o misturador (fonte virtual), a captura do outro
  lado, os dois gravadores numa linha cada, e desfaz no fim.

Nada aqui toca áudio nos testes: executor, gravador, tocador, sintetizador e transcritor são
interfaces, com fakes na suíte. **Não provado na máquina real** — é o que `jarvis --testar-chamada`
começa a provar."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import Executor as Linha
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from jarvis.audio_io.misturador import NOME_DO_MIX, Executor, Misturador, PoliticaDeEco
from jarvis.audio_io.outro_lado import CapturaDoOutroLado
from jarvis.audio_io.pulse import Gravador, Tocador
from jarvis.audio_io.quadro import BYTES_POR_QUADRO, MS_POR_QUADRO, Quadro
from jarvis.audio_io.vad import Vad

QUEM_LIGA: Final = "quem_liga"
DONO: Final = "dono"
TRECHO_MAXIMO_MS: Final = 15_000
"""Um trecho maior que isto é transcrito mesmo sem a pausa (quem fala sem parar)."""
SOBRA_DO_REMOTO_MS: Final = 400
"""Sem fone: o mic real ainda pega o fim da voz de quem liga por este tanto depois."""


class Sintetizador(Protocol):
    """PCM s16le mono na taxa padrão (os motores de TTS do app: `sintetizar(texto)`)."""

    def sintetizar(self, texto: str) -> bytes: ...


class Hipotese(Protocol):
    texto: str


class Transcritor(Protocol):
    """Os motores de ASR do app (`transcrever(amostras) -> Hipotese`)."""

    def transcrever(self, amostras: bytes) -> Hipotese: ...


class VozNaoSaiu(RuntimeError):
    """A fala do agente não chegou à chamada (mistura desligada, TTS ou tocador falhou)."""


@dataclass(slots=True)
class SaidaNaFonteVirtual:
    sintetizador: Sintetizador
    tocador: Tocador
    misturador: Misturador
    politica: Callable[[], PoliticaDeEco]
    saida_do_dono: Callable[[], str]
    """O sink em que o dono ouve (o padrão do sistema), para a voz no fone."""
    falas: list[str] = field(default_factory=list)

    def falar(self, texto: str) -> None:
        if not self.misturador.ligado:
            raise VozNaoSaiu("a fonte virtual não está ligada: a voz não chega à chamada")
        try:
            pcm = self.sintetizador.sintetizar(texto)
        except Exception as erro:
            raise VozNaoSaiu(f"o TTS falhou ({type(erro).__name__})") from erro
        politica = self.politica()
        with self.misturador.enquanto_fala(politica):
            fone: threading.Thread | None = None
            if politica.voz_no_fone and self.saida_do_dono():
                fone = threading.Thread(
                    target=self.tocador.tocar, args=(pcm, self.saida_do_dono()), daemon=True
                )
                fone.start()
            self.tocador.tocar(pcm, NOME_DO_MIX)
            if fone is not None:
                fone.join(timeout=30)
        self.falas.append(texto)

    def interromper(self) -> None:
        """O dono falou ou atendeu: a voz para na hora."""
        self.tocador.parar()


@dataclass(slots=True)
class _Canal:
    nome: str
    vad: Vad
    linha: Linha
    trecho: bytearray = field(default_factory=bytearray)
    indice: int = 0
    descartar: bool = False


@dataclass(slots=True)
class EscutaDaChamada:
    transcritor: Transcritor
    vad_de_quem_liga: Vad
    vad_do_dono: Vad
    ao_ouvir_quem_liga: Callable[[str], None]
    ao_dono_comecou: Callable[[], None]
    ao_dono_falou: Callable[[str], None]
    com_fone: Callable[[], bool]
    linhas: Callable[[], tuple[Linha, Linha]] = lambda: (
        ThreadPoolExecutor(1, thread_name_prefix="asr-quem-liga"),
        ThreadPoolExecutor(1, thread_name_prefix="asr-dono"),
    )
    """Uma linha de ASR por canal: os dois em paralelo, cada um na ordem dele."""
    _canais: dict[str, _Canal] = field(init=False)
    _remoto_ate_ms: float = -1.0
    _agora_ms: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        remota, local = self.linhas()
        self._canais = {
            QUEM_LIGA: _Canal(QUEM_LIGA, self.vad_de_quem_liga, remota),
            DONO: _Canal(DONO, self.vad_do_dono, local),
        }

    def _eco_de_quem_liga(self) -> bool:
        if self.com_fone():
            return False
        remoto = self._canais[QUEM_LIGA]
        agora = self._agora_ms.get(DONO, 0.0)
        return bool(remoto.vad.falando) or agora <= self._remoto_ate_ms + SOBRA_DO_REMOTO_MS

    def quadro(self, canal: str, pcm: bytes) -> None:
        """20 ms de um canal (as linhas de gravação chamam; o teste também)."""
        c = self._canais[canal]
        if len(pcm) != BYTES_POR_QUADRO:
            return
        c.indice += 1
        ms = c.indice * MS_POR_QUADRO
        self._agora_ms[canal] = ms
        mudou = c.vad.ver(Quadro(c.indice, pcm, int(ms * 1_000_000)))
        if mudou is True:
            c.trecho.clear()
            if canal == DONO:
                c.descartar = self._eco_de_quem_liga()
                if not c.descartar:
                    self.ao_dono_comecou()
        if c.vad.falando:
            c.trecho += pcm
            if canal == QUEM_LIGA:
                self._remoto_ate_ms = ms
            if len(c.trecho) * MS_POR_QUADRO // BYTES_POR_QUADRO >= TRECHO_MAXIMO_MS:
                self._fechar(c)
        if mudou is False:
            if canal == QUEM_LIGA:
                self._remoto_ate_ms = ms
            self._fechar(c)

    def _fechar(self, c: _Canal) -> None:
        trecho, c.trecho = bytes(c.trecho), bytearray()
        if not trecho or c.descartar:
            return
        c.linha.submit(self._transcrever, c.nome, trecho)

    def _transcrever(self, canal: str, trecho: bytes) -> None:
        texto = " ".join(str(getattr(self.transcritor.transcrever(trecho), "texto", "")).split())
        if not texto:
            return
        if canal == QUEM_LIGA:
            self.ao_ouvir_quem_liga(texto)
        else:
            self.ao_dono_falou(texto)

    def fechar(self) -> None:
        for c in self._canais.values():
            self._fechar(c)
            with contextlib.suppress(Exception):
                c.linha.shutdown(wait=True)


@dataclass(slots=True)
class SessaoDeAudio:
    """O áudio de uma chamada: liga a fonte virtual e a captura do outro lado, grava os dois
    canais numa linha cada e alimenta a escuta; `encerrar` desfaz tudo, sempre."""

    misturador: Misturador
    captura: CapturaDoOutroLado
    gravador_de_quem_liga: Gravador
    gravador_do_dono: Gravador
    escuta: EscutaDaChamada
    _linhas: list[threading.Thread] = field(default_factory=list)
    _parar: threading.Event = field(default_factory=threading.Event)

    def comecar(self, escolher_app: Callable[[Mapping[str, Any]], bool]) -> None:
        try:
            self.misturador.ligar()
            fonte = self.captura.ligar(escolher_app)
        except Exception:
            self.encerrar()
            raise
        for canal, gravador, dispositivo in (
            (QUEM_LIGA, self.gravador_de_quem_liga, fonte),
            (DONO, self.gravador_do_dono, self.misturador.fisico),
        ):
            linha = threading.Thread(
                target=self._gravar, args=(canal, gravador, dispositivo), daemon=True
            )
            self._linhas.append(linha)
            linha.start()

    def _gravar(self, canal: str, gravador: Gravador, dispositivo: str) -> None:
        with contextlib.suppress(Exception):
            for pcm in gravador.quadros(dispositivo):
                if self._parar.is_set():
                    break
                self.escuta.quadro(canal, pcm)

    def encerrar(self) -> None:
        self._parar.set()
        for gravador in (self.gravador_de_quem_liga, self.gravador_do_dono):
            with contextlib.suppress(Exception):
                gravador.fechar()
        for linha in self._linhas:
            linha.join(timeout=3)
        self._linhas.clear()
        with contextlib.suppress(Exception):
            self.escuta.fechar()
        self.captura.desligar()
        self.misturador.desligar()


NAVEGADORES: Final = (
    "chromium",
    "chromium-browser",
    "chrome",
    "google-chrome",
    "brave",
    "brave-browser",
    "vivaldi",
    "opera",
    "msedge",
    "firefox",
)
"""O WhatsApp Web toca a ligação pelo navegador: o fluxo dele é o do outro lado. Outra aba do mesmo
navegador tocando ao mesmo tempo também casa — a captura usa o fluxo mais recente e avisa."""


@dataclass(slots=True)
class AudioDeVerdade:
    """O `AudioDaChamada` que o app monta: a voz na fonte virtual e os ouvidos nos dois canais,
    ligados à central (fala de quem liga → agente; começo da fala do dono → corta a voz)."""

    saida: SaidaNaFonteVirtual
    sessao: SessaoDeAudio
    escolher_app: Callable[[Mapping[str, Any]], bool]

    def comecar(self) -> None:
        self.sessao.comecar(self.escolher_app)

    def encerrar(self) -> None:
        self.saida.interromper()
        self.sessao.encerrar()


def montar_audio(
    *,
    executor: Executor,
    sintetizador: Sintetizador,
    transcritor: Transcritor,
    trava: threading.Lock,
    fone: str,
    ao_ouvir_quem_liga: Callable[[str], None],
    ao_dono_falou: Callable[[str], None],
    gravador: Callable[[], Gravador] | None = None,
    tocador: Tocador | None = None,
    vad: Callable[[], Vad] | None = None,
) -> AudioDeVerdade:
    """O áudio de uma chamada com as peças de verdade (ou as falsas, nos testes): a política de eco
    sai do ajuste `fone` e, em «auto», do que o sistema diz da saída padrão — na hora de atender."""
    from jarvis.audio_io.misturador import fone_na_saida, politica_de_eco
    from jarvis.audio_io.outro_lado import por_app
    from jarvis.audio_io.pulse import GravadorPorParec, TocadorPorPacat
    from jarvis.audio_io.vad import VadDeEnergia

    novo_gravador = gravador or GravadorPorParec
    novo_vad = vad or VadDeEnergia
    politica = politica_de_eco(fone, fone_na_saida(executor) if fone == "auto" else None)
    misturador = Misturador(executor=executor)

    def saida_do_dono() -> str:
        resposta = executor.rodar(("pactl", "get-default-sink"))
        return resposta.texto.strip() if resposta.codigo == 0 else ""

    saida = SaidaNaFonteVirtual(
        sintetizador=sintetizador,
        tocador=tocador or TocadorPorPacat(),
        misturador=misturador,
        politica=lambda: politica,
        saida_do_dono=saida_do_dono,
    )
    escuta = EscutaDaChamada(
        transcritor=TranscritorComTrava(transcritor, trava),
        vad_de_quem_liga=novo_vad(),
        vad_do_dono=novo_vad(),
        ao_ouvir_quem_liga=ao_ouvir_quem_liga,
        ao_dono_comecou=saida.interromper,
        ao_dono_falou=ao_dono_falou,
        com_fone=lambda: politica.fone is True,
    )
    sessao = SessaoDeAudio(
        misturador=misturador,
        captura=CapturaDoOutroLado(executor),
        gravador_de_quem_liga=novo_gravador(),
        gravador_do_dono=novo_gravador(),
        escuta=escuta,
    )
    return AudioDeVerdade(saida=saida, sessao=sessao, escolher_app=por_app(*NAVEGADORES))


@dataclass(slots=True)
class TranscritorComTrava:
    """O ASR do app é um só: a chamada o usa com a mesma trava do laço do Jarvis."""

    transcritor: Transcritor
    trava: threading.Lock

    def transcrever(self, amostras: bytes) -> Hipotese:
        with self.trava:
            return self.transcritor.transcrever(amostras)


__all__ = [
    "DONO",
    "NAVEGADORES",
    "QUEM_LIGA",
    "AudioDeVerdade",
    "EscutaDaChamada",
    "SaidaNaFonteVirtual",
    "SessaoDeAudio",
    "Sintetizador",
    "Transcritor",
    "TranscritorComTrava",
    "VozNaoSaiu",
    "montar_audio",
]
