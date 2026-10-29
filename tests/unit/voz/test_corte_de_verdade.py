"""Cortar é cancelar de verdade (dono, 2026-10-29): nada do turno cortado volta a tocar.

O relato: «quando eu interrompo falando, o Jarvis para de falar, mas DEPOIS o TTS volta a tocar
sozinho do nada, não deixa cortar de novo, e não escuta pedido novo até a resposta antiga acabar».
A trilha dele (29/10, só códigos) mostrou a causa na escuta contínua: a vigia **pausava**, não
tinha regra para cortar (sem palavra, sem ordem de parar, sem o detector ligado), retomava no
prazo da pausa (`prazo_da_pausa`, 2,5 s) e marcava o resto da fala dele como «contida» — o pedido
sumia e a resposta velha seguia até o fim. E, nos dois modos, o aviso cortado (a resposta de uma
tarefa) **voltava para a fila**: era falado de novo no piso livre ou ia na frente do pedido novo.

Laço de áudio de verdade (`rodar_audio`), áudio sintético num WAV, ASR falso, TTS paramétrico e o
motor roteirizado — nenhum microfone, nenhum alto-falante, nenhuma rede.
"""

from __future__ import annotations

import json
import threading
import time
import wave
from collections.abc import Callable, Generator, Sequence
from pathlib import Path
from random import Random
from typing import Any

from jarvis.agentd.fila_de_avisos import ORIGEM_DO_PEDIDO, Entrega, notificacao
from jarvis.audio_io.quadro import TAXA_PADRAO
from jarvis.audio_io.sintese import fala_simulada, silencio
from jarvis.executor.desfazer import Contaminacao
from jarvis.relogio import RelogioFalso
from jarvis.s2.motor import Contexto, Delta, Fim, Modo, MotivoDoFim, Texto
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.tarefas.gestor import EstadoDaTarefa, FimDaTarefa, Tarefa
from jarvis.voz.app import Aplicativo
from jarvis.voz.config import Configuracao
from jarvis.voz.estado import Estado
from jarvis.voz.interface import Cancelado, Hipotese, Onde
from jarvis.voz.interrupcao import VigiaDeInterrupcao, em_linha

LONGA = (
    "Era uma vez um reino muito distante, onde as montanhas tocavam as nuvens e os rios corriam "
    "devagar entre as pedras antigas. Lá vivia uma inventora que construía máquinas de vento, "
    "relógios de água e lanternas que acendiam sozinhas quando a noite chegava sem avisar ninguém. "
    "Todos os dias ela subia a colina mais alta para medir o tempo e anotar o caminho das aves."
)


def _fala(ms: float, semente: int) -> bytes:
    return fala_simulada(ms, aleatorio=Random(semente), pico=0.5, f0_hz=180.0)


class AsrRoteirizado:
    """O ASR da sessão: devolve o roteiro na ordem (o último se repete). A vigia e o turno novo
    leem o mesmo trecho, então o que o dono diz por cima aparece duas vezes seguidas."""

    nome = "asr-falso"
    modelo = "(nenhum)"
    licenca = "Apache-2.0"
    idioma = "pt-BR"
    onde = Onde.LOCAL

    def __init__(self, *textos: str) -> None:
        self.textos = textos
        self.chamadas = 0

    def transcrever(self, amostras: bytes) -> Hipotese:
        del amostras
        self.chamadas += 1
        return Hipotese(self.textos[min(self.chamadas, len(self.textos)) - 1], 1.0)


def _respostas(*textos: str) -> Callable[[object], str]:
    vez = [0]

    def responder(_contexto: object) -> str:
        vez[0] += 1
        return textos[min(vez[0], len(textos)) - 1]

    return responder


def _wav(caminho: Path, *trechos: bytes) -> Path:
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(TAXA_PADRAO)
        arquivo.writeframes(b"".join(trechos))
    return caminho


def _amostras_tocadas(caminho: Path | None) -> int:
    """O que de fato saiu no "alto-falante" (o WAV de saída), em amostras."""
    if caminho is None or not caminho.exists():
        return 0
    with wave.open(str(caminho), "rb") as arquivo:
        return arquivo.getnframes()


