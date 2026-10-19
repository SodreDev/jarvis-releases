"""O aplicativo continua cancelável enquanto síntese e geração estão bloqueadas."""

from __future__ import annotations

import threading
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.agentd.tts import MAXIMO_DE_SINTESES_PENDENTES, MotorParametrico
from jarvis.audio_io.playback import FilaDePlayback, Pedaco
from jarvis.audio_io.sumidouros import SumidouroEmMemoria
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import Contexto, Delta, Modo, Texto
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao
from jarvis.voz.interface import Cancelado
from jarvis.voz.teclado import ESPACO


@dataclass
class MotorEmEspera(MotorParametrico):
    iniciou: threading.Event = field(default_factory=threading.Event)
    liberar: threading.Event = field(default_factory=threading.Event)
    _mudou: threading.Condition = field(default_factory=threading.Condition)
    iniciadas: int = 0
    concluidas: int = 0

    def sintetizar(self, texto: str) -> bytes:
        with self._mudou:
            self.iniciadas += 1
            self.iniciou.set()
        assert self.liberar.wait(timeout=2), "o teste não liberou a síntese"
        with self._mudou:
            self.concluidas += 1
            self._mudou.notify_all()
        return b"\x01\x00" * 640

    def esperar_fim(self) -> bool:
        with self._mudou:
            return self._mudou.wait_for(lambda: self.concluidas == self.iniciadas, timeout=2)


@dataclass
class TecladoCondicionado:
    pode_interromper: Callable[[], bool]
    leituras: list[int] = field(default_factory=list)
    interrompeu: bool = False

    def tecla(self) -> str | None:
        self.leituras.append(threading.get_ident())
        if self.pode_interromper() and not self.interrompeu:
            self.interrompeu = True
            return ESPACO
        return None


@dataclass
class MotorLongo(MotorRoteirizado):
    geradas: int = 0
    fechou: threading.Event = field(default_factory=threading.Event)

    def gerar(
        self, contexto: Contexto, modo: Modo, cancelado: Cancelado
    ) -> Generator[Delta, None, None]:
        try:
            for _ in range(100):
                if cancelado():
                    return
                self.geradas += 1
                yield Texto(" ".join(f"palavra{i}" for i in range(18)) + " ")
        finally:
            self.fechou.set()


def _app(tmp_path: Path, tts: MotorEmEspera, teclado: TecladoCondicionado) -> Aplicativo:
    app = Aplicativo(
        configuracao=Configuracao(tts="tts-parametrico", s2="eco"),
        raiz=tmp_path,
        escrever_na_tela=lambda _: None,
        teclado=teclado,
        ambiente={"CI": "1", "JARVIS_AUDIO_BACKEND": "arquivo"},
    )
    app._tts = tts
    app._motor = MotorRoteirizado(resposta="Uma resposta curta.")
    app._cerebro = Cerebro(motor=app._motor, session_id=app.session_id)
    return app


def test_barra_cancela_sintese_em_voo_antes_do_primeiro_audio_na_linha_do_player(
    tmp_path: Path,
) -> None:
    tts = MotorEmEspera()
    teclado = TecladoCondicionado(tts.iniciou.is_set)
    app = _app(tmp_path, tts, teclado)
    saida = SumidouroEmMemoria()
    fila = FilaDePlayback(sumidouro=saida, session_id=app.session_id)
    assert fila.enfileirar(Pedaco(chunk_id="pendente", epoch=app.epoch, amostras=b"\x01\x00" * 640))

    try:
        turno = app.responder("oi", fila=fila)
        assert teclado.interrompeu
        assert turno.cancelado
        assert turno.amostras_tocadas == 0
        assert saida.amostras_consumidas == 0
        assert fila.pedacos_na_fila == 0
        assert set(teclado.leituras) == {threading.get_ident()}
    finally:
        tts.liberar.set()
    assert tts.esperar_fim()
    assert saida.amostras_consumidas == 0, "resultado tardio não pode tocar"


def test_recusa_por_epoch_da_fila_interrompe_o_pipeline_e_o_turno(tmp_path: Path) -> None:
    tts = MotorEmEspera()
    tts.liberar.set()
    app = _app(tmp_path, tts, TecladoCondicionado(lambda: False))
    motor = MotorLongo()
    app._motor = motor
    saida = SumidouroEmMemoria()
    fila = FilaDePlayback(sumidouro=saida, session_id=app.session_id, epoch_atual=app.epoch + 1)

    turno = app.responder("oi", fila=fila)

    assert turno.cancelado
    assert turno.amostras_tocadas == 0
    assert saida.amostras_consumidas == 0
    assert fila.descartados_por_epoch == 1
    assert motor.fechou.wait(timeout=2), "recusa da fila deixou a geração presa no put"
    assert motor.geradas < 100
    assert tts.esperar_fim()


def test_epoch_desbloqueia_publicacao_quando_a_fila_do_cerebro_esta_cheia(tmp_path: Path) -> None:
    motor = MotorLongo()
    exibidos: list[str] = []
    # Três sínteses + três ResponseChunks na fila. O sétimo está preso em publicar().
    limite = 2 * MAXIMO_DE_SINTESES_PENDENTES
    teclado = TecladoCondicionado(lambda: motor.geradas == limite + 1 and len(exibidos) == limite)
    tts = MotorEmEspera()
    app = _app(tmp_path, tts, teclado)
    app._motor = motor
    app.ao_pedaco = exibidos.append

    try:
        turno = app.responder("conte tudo")
        assert teclado.interrompeu
        assert turno.cancelado
        assert turno.amostras_tocadas == 0
        assert motor.fechou.wait(timeout=2), "geração presa no put não acordou no epoch"
        assert motor.geradas == limite + 1
        assert len(exibidos) == limite
        assert set(teclado.leituras) == {threading.get_ident()}
    finally:
        tts.liberar.set()
    assert tts.esperar_fim()
