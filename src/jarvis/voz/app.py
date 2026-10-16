"""O laço do `jarvis-voz`: microfone → ASR → resposta → TTS → alto-falante, com barge-in.

**O que este aplicativo é.** Um laço de **teste**, num processo só, para o dono ouvir e falar
com o Jarvis hoje e julgar voz, latência e interrupção de ouvido. Ele reusa as peças da F1 em
vez de reimplementá-las — `Captura` e o VAD (F1-05), a `FilaDePlayback` com epoch (F1-03), o
`TranscritorIncremental` (F1-06), o `SintetizadorEmStreaming` cancelável (F1-09), o indicador
de microfone que não mente (F1-13) e a degradação declarada (F1-14). O que ele **não** é: os
sete processos da SPEC §2. Quando a F2 chegar, o laço de verdade mora lá.

**Epoch e barge-in, que é o que não pode afrouxar.** O aplicativo é dono do epoch, como o
`agentd` é na arquitetura: falar por cima (VAD) ou apertar a barra **incrementa o epoch**, e
isso, sozinho, derruba três coisas de uma vez — a síntese em curso para de produzir (o
sintetizador consulta `cancelado`), a fila de playback descarta o que não tocou, e o motor de
nuvem (se houver) abandona o corpo da resposta em voo. Nenhuma dessas três precisa saber das
outras: todas consultam a mesma pergunta.

**As três portas da janela (ADR-0019).** A interface gráfica não reimplementa nada disto: ela
liga três funções e fica sabendo o resto pelo que já existe. `ao_mudar_estado` é o laço
**dizendo** o que está fazendo (nunca a tela adivinhando); `pressionado` é o PTT de verdade,
que o terminal não tem como oferecer porque não há evento de tecla solta; e `texto_digitado` é
uma linha digitada entrando como turno no **mesmo** laço e no **mesmo** epoch — e não num
caminho paralelo, que seria o jeito mais fácil de perder o cancelamento. Com as três em
`None`, este arquivo se comporta exatamente como antes da janela existir.

**O indicador é o do F1-13, e pelo mesmo motivo.** O que a tela mostra vem de
`microfone-estado.json`, escrito por quem está com a fonte na mão — não da intenção de quem
desenhou a tela. Fonte fechada é zero amostra, e é por isso que o indicador não tem como
mentir.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.agentd.asr import MotorWhisper, TranscritorIncremental
from jarvis.agentd.tts import MotorParametrico, MotorPiperOnnx, SintetizadorEmStreaming
from jarvis.audio_io.backend import fonte_do_ambiente, sumidouro_do_ambiente
from jarvis.audio_io.captura import Captura
from jarvis.audio_io.erros import ErroDeAudio
from jarvis.audio_io.playback import FilaDePlayback
from jarvis.audio_io.quadro import BYTES_POR_AMOSTRA, TAXA_PADRAO
from jarvis.audio_io.vad import Vad
from jarvis.barramento.envelope import uuid7
from jarvis.microfone import EstadoDaFonte, Modo, escrever_estado
from jarvis.rede import ErroDeRede
from jarvis.relogio import Relogio, RelogioDoSistema
from jarvis.voz.chaves import SegredoAusente
from jarvis.voz.config import Configuracao
from jarvis.voz.estado import Estado
from jarvis.voz.interface import MotorDeAsr, MotorDeTts, Onde
from jarvis.voz.registro import MotorRecusado, motor_registrado
from jarvis.voz.s2_provisorio import (
    GeradorDeResposta,
    RespostaDeEco,
    RespostaIndisponivel,
    RespostaPelaCli,
)
from jarvis.voz.teclado import ESPACO, TECLAS_DE_SAIDA, Teclado, TecladoMudo

PASTA_DE_VOZES: Final = Path.home() / ".cache" / "jarvis" / "vozes"
ID_DA_VOZ_NO_REGISTRO: Final = "rhasspy/piper-voices:{voz}"
SILENCIO_PARA_FECHAR_O_TURNO_MS: Final = 700.0
"""Quanto silêncio fecha o turno no modo VAD. Não é o detector semântico do F1-07 — é o
piso simples, e está dito no relatório para ninguém publicar isto como SLO-4."""
MAXIMO_DE_AUDIO_POR_TURNO_S: Final = 30.0


class AplicativoIndisponivel(RuntimeError):
    """O laço não tem como rodar com esta configuração. A frase diz o que falta."""


@dataclass(frozen=True, slots=True)
class Turno:
    """O que aconteceu num turno — é o que o dono lê na tela e no relatório."""

    falou: str
    respondeu: str
    ouvido_ms: float = 0.0
    asr_ms: float = 0.0
    resposta_ms: float = 0.0
    primeiro_pedaco_ms: float = 0.0
    tts_ms: float = 0.0
    amostras_tocadas: int = 0
    cancelado: bool = False
    epoch: int = 0

    @property
    def total_ms(self) -> float:
        return self.asr_ms + self.resposta_ms + self.tts_ms

    def resumo(self) -> str:
        if self.cancelado:
            return f"  (interrompido no epoch {self.epoch}, nada do resto foi tocado)"
        return (
            f"  [ouvi {self.ouvido_ms:.0f} ms · asr {self.asr_ms:.0f} ms · "
            f"resposta {self.resposta_ms:.0f} ms · 1º pedaço {self.primeiro_pedaco_ms:.0f} ms · "
            f"fala {self.tts_ms:.0f} ms]"
        )


def _caminho_da_voz(voz: str) -> Path:
    return PASTA_DE_VOZES / voz / f"{voz}.onnx"


def motor_de_asr(
    configuracao: Configuracao,
    *,
    raiz: Path,
    cancelado: Callable[[], bool],
    ambiente: Mapping[str, str] | None = None,
) -> MotorDeAsr:
    """O motor de ASR que a configuração pediu, já pelo portão (ADR-0017)."""
    registro = motor_registrado(configuracao.asr)
    if registro is None:
        raise AplicativoIndisponivel(f"motor de ASR {configuracao.asr!r} não está no registro")
    if registro.onde is Onde.NUVEM:
        from jarvis.voz.groq import MotorAsrGroq

        motor = MotorAsrGroq(
            raiz=raiz,
            modelo=registro.modelo,
            registrado=registro.id,
            nuvem_ligada=configuracao.nuvem_ligada,
            cancelado=cancelado,
            ambiente=ambiente,
        )
        motor.abrir()
        return motor
    if registro.id == "asr-oraculo":
        raise AplicativoIndisponivel(
            "o oráculo do rótulo não transcreve voz de verdade: ele devolve o texto do corpus "
            "(F1-06). Escolha `asr-whisper-local` ou um motor de nuvem"
        )
    local = MotorWhisper(tamanho=configuracao.modelo_do_asr, pasta=str(PASTA_DE_VOZES.parent))
    local.abrir()
    return local


def motor_de_tts(
    configuracao: Configuracao,
    *,
    raiz: Path,
    cancelado: Callable[[], bool],
    ambiente: Mapping[str, str] | None = None,
) -> MotorDeTts:
    """O motor de TTS que a configuração pediu, já pelo portão (ADR-0017)."""
    registro = motor_registrado(configuracao.tts)
    if registro is None:
        raise AplicativoIndisponivel(f"motor de TTS {configuracao.tts!r} não está no registro")
    if registro.id == "tts-parametrico":
        return MotorParametrico()
    if registro.id == "tts-elevenlabs":
        from jarvis.voz.elevenlabs import MotorTtsElevenLabs

        nuvem = MotorTtsElevenLabs(
            raiz=raiz,
            voz=configuracao.voz,
            nuvem_ligada=configuracao.nuvem_ligada,
            cancelado=cancelado,
            ambiente=ambiente,
        )
        nuvem.abrir()
        return nuvem
    if registro.id == "tts-edge":
        from jarvis.voz.edge import MotorTtsEdge

        edge = MotorTtsEdge(
            raiz=raiz,
            voz=configuracao.voz or "pt-BR-AntonioNeural",
            nuvem_ligada=configuracao.nuvem_ligada,
            sem_termos_aceitos=configuracao.nuvem_sem_termos,
            cancelado=cancelado,
            ambiente=ambiente,
        )
        edge.abrir()
        return edge
    from jarvis.voz.fonemizador import FonemizadorEpitran

    caminho = _caminho_da_voz(configuracao.voz)
    if not caminho.exists():
        from jarvis.voz.modelos import descarga_da_voz

        descarga = descarga_da_voz(configuracao.voz)
        como = (
            f"`jarvis-voz --baixar-voz` ({descarga.tamanho}) ou o botão na aba de diagnóstico"
            if descarga is not None
            else "ver docs/COMO-TESTAR.md"
        )
        raise AplicativoIndisponivel(
            f"a voz {configuracao.voz} não está em {caminho.parent}. Baixe-a com {como}, "
            "ou use `tts-parametrico` para testar o encanamento"
        )
    piper = MotorPiperOnnx(
        caminho=caminho,
        fonemizar=FonemizadorEpitran(),
        voz=configuracao.voz,
        identificador_registrado=ID_DA_VOZ_NO_REGISTRO.format(voz=configuracao.voz),
        registrado=registro.id,
    )
    piper.abrir()
    return piper


def gerador_de_resposta(
    configuracao: Configuracao,
    *,
    pasta_de_trabalho: Path,
    cancelado: Callable[[], bool],
) -> GeradorDeResposta:
    if configuracao.s2 == "eco":
        return RespostaDeEco()
    pasta_de_trabalho.mkdir(parents=True, exist_ok=True)
    return RespostaPelaCli(
        pasta_de_trabalho=pasta_de_trabalho,
        modelo=configuracao.modelo_do_s2,
        cancelado=cancelado,
    )


@dataclass(slots=True)
class Aplicativo:
    """O laço. Dono do epoch, como o `agentd` é na arquitetura de verdade."""

    configuracao: Configuracao
    raiz: Path
    escrever_na_tela: Callable[[str], None] = print
    relogio: Relogio = field(default_factory=RelogioDoSistema)
    ambiente: Mapping[str, str] | None = None
    teclado: Teclado = field(default_factory=TecladoMudo)
    caminho_de_entrada: Path | None = None
    """Com `JARVIS_AUDIO_BACKEND=arquivo`, o WAV que entra no lugar do microfone (F1-01).

    É o que deixa o laço inteiro ser exercitado sem placa de som — na suíte e na máquina do
    dono enquanto ele não tiver o PortAudio instalado."""
    caminho_de_saida: Path | None = None
    """E o WAV onde o que o Jarvis fala é gravado, no lugar do alto-falante."""

    ao_mudar_estado: Callable[[Estado], None] | None = None
    """Chamada a cada mudança de estado (ADR-0019). A janela liga aqui; o terminal não liga.

    **Só é chamada quando o estado muda de verdade**, e o laço não a protege: um observador
    que levanta exceção derruba o turno, e é assim de propósito — tela que quebra calada é
    tela que mente. Quem liga aqui emite sinal e volta; não faz trabalho."""
    pressionado: Callable[[], bool] | None = None
    """O PTT de verdade: "o dono está com o botão apertado agora?" (ADR-0019).

    Com ela ligada, quem decide que o dono está falando é o **dedo dele**, não o VAD, e soltar
    fecha o turno no mesmo tique — sem esperar os 700 ms de silêncio. O terminal não liga isto
    porque não recebe evento de tecla solta (`jarvis.voz.teclado`).

    **Limite honesto, e está na tela:** aqui a fonte continua **aberta** enquanto o laço roda;
    o que o botão controla é o que vira turno. Fechar e reabrir o dispositivo a cada aperto é
    trabalho do `audio-io` com o arquivo de pedido do F1-13, na F2 — e o indicador continua
    mostrando a fonte como ela está, não como a tela gostaria que estivesse."""
    texto_digitado: Callable[[], str | None] | None = None
    """Uma linha que o dono digitou, se houver. É consultada entre os quadros do laço de áudio.

    Digitar no meio do laço de voz é um turno como outro qualquer: mesmo epoch, mesma fila de
    playback, mesma interrupção. Fazer isso por fora (uma segunda thread chamando `responder`)
    daria dois donos do epoch — e dois donos do epoch é a origem do barge-in que não cancela."""

    epoch: int = 1
    estado: Estado = Estado.PARADO
    session_id: str = field(default_factory=lambda: str(uuid7()))
    turnos: list[Turno] = field(default_factory=list)
    _asr: MotorDeAsr | None = field(default=None, repr=False)
    _tts: MotorDeTts | None = field(default=None, repr=False)
    _s2: GeradorDeResposta | None = field(default=None, repr=False)

    # --- montagem -----------------------------------------------------------------------
    def cancelado_de(self, epoch: int) -> Callable[[], bool]:
        """A pergunta que todo mundo faz: "o epoch ainda é meu?" (ADR-0002, §3.3 regra 1)."""

        def cancelado() -> bool:
            return self.epoch > epoch

        return cancelado

    def _cancelado_agora(self) -> bool:
        return self.cancelado_de(self.epoch)()

    def _mudar(self, estado: Estado) -> None:
        """Muda o estado e avisa quem pediu para ser avisado. Sem mudança, sem aviso."""
        if estado is self.estado:
            return
        self.estado = estado
        if self.ao_mudar_estado is not None:
            self.ao_mudar_estado(estado)

    @property
    def _repouso(self) -> Estado:
        """Para onde o estado volta depois de um turno: ouvindo, se a fonte está aberta."""
        return Estado.OUVINDO if self._escutando else Estado.PARADO

    def abrir(self, *, com_asr: bool = True) -> None:
        """Monta os motores necessários. Falha aqui, com frase, não no meio do primeiro turno.

        `com_asr=False` é o modo texto: sem microfone não há o que transcrever, e exigir um
        motor de ASR ali faria o dono baixar modelo para digitar — ou travaria o modo que
        existe **justamente** para funcionar quando o áudio não vai.

        **Idempotente, e isso é contrato:** motor já montado não é remontado. `responder`
        chama `abrir` quando falta alguém, o laço de áudio chama no começo, e quem monta um
        motor à mão (medição, teste) não pode tê-lo trocado por baixo — seria o aplicativo
        reabrindo o modelo a cada turno e descartando o estado de quem o injetou.
        """
        cancelado = self._cancelado_do_turno_corrente
        self.raiz.mkdir(parents=True, exist_ok=True)
        try:
            if com_asr and self._asr is None:
                self._asr = motor_de_asr(
                    self.configuracao, raiz=self.raiz, cancelado=cancelado, ambiente=self.ambiente
                )
            if self._tts is None:
                self._tts = motor_de_tts(
                    self.configuracao, raiz=self.raiz, cancelado=cancelado, ambiente=self.ambiente
                )
        except (MotorRecusado, SegredoAusente, ErroDeRede) as erro:
            # As três recusas chegam ao dono como a mesma coisa — "não deu para começar, e
            # aqui está o porquê" —, porque para ele são: motor desligado, chave ausente e
            # nuvem proibida sob CI resolvem-se lendo a frase, não um traceback.
            raise AplicativoIndisponivel(str(erro)) from None
        if self._s2 is None:
            self._s2 = gerador_de_resposta(
                self.configuracao,
                pasta_de_trabalho=self.raiz / "conversa",
                cancelado=cancelado,
            )
        self._aquecer()

    def _aquecer(self) -> None:
        """Uma síntese curta, jogada fora, **só em motor local**.

        Medido aqui: a primeira fala do piper custa ~1,8 s nesta máquina (carregar o grafo
        ONNX e as tabelas do `epitran`) e as seguintes, ~70 ms. Sem aquecer, o dono ouve esse
        segundo e meio no primeiro turno e conclui que a voz é lenta — quando o que ele mediu
        foi o carregamento.

        **Nunca em motor de nuvem:** aquecer ali seria mandar texto para fora e pagar uma
        requisição que ninguém pediu. Por isso a condição é `onde is LOCAL`, e não "se der".
        """
        if self._tts is None or self._tts.onde is not Onde.LOCAL:
            return
        try:
            self._tts.sintetizar("oi")
        except Exception:  # aquecimento é melhor-esforço: falhar aqui não derruba o turno
            return

    def _cancelado_do_turno_corrente(self) -> bool:
        """Os motores recebem **esta** função, que olha o epoch do turno em curso.

        Passar `cancelado_de(epoch)` na montagem prenderia o motor ao epoch do começo do
        aplicativo, e ele nunca mais cancelaria. Aqui a pergunta é sempre sobre o turno de
        agora — é o mesmo motivo pelo qual o `audio-io` **segue** o epoch em vez de guardá-lo
        (defeito achado no F1-14).
        """
        return self._turno_cancelado

    _turno_cancelado: bool = False
    _escutando: bool = False
    """Verdadeiro enquanto o laço de áudio está com a fonte aberta (define o repouso)."""

    # --- um turno -----------------------------------------------------------------------
    def responder(self, texto: str, *, fila: FilaDePlayback | None = None) -> Turno:
        """Texto → resposta → áudio no sumidouro. É o turno sem a parte do microfone."""
        if self._tts is None or self._s2 is None:
            # Só o que este caminho usa: responder não transcreve nada.
            self.abrir(com_asr=False)
        assert self._tts is not None and self._s2 is not None

        epoch = self.epoch
        self._turno_cancelado = False
        self._mudar(Estado.PENSANDO)
        comeco = time.monotonic()
        try:
            resposta = self._s2.responder(texto)
        except RespostaIndisponivel as erro:
            self.escrever_na_tela(f"  (sem resposta: {erro})")
            self._mudar(self._repouso)
            return Turno(falou=texto, respondeu="", epoch=epoch)
        resposta_ms = (time.monotonic() - comeco) * 1000.0
        if not resposta:
            self._mudar(self._repouso)
            return Turno(
                falou=texto, respondeu="", resposta_ms=resposta_ms, cancelado=True, epoch=epoch
            )
        turno = self.falar(resposta, epoch=epoch, fila=fila)
        self._mudar(self._repouso)
        return Turno(
            falou=texto,
            respondeu=resposta,
            resposta_ms=resposta_ms,
            primeiro_pedaco_ms=turno.primeiro_pedaco_ms,
            tts_ms=turno.tts_ms,
            amostras_tocadas=turno.amostras_tocadas,
            cancelado=turno.cancelado,
            epoch=epoch,
        )

    def falar(self, texto: str, *, epoch: int, fila: FilaDePlayback | None = None) -> Turno:
        """Sintetiza e entrega, parando no cancelamento (contrato do F1-09)."""
        assert self._tts is not None
        self._mudar(Estado.FALANDO)
        sintetizador = SintetizadorEmStreaming(
            motor=self._tts,
            session_id=self.session_id,
            epoch=epoch,
            cancelado=self.cancelado_de(epoch),
        )
        comeco = time.monotonic()
        primeiro: float = 0.0
        tocadas = 0
        for pedaco, _trecho in sintetizador.pedacos(texto):
            if primeiro == 0.0:
                primeiro = (time.monotonic() - comeco) * 1000.0
            if fila is None:
                # Sem fila (modo texto sem áudio), o que se mede é a síntese: o pedaço conta
                # como produzido, e fica claro no relatório que ninguém o tocou.
                tocadas += pedaco.n_amostras
                self._olhar_o_teclado()
                if self.epoch > epoch:
                    break
                continue
            if not fila.enfileirar(pedaco):
                continue
            # Drena o pedaço quadro a quadro, olhando o teclado entre eles: é aqui que a
            # barra interrompe **no meio** do pedaço, e não só entre pedaços.
            while fila.pedacos_na_fila and self.epoch == epoch:
                antes = fila.sumidouro.amostras_consumidas
                fila.tick()
                tocadas += fila.sumidouro.amostras_consumidas - antes
                self._olhar_o_teclado()
            if self.epoch > epoch:
                fila.cancelar(reason="barge_in", epoch_novo=self.epoch)
                break
        return Turno(
            falou="",
            respondeu=texto,
            primeiro_pedaco_ms=primeiro,
            tts_ms=(time.monotonic() - comeco) * 1000.0,
            amostras_tocadas=tocadas,
            cancelado=self.epoch > epoch,
            epoch=epoch,
        )

    def interromper(self, motivo: str = "barge_in") -> int:
        """O dono falou por cima (ou apertou a barra): o epoch morre e tudo cai junto."""
        self.epoch += 1
        self._turno_cancelado = True
        self._mudar(self._repouso)
        self.escrever_na_tela(f"  ⟂ interrompido ({motivo})")
        return self.epoch

    def _olhar_o_teclado(self) -> str | None:
        tecla = self.teclado.tecla()
        if tecla is None:
            return None
        if tecla in TECLAS_DE_SAIDA:
            return tecla
        if tecla == ESPACO:
            self.interromper("tecla")
        return tecla

    # --- modo texto ----------------------------------------------------------------------
    def rodar_texto(self, linhas: Iterable[str]) -> int:
        """Sem microfone: o dono digita, o Jarvis responde e **fala** pelo sumidouro.

        É o caminho que funciona sem placa de som — e é o que prova o resto do laço quando o
        dispositivo não abre (aceite do pedido do dono).
        """
        self.abrir(com_asr=False)
        self._dizer_o_que_esta_ligado()
        for linha in linhas:
            texto = linha.strip()
            if not texto:
                continue
            if texto in {"/sair", "/quit", "/q"}:
                break
            turno = self.responder(texto)
            self.turnos.append(turno)
            if turno.respondeu:
                self.escrever_na_tela(f"Jarvis: {turno.respondeu}")
            self.escrever_na_tela(turno.resumo())
        self._mudar(Estado.PARADO)
        return 0

    # --- modo áudio ----------------------------------------------------------------------
    def rodar_audio(self, *, limite_de_turnos: int | None = None, vad: Vad | None = None) -> int:
        """O laço de voz. Fecha o turno por silêncio (VAD) ou pela barra (PTT)."""
        self.abrir()
        self._dizer_o_que_esta_ligado()
        fonte = fonte_do_ambiente(
            relogio=self.relogio, caminho=self.caminho_de_entrada, ambiente=self.ambiente
        )
        sumidouro = sumidouro_do_ambiente(caminho=self.caminho_de_saida, ambiente=self.ambiente)
        captura = Captura(
            fonte=fonte, relogio=self.relogio, session_id=self.session_id, epoch=self.epoch
        )
        if vad is not None:
            captura.detector = vad
        try:
            # Quem abre a fonte é a `Captura` (F1-03), não este laço: é dela que o estado
            # "aberta" vem, e é desse estado que o indicador do F1-13 deriva. Abrir por fora
            # e enfiar o iterador na captura faria o indicador descrever outra coisa.
            captura.abrir()
            sumidouro.abrir()
        except ErroDeAudio as erro:
            raise AplicativoIndisponivel(
                f"{erro}\n  Sem dispositivo, use `jarvis-voz --texto` para testar o resto do "
                "laço (resposta e voz saem em arquivo ou no alto-falante quando houver)."
            ) from None
        self._escutando = True
        self._mudar(Estado.OUVINDO)
        fila = FilaDePlayback(
            sumidouro=sumidouro, session_id=self.session_id, epoch_atual=self.epoch
        )
        transcritor = TranscritorIncremental(motor=self._asr) if self._asr is not None else None
        assert transcritor is not None

        falando = False
        silencio_ms = 0.0
        audio = bytearray()
        turnos = 0
        try:
            while limite_de_turnos is None or turnos < limite_de_turnos:
                self._publicar_estado(captura, aberta=True)
                if self._olhar_o_teclado() in TECLAS_DE_SAIDA:
                    break
                digitado = self.texto_digitado() if self.texto_digitado is not None else None
                if digitado:
                    turnos += 1
                    self._turno_digitado(digitado, fila)
                    falando, silencio_ms, audio = False, 0.0, bytearray()
                    continue
                quadros_antes = captura.quadros
                eventos = captura.tick()
                quadro = captura.ultimo_quadro
                # A fonte acabou (o WAV terminou, o dispositivo fechou) quando o tique não
                # trouxe quadro novo. Olhar só `ultimo_quadro` não serve: ele guarda o
                # **último** quadro, e continua preenchido depois do fim — era assim que este
                # laço girava a 100% de CPU sem ter mais nada para ouvir. Achado pelo teste do
                # PTT, onde nenhum turno fecha e a saída tinha de vir do fim da fonte.
                if quadro is None or captura.quadros == quadros_antes:
                    break
                if self._quer_falar(captura):
                    if not falando:
                        falando = True
                        audio = bytearray()
                        if fila.pedacos_na_fila:
                            self.interromper("barge_in")
                            fila.cancelar(reason="barge_in", epoch_novo=self.epoch)
                    silencio_ms = 0.0
                    audio.extend(quadro.amostras)
                elif falando:
                    silencio_ms += 20.0
                    audio.extend(quadro.amostras)
                    # No PTT o fim do turno é o dedo saindo do botão: esperar 700 ms de
                    # silêncio ali seria cobrar do dono um silêncio que ele já declarou.
                    fechou = self.pressionado is not None or (
                        silencio_ms >= SILENCIO_PARA_FECHAR_O_TURNO_MS
                    )
                    if fechou:
                        falando = False
                        turnos += 1
                        self._turno_de_audio(bytes(audio), transcritor, fila)
                        audio = bytearray()
                _ = eventos
                if len(audio) > MAXIMO_DE_AUDIO_POR_TURNO_S * TAXA_PADRAO * BYTES_POR_AMOSTRA:
                    falando = False
                    turnos += 1
                    self._turno_de_audio(bytes(audio), transcritor, fila)
                    audio = bytearray()
        finally:
            self._publicar_estado(captura, aberta=False)
            captura.fechar()
            sumidouro.fechar()
            self._escutando = False
            self._mudar(Estado.PARADO)
        return 0

    def _quer_falar(self, captura: Captura) -> bool:
        """Quem diz que o dono está falando: o dedo dele (PTT da janela) ou o VAD."""
        if self.pressionado is not None:
            return self.pressionado()
        return bool(captura.detector.falando)

    def _turno_digitado(self, texto: str, fila: FilaDePlayback) -> None:
        """Uma linha digitada no meio do laço de voz. Mesmo turno, mesmo epoch, mesma fila."""
        self.escrever_na_tela(f"Você (digitado): {texto}")
        turno = self.responder(texto, fila=fila)
        self.turnos.append(turno)
        if turno.respondeu:
            self.escrever_na_tela(f"Jarvis: {turno.respondeu}")
        self.escrever_na_tela(turno.resumo())

    def _turno_de_audio(
        self, amostras: bytes, transcritor: TranscritorIncremental, fila: FilaDePlayback
    ) -> None:
        assert self._asr is not None
        self._mudar(Estado.PENSANDO)
        comeco = time.monotonic()
        hipotese = self._asr.transcrever(amostras)
        asr_ms = (time.monotonic() - comeco) * 1000.0
        ouvido_ms = 1000.0 * (len(amostras) // BYTES_POR_AMOSTRA) / TAXA_PADRAO
        if not hipotese.texto.strip():
            self.escrever_na_tela("  (não entendi nada nesse trecho)")
            self._mudar(self._repouso)
            return
        self.escrever_na_tela(f"Você: {hipotese.texto}")
        turno = self.responder(hipotese.texto, fila=fila)
        completo = Turno(
            falou=hipotese.texto,
            respondeu=turno.respondeu,
            ouvido_ms=ouvido_ms,
            asr_ms=asr_ms,
            resposta_ms=turno.resposta_ms,
            primeiro_pedaco_ms=turno.primeiro_pedaco_ms,
            tts_ms=turno.tts_ms,
            amostras_tocadas=turno.amostras_tocadas,
            cancelado=turno.cancelado,
            epoch=turno.epoch,
        )
        self.turnos.append(completo)
        if completo.respondeu:
            self.escrever_na_tela(f"Jarvis: {completo.respondeu}")
        self.escrever_na_tela(completo.resumo())

    def _publicar_estado(self, captura: Captura, *, aberta: bool) -> None:
        """O indicador do F1-13: o que a fonte **está** fazendo, não o que a tela quer."""
        escrever_estado(
            self.raiz,
            EstadoDaFonte(
                aberta=aberta and captura.aberta,
                amostras=captura.amostras_capturadas if aberta else 0,
                amostras_totais=captura.amostras_capturadas,
                device_id=captura.fonte.device_id if aberta else None,
                modo=Modo.PTT if self.configuracao.escuta == "ptt" else Modo.ESCUTA,
            ),
        )

    def _dizer_o_que_esta_ligado(self) -> None:
        """Antes do primeiro turno, o dono lê o que está ligado — inclusive o que sai daqui."""
        assert self._tts is not None and self._s2 is not None
        if self._asr is None:
            self.escrever_na_tela("ouvindo com: (modo texto — o microfone não entra aqui)")
        else:
            self.escrever_na_tela(f"ouvindo com: {self._asr.nome}  [{self._asr.onde}]")
        self.escrever_na_tela(f"falando com: {self._tts.nome}  [{self._tts.onde}]")
        self.escrever_na_tela(f"respondendo com: {self._s2.nome}")
        for motor in self.configuracao.motores_de_nuvem_escolhidos():
            self.escrever_na_tela("")
            self.escrever_na_tela(f"  {motor.frase_de_aviso}")
        self.escrever_na_tela("")