def _aplicativo(
    tmp_path: Path,
    escuta: str,
    asr: AsrRoteirizado,
    motor: object,
    *entrada: bytes,
) -> tuple[Aplicativo, list[str], list[Estado]]:
    tela: list[str] = []
    estados: list[Estado] = []
    app = Aplicativo(
        configuracao=Configuracao(asr="asr-whisper-local", tts="tts-parametrico", escuta=escuta),
        raiz=tmp_path / "sessao",
        escrever_na_tela=tela.append,
        relogio=RelogioFalso(),
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        ao_mudar_estado=estados.append,
    )
    app._asr = asr
    app._motor = motor  # type: ignore[assignment]
    app.vigia = VigiaDeInterrupcao(
        transcrever=lambda amostras: asr.transcrever(amostras).texto, enviar=em_linha
    )
    app.caminho_de_entrada = _wav(tmp_path / "entrada.wav", *entrada)
    app.caminho_de_saida = tmp_path / "saida.wav"
    app.avisos.piso_livre_s = 0.0  # o teste não espera o 1,5 s de silêncio do D22
    return app, tela, estados


def _trilha(app: Aplicativo) -> list[dict[str, object]]:
    arquivo = app.raiz / "diagnostico" / "turnos.jsonl"
    return [json.loads(linha) for linha in arquivo.read_text(encoding="utf-8").splitlines()]


def _aviso_da_resposta(app: Aplicativo, texto: str = LONGA) -> str:
    """A resposta de uma tarefa do dono na fila, como `_aviso_da_tarefa` a põe (ADR-0038)."""
    identificador = "tarefa-t-historia"
    app._falas_dos_avisos[identificador] = texto
    app.receber_aviso(
        notificacao(
            app.session_id,
            identificador,
            tipo="concluida",
            origem=f"{ORIGEM_DO_PEDIDO}conta uma história",
            resumo=texto,
        )
    )
    return identificador


# --- a escuta contínua: a causa da trilha do dono ---------------------------------------------
def test_na_continua_falar_por_cima_corta_e_o_pedido_novo_e_atendido(tmp_path: Path) -> None:
    """Sem o detector, toda fala na contínua é com o Jarvis — com ele calado, vira pedido; por cima
    da fala dele, corta e vira pedido. Antes: pausava, retomava em 2,5 s e o pedido sumia."""
    asr = AsrRoteirizado("me conta uma história", "abre o spotify")
    motor = MotorRoteirizado(resposta=_respostas(LONGA, "Abri o Spotify."), nome="roteiro")
    app, _tela, _estados = _aplicativo(
        tmp_path,
        "vad",
        asr,
        motor,
        _fala(400, 5),
        silencio(3600),
        _fala(1000, 7),
        silencio(3000),
    )

    app.rodar_audio(limite_de_turnos=2)

    assert [t.falou for t in app.turnos] == ["me conta uma história", "abre o spotify"]
    historia, pedido = app.turnos
    assert historia.cancelado, "a história não foi cortada: o pedido por cima se perdeu"
    assert pedido.respondeu == "Abri o Spotify." and not pedido.cancelado
    decisoes = [(e["decisao"], e["motivo"]) for e in _trilha(app) if e["evento"] == "interrupcao"]
    assert ("cortar", "fala_do_dono") in decisoes, decisoes
    assert all(d != "retomar" for d, _m in decisoes), "retomou a história por cima do dono"
    # Nada volta a tocar: o que saiu no alto-falante é o pedaço da história e a resposta nova.
    assert _amostras_tocadas(app.caminho_de_saida) == historia.amostras_tocadas + (
        pedido.amostras_tocadas
    )


