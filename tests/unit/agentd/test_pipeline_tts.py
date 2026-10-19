"""Pipeline antecipado do TTS: concorrência limitada, ordem e cancelamento por epoch."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

from jarvis.agentd.fala_em_stream import StreamForaDeOrdem, falar_stream_para
from jarvis.agentd.tts import (
    MAXIMO_DE_SINTESES_PENDENTES,
    SintetizadorEmStreaming,
    Trecho,
    falar_para,
)
from jarvis.audio_io.playback import Pedaco
from jarvis.voz.interface import Onde, cancelado_por_epoch


@dataclass
class MotorControlado:
    """Sintetizador falso cujas chamadas o teste pode observar e liberar."""

    bloqueio_padrao: threading.Event | None = None
    bloqueios: dict[str, threading.Event] = field(default_factory=dict)
    primeiro_espera: int = 0
    nome: str = "tts-controlado"
    voz: str = "teste"
    licenca: str = "MIT"
    onde: Onde = Onde.LOCAL
    iniciadas: list[str] = field(default_factory=list)
    concluidas: list[str] = field(default_factory=list)
    _mudou: threading.Condition = field(default_factory=threading.Condition, repr=False)

    def sintetizar(self, texto: str) -> bytes:
        with self._mudou:
            self.iniciadas.append(texto)
            self._mudou.notify_all()
            if texto == "lote-1" and self.primeiro_espera:
                pronto = self._mudou.wait_for(
                    lambda: len(self.iniciadas) >= self.primeiro_espera, timeout=2
                )
                if not pronto:
                    raise AssertionError("as sínteses futuras não começaram")
        bloqueio = self.bloqueios.get(texto, self.bloqueio_padrao)
        if bloqueio is not None and not bloqueio.wait(timeout=2):
            raise AssertionError(f"o teste não liberou {texto}")
        with self._mudou:
            self.concluidas.append(texto)
            self._mudou.notify_all()
        numero = (
            int(texto.removeprefix("lote-")) if texto.startswith("lote-") else len(texto.split())
        )
        return numero.to_bytes(2, "little")

    def esperar_iniciadas(self, quantidade: int) -> bool:
        with self._mudou:
            return self._mudou.wait_for(lambda: len(self.iniciadas) >= quantidade, timeout=2)

    def esperar_conclusao(self, texto: str) -> bool:
        with self._mudou:
            return self._mudou.wait_for(lambda: texto in self.concluidas, timeout=2)

    def esperar_concluidas(self, quantidade: int) -> bool:
        with self._mudou:
            return self._mudou.wait_for(lambda: len(self.concluidas) >= quantidade, timeout=2)


@dataclass
class FilaFalsa:
    pendentes: deque[Pedaco] = field(default_factory=deque)

    def enfileirar(self, pedaco: Pedaco) -> bool:
        self.pendentes.append(pedaco)
        return True


@dataclass
class PlayerFalso:
    motor: MotorControlado
    liberar_segundo: threading.Event
    tocados: list[str] = field(default_factory=list)

    def tocar_proximo(self, fila: FilaFalsa) -> None:
        pedaco = fila.pendentes.popleft()
        if not self.tocados:
            assert self.motor.esperar_iniciadas(3)
            assert {"lote-2", "lote-3"} <= set(self.motor.iniciadas)
            assert self.motor.esperar_conclusao("lote-3")
            # N+1 ainda está em voo e N+2 já terminou antes de o áudio N terminar.
            self.liberar_segundo.set()
        self.tocados.append(pedaco.chunk_id)


def _trechos(quantidade: int) -> list[tuple[int, str]]:
    return [(indice * 10, f"lote-{indice + 1}") for indice in range(quantidade)]


def test_duas_sinteses_futuras_comecam_antes_do_audio_atual_terminar_e_tocam_em_ordem() -> None:
    liberar_segundo = threading.Event()
    motor = MotorControlado(
        bloqueios={"lote-2": liberar_segundo},
        primeiro_espera=3,
    )
    sintetizador = SintetizadorEmStreaming(motor=motor, epoch=7)
    fila = FilaFalsa()
    player = PlayerFalso(motor=motor, liberar_segundo=liberar_segundo)

    mapa: list[Trecho] = []
    audios: list[int] = []
    for pedaco, trecho in sintetizador.pedacos_do_stream(_trechos(4), chunk_id="fala"):
        assert fila.enfileirar(pedaco)
        player.tocar_proximo(fila)
        mapa.append(trecho)
        audios.append(int.from_bytes(pedaco.amostras, "little"))

    assert player.tocados == ["fala-1", "fala-2", "fala-3", "fala-4"]
    assert fila.pendentes == deque()
    assert audios == [1, 2, 3, 4]
    assert [t.inicio_no_texto for t in mapa] == [0, 10, 20, 30]
    assert [t.inicio_em_amostras for t in mapa] == [0, 1, 2, 3]


def test_backpressure_limita_as_sinteses_pendentes() -> None:
    liberar = threading.Event()
    motor = MotorControlado(bloqueio_padrao=liberar)
    sintetizador = SintetizadorEmStreaming(motor=motor)
    resultado: list[tuple[Pedaco, object]] = []
    erros: list[BaseException] = []

    def consumir() -> None:
        try:
            resultado.extend(sintetizador.pedacos_do_stream(_trechos(8)))
        except BaseException as erro:  # pragma: no cover - a asserção abaixo mostra a causa
            erros.append(erro)

    consumidor = threading.Thread(target=consumir, daemon=True)
    consumidor.start()

    assert motor.esperar_iniciadas(MAXIMO_DE_SINTESES_PENDENTES)
    assert len(motor.iniciadas) == MAXIMO_DE_SINTESES_PENDENTES
    liberar.set()
    consumidor.join(timeout=2)

    assert not consumidor.is_alive()
    assert erros == []
    assert len(resultado) == 8
    assert [pedaco.chunk_id for pedaco, _ in resultado] == [f"tts-{i}" for i in range(1, 9)]


def test_avanco_do_epoch_cancela_geracao_e_nao_deixa_audio_tardio_na_fila() -> None:
    liberar = threading.Event()
    motor = MotorControlado(bloqueio_padrao=liberar)
    epoch = {"atual": 4}
    sintetizador = SintetizadorEmStreaming(
        motor=motor,
        epoch=4,
        cancelado=cancelado_por_epoch(lambda: epoch["atual"], 4),
    )
    enfileirados: list[Pedaco] = []
    resultado = []

    def enfileirar(pedaco: Pedaco) -> bool:
        enfileirados.append(pedaco)
        return True

    def falar() -> None:
        texto = " ".join(f"palavra{i}" for i in range(72))
        resultado.append(falar_para(sintetizador, texto, enfileirar))

    consumidor = threading.Thread(target=falar, daemon=True)
    consumidor.start()
    assert motor.esperar_iniciadas(MAXIMO_DE_SINTESES_PENDENTES)

    epoch["atual"] = 5
    consumidor.join(timeout=2)

    assert not consumidor.is_alive()
    assert enfileirados == []
    assert resultado[0].cancelada_em == 0

    liberar.set()
    assert motor.esperar_concluidas(MAXIMO_DE_SINTESES_PENDENTES)
    assert enfileirados == [], "síntese terminada depois do epoch não pode chegar à fila"


def test_player_parado_limita_resultados_prontos_e_fecha_a_entrada_ao_sair() -> None:
    fechou = threading.Event()
    consumidos: list[str] = []

    def entrada() -> Iterator[tuple[int, str]]:
        try:
            for trecho in _trechos(100):
                consumidos.append(trecho[1])
                yield trecho
        finally:
            fechou.set()

    # Mantém uma referência viva: o fechamento não pode depender do coletor de lixo.
    trechos = entrada()
    motor = MotorControlado()
    fluxo = SintetizadorEmStreaming(motor=motor).pedacos_do_stream(trechos)
    try:
        assert next(fluxo)[0].chunk_id == "tts-1"
        # Com o consumidor suspenso, apenas a janela futura pode ficar pronta.
        assert motor.esperar_concluidas(1 + MAXIMO_DE_SINTESES_PENDENTES)
    finally:
        fluxo.close()  # type: ignore[attr-defined]

    assert fechou.wait(timeout=2)
    assert len(consumidos) == 1 + MAXIMO_DE_SINTESES_PENDENTES
    assert len(motor.iniciadas) == len(consumidos)


def test_epoch_cancela_tambem_a_leitura_bloqueada_no_backpressure() -> None:
    liberar = threading.Event()
    fechou = threading.Event()
    epoch = {"atual": 4}
    consumidos: list[str] = []

    def entrada() -> Iterator[tuple[int, str]]:
        try:
            for trecho in _trechos(100):
                consumidos.append(trecho[1])
                yield trecho
        finally:
            fechou.set()

    motor = MotorControlado(bloqueio_padrao=liberar)
    trechos = entrada()
    sintese = SintetizadorEmStreaming(
        motor=motor, epoch=4, cancelado=cancelado_por_epoch(lambda: epoch["atual"], 4)
    )
    resultado: list[tuple[Pedaco, Trecho]] = []
    consumidor = threading.Thread(
        target=lambda: resultado.extend(sintese.pedacos_do_stream(trechos)), daemon=True
    )
    consumidor.start()
    try:
        assert motor.esperar_iniciadas(MAXIMO_DE_SINTESES_PENDENTES)
        epoch["atual"] = 5
        consumidor.join(timeout=2)
        assert not consumidor.is_alive()
        assert fechou.wait(timeout=2)
        assert len(consumidos) == MAXIMO_DE_SINTESES_PENDENTES
        assert resultado == []
    finally:
        epoch["atual"] = 5
        liberar.set()
        consumidor.join(timeout=2)
    assert motor.esperar_concluidas(MAXIMO_DE_SINTESES_PENDENTES)


def test_entrada_bloqueada_nao_inicia_sintese_depois_de_fechar_o_pipeline() -> None:
    entrou = threading.Event()
    liberar = threading.Event()
    fechou = threading.Event()
    epoch = {"atual": 0}

    def entrada() -> Iterator[tuple[int, str]]:
        try:
            entrou.set()
            assert liberar.wait(timeout=2)
            yield 0, "lote-1"
        finally:
            fechou.set()

    motor = MotorControlado()
    sintese = SintetizadorEmStreaming(
        motor=motor, cancelado=cancelado_por_epoch(lambda: epoch["atual"], 0)
    )
    trechos = entrada()
    resultado: list[tuple[Pedaco, Trecho]] = []
    consumidor = threading.Thread(
        target=lambda: resultado.extend(sintese.pedacos_do_stream(trechos)), daemon=True
    )
    consumidor.start()
    try:
        assert entrou.wait(timeout=2)
        epoch["atual"] = 1
        consumidor.join(timeout=2)
        assert not consumidor.is_alive(), "não pode esperar uma fonte externa para cancelar"
    finally:
        epoch["atual"] = 1
        liberar.set()
        consumidor.join(timeout=2)
    assert fechou.wait(timeout=2)
    assert motor.iniciadas == []
    assert resultado == []


def test_primeira_recusa_do_playback_fecha_o_stream_e_nao_publica_mais_audio() -> None:
    fechou = threading.Event()

    def entrada() -> Iterator[dict[str, object]]:
        try:
            for seq in range(100):
                yield {
                    "epoch": 0,
                    "response_id": "r",
                    "seq": seq,
                    "text": f"lote-{seq + 1}",
                    "last": False,
                }
        finally:
            fechou.set()

    pedacos = entrada()
    entregues: list[Pedaco] = []

    def recusar(pedaco: Pedaco) -> bool:
        entregues.append(pedaco)
        return False

    fala = falar_stream_para(SintetizadorEmStreaming(motor=MotorControlado()), pedacos, recusar)

    assert fechou.wait(timeout=2)
    assert len(entregues) == 1
    assert fala.cancelada_em == 0
    assert fala.pedacos == ()


def test_erro_de_ordem_no_produtor_chega_ao_consumidor() -> None:
    pedacos = [
        {"epoch": 0, "response_id": "r", "seq": seq, "text": "lote-1", "last": False}
        for seq in (0, 2)
    ]
    with pytest.raises(StreamForaDeOrdem, match="esperava seq 1"):
        falar_stream_para(SintetizadorEmStreaming(motor=MotorControlado()), pedacos, lambda _: True)


def test_falha_ao_abrir_iterador_nao_deixa_o_consumidor_esperando() -> None:
    class EntradaComFalha:
        def __iter__(self) -> Iterator[tuple[int, str]]:
            raise ValueError("não abriu a entrada")

    sintese = SintetizadorEmStreaming(motor=MotorControlado())
    with pytest.raises(ValueError, match="não abriu a entrada"):
        list(sintese.pedacos_do_stream(EntradaComFalha()))


@pytest.mark.parametrize("erro", [ValueError("provider falhou"), TimeoutError("provider expirou")])
def test_falha_do_provider_inclusive_timeout_e_propagada(erro: Exception) -> None:
    class MotorComFalha(MotorControlado):
        def sintetizar(self, texto: str) -> bytes:
            raise erro

    with pytest.raises(type(erro), match=str(erro)):
        list(SintetizadorEmStreaming(motor=MotorComFalha()).pedacos_do_stream(_trechos(1)))
