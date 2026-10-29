"""O aplicativo continua cancelável enquanto síntese e geração estão bloqueadas.

E a geração não espera a fala: a janela de síntese (3 lotes à frente) limita o trabalho do TTS,
nunca o cérebro lendo o motor — senão a tela segue o alto-falante e o prazo total do motor corta
a resposta longa (revisão de 7507cd5, 2026-10-19).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.agentd.tts import MotorParametrico
from jarvis.audio_io.playback import FilaDePlayback, Pedaco
from jarvis.audio_io.sumidouros import SumidouroEmMemoria
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import Contexto, Delta, Fim, Modo, MotivoDoFim, Texto
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
    espera_o_cancelamento_depois_de: int = 0
    """> 0: depois de tantos deltas o motor espera o turno ser cancelado (até 2 s) antes de seguir.
    Prova que quem parou a geração foi o cancelamento, e não o texto que acabou."""
    ponto: str = ""
    """"." faz de cada delta uma frase inteira: a voz a recebe assim que ela fecha. Sem ponto, a
    frase de 18 palavras só sai no teto de segurança da fala (120 palavras, 2026-10-29)."""

    def gerar(
        self, contexto: Contexto, modo: Modo, cancelado: Cancelado
    ) -> Generator[Delta, None, None]:
        try:
            for _ in range(100):
                if self.geradas == self.espera_o_cancelamento_depois_de > 0:
                    fim = time.monotonic() + 2
                    while not cancelado() and time.monotonic() < fim:
                        time.sleep(0.005)
                if cancelado():
                    return
                self.geradas += 1
                yield Texto(" ".join(f"palavra{i}" for i in range(18)) + self.ponto + " ")
        finally:
            self.fechou.set()


@dataclass
class MotorComPrazo(MotorRoteirizado):
    """Como o `claude -p` (`MotorClaudeCli._ler`): o prazo é **total** e é conferido a cada
    `next()`. Se quem lê demora — o cérebro preso esperando a fala —, o próximo `next()` já passou
    do prazo e a resposta sai cortada."""

    prazo_s: float = 1.0
    deltas: int = 40
    fechou: threading.Event = field(default_factory=threading.Event)

    def gerar(
        self, contexto: Contexto, modo: Modo, cancelado: Cancelado
    ) -> Generator[Delta, None, None]:
        limite = time.monotonic() + self.prazo_s
        try:
            for i in range(self.deltas):
                if cancelado():
                    return
                if time.monotonic() > limite:
                    yield Fim(MotivoDoFim.PRAZO, f"passou de {self.prazo_s:.0f}s")
                    return
                yield Texto(" ".join(f"p{i}_{j}" for j in range(18)) + " ")
            yield Fim(MotivoDoFim.CONCLUIDO)
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
    motor = MotorLongo(espera_o_cancelamento_depois_de=6, ponto=".")
    app._motor = motor
    saida = SumidouroEmMemoria()
    fila = FilaDePlayback(sumidouro=saida, session_id=app.session_id, epoch_atual=app.epoch + 1)

    turno = app.responder("oi", fila=fila)

    assert turno.cancelado
    assert turno.amostras_tocadas == 0
    assert saida.amostras_consumidas == 0
    assert fila.descartados_por_epoch == 1
    assert motor.fechou.wait(timeout=2), "recusa da fila não encerrou a geração"
    assert motor.geradas == 6, "quem parou a geração foi a recusa, não o fim do texto"
    assert tts.esperar_fim()


def test_com_a_sintese_presa_o_cerebro_le_o_motor_ate_o_fim_e_a_barra_ainda_cancela(
    tmp_path: Path,
) -> None:
    """Sem contrapressão no texto: o TTS preso não prende a geração (a tela e o prazo do motor
    seguem o motor, não a fala), e a barra continua cancelando na linha do player."""
    motor = MotorLongo()
    exibidos: list[str] = []
    teclado = TecladoCondicionado(motor.fechou.is_set)
    tts = MotorEmEspera()
    app = _app(tmp_path, tts, teclado)
    app._motor = motor
    app.ao_pedaco = exibidos.append

    try:
        turno = app.responder("conte tudo")
        assert teclado.interrompeu
        assert turno.cancelado
        assert turno.amostras_tocadas == 0
        assert motor.geradas == 100, "a síntese presa segurou a geração"
        assert exibidos and exibidos[-1].endswith("palavra17")
        assert set(teclado.leituras) == {threading.get_ident()}
    finally:
        tts.liberar.set()
    assert tts.esperar_fim()


def test_resposta_longa_com_a_fala_atrasada_nao_estoura_o_prazo_do_motor(tmp_path: Path) -> None:
    """A síntese só anda quando a geração acabou. Com a fila do cérebro limitada a 3 (7507cd5), o
    cérebro parava no 7º lote, o motor nunca terminava e o prazo dele cortava a resposta."""
    motor = MotorComPrazo()
    tts = MotorEmEspera(liberar=motor.fechou)
    telas: list[str] = []
    app = Aplicativo(
        configuracao=Configuracao(tts="tts-parametrico", s2="eco"),
        raiz=tmp_path,
        escrever_na_tela=telas.append,
        teclado=TecladoCondicionado(lambda: False),
        ambiente={"CI": "1", "JARVIS_AUDIO_BACKEND": "arquivo"},
    )
    app._tts = tts
    app._motor = motor
    app._cerebro = Cerebro(motor=motor, session_id=app.session_id)
    fila = FilaDePlayback(sumidouro=SumidouroEmMemoria(), session_id=app.session_id)

    turno = app.responder("conte uma história comprida", fila=fila)

    assert not [t for t in telas if "sem resposta" in t], telas
    assert not turno.cancelado
    assert turno.respondeu.endswith(f"p{motor.deltas - 1}_17")
    assert tts.esperar_fim()