def test_na_continua_o_corte_e_a_fala_contida_nao_impedem_o_segundo_corte(
    tmp_path: Path,
) -> None:
    """Um trecho que não decidiu (ruído sem palavra) não marca a fala seguinte como «contida»: o
    dono fala por cima de novo e corta. Antes, o prazo da pausa retomava e o resto da fala dele não
    pausava nem perguntava mais nada — «não deixa cortar de novo»."""
    asr = AsrRoteirizado("me conta uma história", "", "abre o spotify")
    motor = MotorRoteirizado(resposta=_respostas(LONGA, "Abri o Spotify."), nome="roteiro")
    app, _tela, _estados = _aplicativo(
        tmp_path,
        "vad",
        asr,
        motor,
        _fala(400, 5),
        silencio(2600),
        _fala(600, 9),  # o primeiro trecho por cima: o ASR não ouve palavra (vazio)
        silencio(200),
        _fala(1000, 7),  # e o dono fala de novo, logo em seguida
        silencio(3000),
    )

    app.rodar_audio(limite_de_turnos=2)

    assert [t.falou for t in app.turnos] == ["me conta uma história", "abre o spotify"]
    assert app.turnos[0].cancelado and app.turnos[1].respondeu == "Abri o Spotify."


# --- o aviso cortado não volta (os dois modos) ------------------------------------------------
def test_o_aviso_cortado_nao_volta_a_tocar_no_piso_livre(tmp_path: Path) -> None:
    """A resposta de uma tarefa, cortada com «Jarvis, para», não é falada de novo quando o piso
    fica livre: o card guarda, a tela mostrou, a voz não repete."""
    asr = AsrRoteirizado("jarvis para")
    motor = MotorRoteirizado(resposta="isto não pode ser dito", nome="roteiro")
    app, tela, _estados = _aplicativo(
        tmp_path, "palavra", asr, motor, silencio(2000), _fala(800, 7), silencio(5000)
    )
    app.abrir()
    identificador = _aviso_da_resposta(app)

    app.rodar_audio()

    falas_do_jarvis = [t for t in app.turnos if not t.falou]
    assert len(falas_do_jarvis) == 1, "o aviso cortado voltou a tocar"
    assert falas_do_jarvis[0].amostras_tocadas > 0
    assert "  (parei)" in tela
    assert app.avisos.avisos[identificador].entrega is not Entrega.NA_FILA
    assert not app.avisos.avisos[identificador].pendente
    assert len(motor.pedidos) == 0, "«para» virou pedido ao motor"
    assert _amostras_tocadas(app.caminho_de_saida) == falas_do_jarvis[0].amostras_tocadas


def test_o_aviso_cortado_nao_vai_na_frente_do_pedido_novo(tmp_path: Path) -> None:
    """Cortado o aviso com um pedido novo, o pedido é respondido — sem a resposta velha antes."""
    asr = AsrRoteirizado("jarvis que horas são")
    motor = MotorRoteirizado(resposta="São três e meia.", nome="roteiro")
    app, _tela, _estados = _aplicativo(
        tmp_path, "palavra", asr, motor, silencio(2000), _fala(800, 7), silencio(4000)
    )
    app.abrir()
    _aviso_da_resposta(app)

    app.rodar_audio(limite_de_turnos=1)

    aviso, pedido = app.turnos
    assert not aviso.falou and pedido.falou == "que horas são"
    assert pedido.respondeu == "São três e meia.", "a resposta velha foi junto com o pedido novo"
    assert len(motor.pedidos) == 1
    assert "Antes desta resposta você já disse" not in motor.pedidos[0].sistema


