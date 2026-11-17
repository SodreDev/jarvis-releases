"""ADR-0074, fatia B: a voz do agente na fonte virtual (com a política de eco) e os ouvidos em dois
canais (quem liga × dono, ASR em paralelo). Executor, VAD de energia, sintetizador, tocador,
gravador e transcritor falsos: nenhum áudio, microfone ou servidor de som de verdade."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import Executor, Future
from dataclasses import dataclass, field
from typing import Any

import pytest

from jarvis.audio_io.misturador import (
    NOME_DO_MIX,
    ErroDoMisturador,
    Misturador,
    Saida,
    politica_de_eco,
)
from jarvis.audio_io.outro_lado import (
    FONTE_DO_OUTRO_LADO,
    NOME_DO_SINK,
    CapturaDoOutroLado,
    por_app,
)
from jarvis.audio_io.quadro import BYTES_POR_QUADRO
from jarvis.audio_io.sintese import silencio
from jarvis.audio_io.vad import VadDeEnergia
from jarvis.chamada.voz import (
    DONO,
    QUEM_LIGA,
    EscutaDaChamada,
    SaidaNaFonteVirtual,
    SessaoDeAudio,
    VozNaoSaiu,
)
from tests.unit.audio_io.test_eco_da_chamada import GrafoComSaida
from tests.unit.audio_io.test_misturador import PID_DO_JARVIS

ALTO = (b"\xff\x3f\x01\xc0" * (BYTES_POR_QUADRO // 4))[:BYTES_POR_QUADRO]
"""Um quadro alto (± metade da escala): fala para o VAD de energia."""
MUDO = silencio(20)


class LinhaNaHora(Executor):
    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future[Any]:
        futuro: Future[Any] = Future()
        futuro.set_result(fn(*args, **kwargs))
        return futuro


@dataclass
class Transcritor:
    textos: dict[int, str]
    vistos: list[int] = field(default_factory=list)

    def transcrever(self, amostras: bytes) -> Any:
        quadros = len(amostras) // BYTES_POR_QUADRO
        self.vistos.append(quadros)

        @dataclass
        class H:
            texto: str

        return H(self.textos.get(quadros, f"{quadros} quadros"))


@dataclass
class Ouvidos:
    com_fone: bool = False
    quem_liga: list[str] = field(default_factory=list)
    dono: list[str] = field(default_factory=list)
    cortes: int = 0

    def escuta(self, transcritor: Transcritor) -> EscutaDaChamada:
        return EscutaDaChamada(
            transcritor=transcritor,
            vad_de_quem_liga=VadDeEnergia(),
            vad_do_dono=VadDeEnergia(),
            ao_ouvir_quem_liga=self.quem_liga.append,
            ao_dono_comecou=self._cortar,
            ao_dono_falou=self.dono.append,
            com_fone=lambda: self.com_fone,
            linhas=lambda: (LinhaNaHora(), LinhaNaHora()),
        )

    def _cortar(self) -> None:
        self.cortes += 1


def _falar(escuta: EscutaDaChamada, canal: str, quadros: int, pausa: int = 25) -> None:
    for _ in range(quadros):
        escuta.quadro(canal, ALTO)
    for _ in range(pausa):
        escuta.quadro(canal, MUDO)


def test_cada_canal_vira_um_trecho_transcrito_e_vai_ao_lugar_certo() -> None:
    ouvidos = Ouvidos(com_fone=True)
    escuta = ouvidos.escuta(Transcritor({}))
    _falar(escuta, QUEM_LIGA, 30)
    assert len(ouvidos.quem_liga) == 1 and ouvidos.dono == [] and ouvidos.cortes == 0
    _falar(escuta, DONO, 20)
    assert ouvidos.cortes == 1, "o começo da fala do dono corta a voz na hora"
    assert len(ouvidos.dono) == 1


def test_sem_fone_o_mic_que_pega_quem_liga_nao_vira_o_dono() -> None:
    ouvidos = Ouvidos(com_fone=False)
    escuta = ouvidos.escuta(Transcritor({}))
    for _ in range(30):  # os dois canais ao mesmo tempo: a voz de quem liga no alto-falante
        escuta.quadro(QUEM_LIGA, ALTO)
        escuta.quadro(DONO, ALTO)
    for _ in range(25):
        escuta.quadro(QUEM_LIGA, MUDO)
        escuta.quadro(DONO, MUDO)
    assert len(ouvidos.quem_liga) == 1
    assert ouvidos.dono == [] and ouvidos.cortes == 0
    # Bem depois, o dono fala sozinho: aí corta.
    for _ in range(50):
        escuta.quadro(QUEM_LIGA, MUDO)
        escuta.quadro(DONO, MUDO)
    _falar(escuta, DONO, 20)
    assert ouvidos.cortes == 1 and len(ouvidos.dono) == 1


def test_com_fone_o_dono_por_cima_de_quem_liga_corta() -> None:
    ouvidos = Ouvidos(com_fone=True)
    escuta = ouvidos.escuta(Transcritor({}))
    for _ in range(30):
        escuta.quadro(QUEM_LIGA, ALTO)
        escuta.quadro(DONO, ALTO)
    assert ouvidos.cortes == 1


def test_trecho_longo_e_transcrito_sem_esperar_a_pausa() -> None:
    ouvidos = Ouvidos(com_fone=True)
    transcritor = Transcritor({})
    escuta = ouvidos.escuta(transcritor)
    for _ in range(800):  # 16 s sem parar
        escuta.quadro(QUEM_LIGA, ALTO)
    assert transcritor.vistos and transcritor.vistos[0] == 750


# --- a voz na fonte virtual ---------------------------------------------------------------------
@dataclass
class TocadorFalso:
    tocados: list[tuple[str, int]] = field(default_factory=list)
    paradas: int = 0
    grafo: GrafoComSaida | None = None
    mudo_durante: list[bool] = field(default_factory=list)

    def tocar(self, pcm: bytes, dispositivo: str) -> None:
        self.tocados.append((dispositivo, len(pcm)))
        if self.grafo is not None:
            self.mudo_durante.append(self.grafo.mudos.get(77, False))

    def parar(self) -> None:
        self.paradas += 1


class Sintetizador:
    def sintetizar(self, texto: str) -> bytes:
        return silencio(100)


def _saida(fone: str, *, ligado: bool = True) -> tuple[SaidaNaFonteVirtual, TocadorFalso]:
    grafo = GrafoComSaida()
    misturador = Misturador(executor=grafo, pid_do_jarvis=PID_DO_JARVIS)
    if ligado:
        misturador.ligar()
    tocador = TocadorFalso(grafo=grafo)
    saida = SaidaNaFonteVirtual(
        sintetizador=Sintetizador(),
        tocador=tocador,
        misturador=misturador,
        politica=lambda: politica_de_eco(fone, None),
        saida_do_dono=lambda: "alsa_output.fone",
    )
    return saida, tocador


def test_sem_fone_toca_so_na_mistura_com_o_mic_mudo_durante() -> None:
    saida, tocador = _saida("nao")
    saida.falar("Olá, aqui é o assistente virtual.")
    assert tocador.tocados == [(NOME_DO_MIX, len(silencio(100)))]
    assert tocador.mudo_durante == [True]
    assert tocador.grafo is not None and tocador.grafo.mudos == {77: False}, "o mic volta"


def test_com_fone_toca_na_mistura_e_no_fone_sem_abafar() -> None:
    saida, tocador = _saida("sim")
    saida.falar("oi")
    assert sorted(d for d, _ in tocador.tocados) == ["alsa_output.fone", NOME_DO_MIX]
    assert tocador.mudo_durante == [False, False]


def test_sem_a_mistura_ligada_a_voz_nao_sai_e_o_agente_sabe() -> None:
    saida, tocador = _saida("nao", ligado=False)
    with pytest.raises(VozNaoSaiu):
        saida.falar("oi")
    assert tocador.tocados == []
    saida.interromper()
    assert tocador.paradas == 1


# --- o outro lado, sozinho ----------------------------------------------------------------------
class GrafoComApps(GrafoComSaida):
    """Mais dois fluxos tocando: o navegador com a chamada e um player de música."""

    def __init__(self) -> None:
        super().__init__()
        self.tocando: dict[int, dict[str, Any]] = {
            31: {"index": 31, "sink": 1, "properties": {"application.process.binary": "chromium"}},
            32: {"index": 32, "sink": 1, "properties": {"application.process.binary": "spotify"}},
        }

    def rodar(self, argv: Sequence[str]) -> Saida:
        args = tuple(argv)[1:]
        if args == ("-f", "json", "list", "sink-inputs"):
            # Os fluxos dos apps e, com o misturador ligado, o do loopback do microfone.
            do_misturador = json.loads(super().rodar(argv).texto or "[]")
            return Saida(0, json.dumps([*self.tocando.values(), *do_misturador]))
        if args == ("-f", "json", "list", "sinks"):
            self.comandos.append(tuple(argv))
            return Saida(0, json.dumps([{"index": 1, "name": "alsa_output.pci"}]))
        if args[:1] == ("move-sink-input",):
            self.comandos.append(tuple(argv))
            self.tocando[int(args[1])]["sink_nome"] = args[2]
            return Saida(0)
        return super().rodar(argv)


def test_captura_isola_so_o_fluxo_do_app_e_devolve_no_fim() -> None:
    grafo = GrafoComApps()
    captura = CapturaDoOutroLado(grafo)
    assert captura.ligar(por_app("chromium")) == FONTE_DO_OUTRO_LADO
    assert grafo.tocando[31]["sink_nome"] == NOME_DO_SINK
    assert "sink_nome" not in grafo.tocando[32], "a música do dono fica onde estava"
    carregados = [c[2:] for c in grafo.comandos if c[1:2] == ("load-module",)]
    assert carregados[1][:3] == (
        "module-loopback",
        f"source={FONTE_DO_OUTRO_LADO}",
        "sink=alsa_output.pci",
    ), "o dono continua ouvindo quem liga onde ouvia"
    captura.desligar()
    assert grafo.tocando[31]["sink_nome"] == "alsa_output.pci"
    assert not captura.ligado and grafo.modulos == {}


def test_sem_o_app_tocando_nada_e_criado() -> None:
    grafo = GrafoComApps()
    with pytest.raises(ErroDoMisturador):
        CapturaDoOutroLado(grafo).ligar(por_app("discord"))
    assert grafo.modulos == {}


# --- a sessão inteira ---------------------------------------------------------------------------
@dataclass
class GravadorFalso:
    quadros_: list[bytes]
    fechado: bool = False
    dispositivos: list[str] = field(default_factory=list)

    def quadros(self, dispositivo: str) -> Iterator[bytes]:
        self.dispositivos.append(dispositivo)
        yield from self.quadros_

    def fechar(self) -> None:
        self.fechado = True


def test_sessao_liga_grava_os_dois_canais_e_desfaz_tudo() -> None:
    grafo = GrafoComApps()
    misturador = Misturador(executor=grafo, pid_do_jarvis=PID_DO_JARVIS)
    ouvidos = Ouvidos(com_fone=True)
    remoto = GravadorFalso([ALTO] * 30 + [MUDO] * 25)
    local = GravadorFalso([MUDO] * 5)
    sessao = SessaoDeAudio(
        misturador=misturador,
        captura=CapturaDoOutroLado(grafo),
        gravador_de_quem_liga=remoto,
        gravador_do_dono=local,
        # 30 quadros de fala + o fim de fala que o VAD segura (histerese): 49 no trecho.
        escuta=ouvidos.escuta(Transcritor({49: "alô, o Marcos está?"})),
    )
    sessao.comecar(por_app("chromium"))
    for linha in sessao._linhas:
        linha.join(timeout=5)
    assert ouvidos.quem_liga == ["alô, o Marcos está?"]
    assert remoto.dispositivos == [FONTE_DO_OUTRO_LADO]
    assert local.dispositivos == [misturador.fisico], "o dono pelo microfone REAL"
    sessao.encerrar()
    assert remoto.fechado and local.fechado and not misturador.ligado
    assert grafo.modulos == {}


def test_sessao_que_falha_ao_ligar_desfaz_o_misturador() -> None:
    grafo = GrafoComApps()
    misturador = Misturador(executor=grafo, pid_do_jarvis=PID_DO_JARVIS)
    sessao = SessaoDeAudio(
        misturador=misturador,
        captura=CapturaDoOutroLado(grafo),
        gravador_de_quem_liga=GravadorFalso([]),
        gravador_do_dono=GravadorFalso([]),
        escuta=Ouvidos().escuta(Transcritor({})),
    )
    with pytest.raises(ErroDoMisturador):
        sessao.comecar(por_app("discord"))
    assert not misturador.ligado and grafo.modulos == {}


def test_por_app_casa_binario_ou_nome() -> None:
    casa: Callable[[Mapping[str, Any]], bool] = por_app("Chromium", "WhatsApp")
    assert casa({"application.process.binary": "chromium"})
    assert casa({"application.name": "whatsapp"})
    assert not casa({"application.process.binary": "spotify"})


def test_gravar_e_tocar_de_verdade_recusam_sob_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    from jarvis.audio_io.erros import DispositivoProibidoEmCI
    from jarvis.audio_io.pulse import GravadorPorParec, TocadorPorPacat

    monkeypatch.setenv("CI", "1")
    with pytest.raises(DispositivoProibidoEmCI):
        next(GravadorPorParec().quadros("jarvis_outro_lado.monitor"))
    with pytest.raises(DispositivoProibidoEmCI):
        TocadorPorPacat().tocar(b"\x00\x00", NOME_DO_MIX)


def test_voz_que_nao_sai_vira_veredito_ao_agente(tmp_path: Any) -> None:
    from jarvis.chamada.agente import FALAR
    from tests.unit.chamada.test_agente import AVISO, Mundo, por_rodada

    mundo = Mundo(tmp_path, por_rodada([AVISO]))
    saida, _ = _saida("nao", ligado=False)
    mundo.agente.saida = saida
    resultado = mundo.agente.nova_chamada("Bruno").ouvir("alô")
    (feito,) = resultado.feitos
    assert feito.ferramenta == FALAR and not feito.aceita
    assert "a voz não saiu" in feito.veredito and resultado.falas == []