# --- o cérebro do turno cortado não prende o laço -------------------------------------------
class MotorQueDemoraParaParar:
    """Um motor que fala, e cuja geração só nota o cancelamento depois de `teimosia_s` (uma
    ferramenta em voo, uma rede lenta): o laço não pode esperar por ele para voltar a ouvir."""

    nome = "teimoso"
    onde = Onde.LOCAL
    aceita_imagem = False

    def __init__(self, texto: str, depois: str, teimosia_s: float) -> None:
        self.texto, self.depois, self.teimosia_s = texto, depois, teimosia_s
        self.pedidos: list[Contexto] = []
        self.em_voo = threading.Event()
        self.ativos = 0
        self.maximo_de_ativos = 0
        self._trava = threading.Lock()

    def gerar(
        self, contexto: Contexto, modo: Modo, cancelado: Cancelado
    ) -> Generator[Delta, None, None]:
        del modo
        with self._trava:
            self.pedidos.append(contexto)
            primeiro = len(self.pedidos) == 1
            self.ativos += 1
            self.maximo_de_ativos = max(self.maximo_de_ativos, self.ativos)
        try:
            if not primeiro:
                yield Texto(self.depois)
                yield Fim(MotivoDoFim.CONCLUIDO)
                return
            yield Texto(self.texto)
            self.em_voo.set()
            # Preso numa "ferramenta" que não olha o cancelamento por um tempo.
            while not cancelado():
                time.sleep(0.005)
            time.sleep(self.teimosia_s)
            yield Fim(MotivoDoFim.CANCELADO)
        finally:
            with self._trava:
                self.ativos -= 1


class AplicativoCronometrado(Aplicativo):
    """O laço de sempre, anotando quando o corte aconteceu e quando cada turno do dono fechou."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.cortes: list[float] = []
        self.voltas: list[float] = []

    def interromper(self, motivo: str = "barge_in", *, resposta: bool = False) -> int:
        self.cortes.append(time.monotonic())
        return super().interromper(motivo, resposta=resposta)

    def _turno_de_audio(self, *args: Any, **kwargs: Any) -> None:
        self.voltas.append(time.monotonic())
        super()._turno_de_audio(*args, **kwargs)


def test_o_cerebro_que_demora_a_parar_nao_prende_o_laco_nem_roda_junto_com_o_novo(
    tmp_path: Path,
) -> None:
    """Uma ferramenta em voo segura o cérebro do turno cortado por 1,5 s: o laço volta a ouvir na
    hora (antes esperava até 2 s, com o microfone sem ser lido), e o turno novo espera o velho
    sair na linha dele — os dois nunca mexem na conversa juntos."""
    asr = AsrRoteirizado("jarvis me conta uma história", "jarvis que horas são")
    motor = MotorQueDemoraParaParar(LONGA, "São três e meia.", teimosia_s=1.5)
    app = AplicativoCronometrado(
        configuracao=Configuracao(asr="asr-whisper-local", tts="tts-parametrico", escuta="palavra"),
        raiz=tmp_path / "sessao",
        escrever_na_tela=lambda _linha: None,
        relogio=RelogioFalso(),
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
    )
    app._asr = asr
    app._motor = motor
    app.vigia = VigiaDeInterrupcao(
        transcrever=lambda amostras: asr.transcrever(amostras).texto, enviar=em_linha
    )
    app.caminho_de_entrada = _wav(
        tmp_path / "entrada.wav",
        _fala(400, 5),
        silencio(3600),
        _fala(1000, 7),
        silencio(3000),
    )
    app.caminho_de_saida = tmp_path / "saida.wav"

    app.rodar_audio(limite_de_turnos=2)

    assert [t.falou for t in app.turnos] == ["me conta uma história", "que horas são"]
    assert app.turnos[0].cancelado and app.turnos[1].respondeu == "São três e meia."
    # O laço voltou a ouvir na hora: o turno do dono fechou sem esperar o cérebro velho parar.
    assert app.cortes and len(app.voltas) == 2
    espera = app.voltas[1] - app.cortes[0]
    assert espera < 1.0, f"o laço esperou {espera:.2f} s pelo cérebro cortado"
    # E os dois cérebros não rodaram juntos: o novo esperou o velho sair.
    assert motor.maximo_de_ativos == 1
    # A conversa guarda o que o dono ouviu da história, marcada como interrompida.
    assert app._cerebro is not None
    papeis = [(m.papel, m.interrompida) for m in app._cerebro.conversa.turnos]
    assert papeis == [("dono", False), ("jarvis", True), ("dono", False), ("jarvis", False)]


# --- «para» depois do corte: as tarefas daquele turno param também ------------------------------
class MotorDeTarefaQueEspera:
    """O motor de uma tarefa longa: só termina quando a cancelam."""

    nome = "objetivo"
    na_nuvem = False

    def proximo(
        self, tarefa: Tarefa, feitos: Sequence[object], cancelado: Callable[[], bool]
    ) -> FimDaTarefa:
        del tarefa, feitos
        while not cancelado():
            time.sleep(0.005)
        return FimDaTarefa("cancelada")


class AplicativoQueDelega(Aplicativo):
    """Quando o dono corta, a tarefa que o turno cortado delegou já está rodando (ADR-0038): o
    teste a põe no gestor com o `turno` dele — e uma de outro turno, que não pode parar."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.delegadas: list[Tarefa] = []

    def _turno_de_audio(self, *args: Any, **kwargs: Any) -> None:
        gestor = self.ferramentas.tarefas if self.ferramentas is not None else None
        if self._turno_cortado and gestor is not None and not self.delegadas:
            for turno in (self._turno_cortado, "t-de-outro-pedido"):
                self.delegadas.append(
                    gestor.iniciar_objetivo(
                        f"pesquisa do turno {turno}",
                        MotorDeTarefaQueEspera(),
                        contaminacao=Contaminacao(),
                        turno=turno,
                    )
                )
        super()._turno_de_audio(*args, **kwargs)


def test_jarvis_para_por_cima_cancela_a_tarefa_do_turno_cortado_e_so_ela(tmp_path: Path) -> None:
    asr = AsrRoteirizado("jarvis me conta uma história", "jarvis para")
    app = AplicativoQueDelega(
        configuracao=Configuracao(asr="asr-whisper-local", tts="tts-parametrico", escuta="palavra"),
        raiz=tmp_path / "sessao",
        escrever_na_tela=lambda _linha: None,
        relogio=RelogioFalso(),
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo", "CI": "1"},
        lar=tmp_path,
    )
    app._asr = asr
    app._motor = MotorRoteirizado(resposta=_respostas(LONGA), nome="roteiro")
    app.vigia = VigiaDeInterrupcao(
        transcrever=lambda amostras: asr.transcrever(amostras).texto, enviar=em_linha
    )
    app.caminho_de_entrada = _wav(
        tmp_path / "entrada.wav", _fala(400, 5), silencio(3600), _fala(800, 7), silencio(3000)
    )
    app.caminho_de_saida = tmp_path / "saida.wav"
    app.abrir()
    gestor = app.ferramentas.tarefas if app.ferramentas is not None else None
    assert gestor is not None
    app._cancelar_tarefas = lambda: None  # type: ignore[method-assign]

    app.rodar_audio(limite_de_turnos=2)

    da_historia, de_outro = app.delegadas
    assert gestor.esperar(da_historia.id, 2.0)
    assert da_historia.estado is EstadoDaTarefa.CANCELADA, "a tarefa do turno cortado seguiu"
    assert not de_outro.estado.final, "o «para» cancelou a tarefa de outro pedido"
    gestor.cancelar_todas()
    assert gestor.esperar(de_outro.id, 2.0)
    # A tarefa cancelada não fala: o fim dela foi calado (só o card).
    assert [t.falou for t in app.turnos] == ["me conta uma história"]


def test_depois_do_corte_o_estado_volta_a_ouvindo_e_nunca_fica_preso_em_falando(
    tmp_path: Path,
) -> None:
    asr = AsrRoteirizado("jarvis me conta uma história", "jarvis que horas são")
    motor = MotorRoteirizado(resposta=_respostas(LONGA, "São três e meia."), nome="roteiro")
    app, _tela, estados = _aplicativo(
        tmp_path,
        "palavra",
        asr,
        motor,
        _fala(400, 5),
        silencio(3600),
        _fala(1000, 7),
        silencio(3000),
    )

    app.rodar_audio(limite_de_turnos=2)

    assert app.turnos[0].cancelado and app.turnos[1].respondeu == "São três e meia."
    # O corte devolve o laço a ouvir antes de qualquer outra coisa; e ele acaba parado.
    corte = estados.index(Estado.FALANDO)
    assert estados[corte + 1] is Estado.OUVINDO, estados
    assert estados[-1] is Estado.PARADO and app.estado is Estado.PARADO
