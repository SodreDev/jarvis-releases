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

import contextlib
import os
import queue
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from jarvis.agentd.asr import MotorWhisper, TranscritorIncremental
from jarvis.agentd.fala_em_stream import trechos_do_stream
from jarvis.agentd.fila_de_avisos import Entrega, FilaDeAvisos, notificacao
from jarvis.agentd.tts import (
    MAXIMO_DE_SINTESES_PENDENTES,
    Fala,
    MotorParametrico,
    MotorPiperOnnx,
    SintetizadorEmStreaming,
    Trecho,
    fatiar,
)
from jarvis.ambiente import ambiente_ou_os
from jarvis.apps.resolvedor import RepositorioDeAliases, dicas_de_apps
from jarvis.audio_io.ambiente import Backend, backend_escolhido
from jarvis.audio_io.backend import dispositivo_pedido, fonte_do_ambiente, sumidouro_do_ambiente
from jarvis.audio_io.captura import Captura
from jarvis.audio_io.erros import ErroDeAudio
from jarvis.audio_io.playback import FilaDePlayback, Pedaco
from jarvis.audio_io.quadro import BYTES_POR_AMOSTRA, TAXA_PADRAO
from jarvis.audio_io.sumidouros import SumidouroDeAudio
from jarvis.audio_io.vad import Vad, vad_do_ambiente
from jarvis.barramento.envelope import Envelope, Trust, uuid7
from jarvis.decisao.enderecamento import DetectorDeEnderecamento, Motivo
from jarvis.decisao.openrouter import ClassificadorOpenRouter
from jarvis.entrada.controle import ControleDeEntrada
from jarvis.entrada.escolha import backend_do_ambiente
from jarvis.entrada.foco import foco_do_ambiente
from jarvis.entrada.limite import Interruptor
from jarvis.executor import desktop
from jarvis.executor.alarmes import Alarme, agenda_compartilhada
from jarvis.executor.ferramentas import Confirmacao, ExecutorDeFerramentas
from jarvis.executor.lancador import RegistroDeApps, listar_apps
from jarvis.executor.navegadores import AbridorDeNavegador, separar
from jarvis.memoryd.conversa import ConversaPersistente
from jarvis.memoryd.ferramentas import FerramentasDeMemoria
from jarvis.microfone import EstadoDaFonte, Modo, escrever_estado
from jarvis.navegador.cliente import ClienteDoNavegador, TransporteUnix, familia_do_host
from jarvis.navegador.estado import EstadoDaPonte, sondar
from jarvis.navegador.ferramentas import CorposDoNavegador
from jarvis.politica.abertura import nome_de_app
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.canonicalizacao import Sistema, canonicalizar
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo as ModoDeAcesso
from jarvis.politica.modos import Raiz
from jarvis.politica.pdp import Pdp
from jarvis.rede import ErroDeRede
from jarvis.relogio import Relogio, RelogioDoSistema
from jarvis.s2.cerebro import Cerebro, Resposta
from jarvis.s2.motor import INTERVALO_DE_CONSULTA_S, Mensagem, MotivoDoFim, MotorDeConversa
from jarvis.s2.motor_claude_cli import MotorClaudeCli
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.s2.portao import PortaoDeAcao
from jarvis.tarefas.gestor import (
    EstadoDaTarefa,
    GestorDeTarefas,
    MotorDeTarefa,
    MotorDireto,
    Tarefa,
)
from jarvis.tarefas.motores import MotorDeAgente
from jarvis.voz.chaves import SegredoAusente
from jarvis.voz.config import ASR_PADRAO, Configuracao
from jarvis.voz.escuta import Escuta, ModoDeEscuta
from jarvis.voz.estado import Estado
from jarvis.voz.interface import MotorDeAsr, MotorDeTts, Onde
from jarvis.voz.prontidao import o_que_falta
from jarvis.voz.registro import MotorRecusado, motor_registrado
from jarvis.voz.s2_provisorio import RespostaDeEco
from jarvis.voz.teclado import ESPACO, TECLAS_DE_SAIDA, Teclado, TecladoMudo

PASTA_DE_VOZES: Final = Path.home() / ".cache" / "jarvis" / "vozes"
ID_DA_VOZ_NO_REGISTRO: Final = "rhasspy/piper-voices:{voz}"
SILENCIO_PARA_FECHAR_O_TURNO_MS: Final = 700.0
QUADROS_ANTES_DA_FALA: Final = 20
"""400 ms de quadros guardados antes do VAD disparar (20 quadros de 20 ms)."""
"""Quanto silêncio fecha o turno no modo VAD. Não é o detector semântico do F1-07 — é o
piso simples, e está dito no relatório para ninguém publicar isto como SLO-4."""
MAXIMO_DE_AUDIO_POR_TURNO_S: Final = 30.0
ESPERA_DO_CEREBRO_S: Final = 2.0
"""Quanto o laço espera a linha do cérebro fechar depois do último pedaço (ou do cancelamento):
o motor já parou de gerar (regra 9 da ADR-0025, ≤ 50 ms); isto é só o fim da linha."""


class AplicativoIndisponivel(RuntimeError):
    """O laço não tem como rodar com esta configuração. A frase diz o que falta."""


class OuvidoIndisponivel(AplicativoIndisponivel):
    """O que falta é o ASR: a fala do dono não vira texto. A janela diz isso com o caminho
    (ligar o da nuvem ou usar o local), em vez de cair calada no modo texto."""


@dataclass(frozen=True, slots=True)
class Turno:
    """O que aconteceu num turno — é o que o dono lê na tela e no relatório."""

    falou: str
    respondeu: str
    ouvido_ms: float = 0.0
    asr_ms: float = 0.0
    resposta_ms: float = 0.0
    """Do enviado à 1ª fronteira: o primeiro pedaço de fala que o cérebro publicou."""
    primeiro_pedaco_ms: float = 0.0
    """Do enviado ao 1º áudio na fila de playback."""
    tts_ms: float = 0.0
    contexto_ms: float = 0.0
    """Do enviado ao contexto pronto para o motor (inclui a consulta à memória)."""
    primeiro_token_ms: float = 0.0
    """Do enviado ao primeiro texto que o motor entregou."""
    amostras_tocadas: int = 0
    cancelado: bool = False
    epoch: int = 0

    @property
    def total_ms(self) -> float:
        return self.asr_ms + self.resposta_ms + self.tts_ms

    def resumo(self) -> str:
        if self.cancelado:
            return f"  (interrompido no epoch {self.epoch}, nada do resto foi tocado)"
        # Cada trecho visível, contado do enviado (pedido do dono, 2026-10-16: "está lento" —
        # a tela diz onde o tempo foi). Com voz, antes vêm o ouvido e o ASR.
        voz = (
            f"ouvi {self.ouvido_ms:.0f} ms · asr {self.asr_ms:.0f} ms · " if self.ouvido_ms else ""
        )
        return (
            f"  [{voz}enviado → contexto {self.contexto_ms:.0f} ms · "
            f"1º token {self.primeiro_token_ms:.0f} ms · 1ª fronteira {self.resposta_ms:.0f} ms · "
            f"1º áudio {self.primeiro_pedaco_ms:.0f} ms · fala inteira {self.tts_ms:.0f} ms]"
        )


def _caminho_da_voz(voz: str) -> Path:
    return PASTA_DE_VOZES / voz / f"{voz}.onnx"


def motor_de_asr(
    configuracao: Configuracao,
    *,
    raiz: Path,
    cancelado: Callable[[], bool],
    ambiente: Mapping[str, str] | None = None,
    dicas_apps: Iterable[str] = (),
) -> MotorDeAsr:
    """O motor de ASR que a configuração pediu, já pelo portão (ADR-0017).

    `dicas_apps` são os nomes dos apps instalados: o ASR local os recebe como `hotwords` e
    `initial_prompt`, para "abre o Discord" não virar "abre o disco" (pedido do dono, 2026-10-18; o
    resolvedor de `jarvis.apps` faz o resto, contra o registro)."""
    falta = o_que_falta(
        configuracao.asr, configuracao, ambiente=ambiente, pasta_de_vozes=PASTA_DE_VOZES
    )
    if falta:
        raise OuvidoIndisponivel(f"o ASR escolhido ({configuracao.asr}) não roda: {falta}")
    registro = motor_registrado(configuracao.asr)
    if registro is None:
        raise OuvidoIndisponivel(f"motor de ASR {configuracao.asr!r} não está no registro")
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
    local = MotorWhisper(
        tamanho=configuracao.modelo_do_asr,
        pasta=str(PASTA_DE_VOZES.parent),
        dicas=dicas_de_apps(dicas_apps, primeira=configuracao.palavra),
    )
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
    falta = o_que_falta(
        configuracao.tts, configuracao, ambiente=ambiente, pasta_de_vozes=PASTA_DE_VOZES
    )
    if falta:
        raise AplicativoIndisponivel(f"a voz escolhida ({configuracao.tts}) não roda: {falta}")
    registro = motor_registrado(configuracao.tts)
    if registro is None:
        raise AplicativoIndisponivel(f"motor de TTS {configuracao.tts!r} não está no registro")
    if registro.id == "tts-parametrico":
        return MotorParametrico()
    if registro.id == "tts-elevenlabs":
        from jarvis.voz.elevenlabs import MotorTtsElevenLabs

        nuvem = MotorTtsElevenLabs(
            raiz=raiz,
            voz=configuracao.voz_elevenlabs,
            modelo=configuracao.modelo_elevenlabs or registro.modelo,
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


def motor_de_conversa(configuracao: Configuracao, *, pasta_de_trabalho: Path) -> MotorDeConversa:
    """O motor do cérebro que o dono escolheu (ADR-0025; D18 do roteiro da F2).

    `eco` é o **padrão**: repete o que o dono disse, sem rede e sem conta — testa voz,
    interrupção e tela sem mandar nada para fora. O `claude -p` só roda quando o dono escolhe
    `s2 = "claude"`, e a tela diz `[nuvem]` ao lado do nome: nunca é padrão silencioso.
    """
    if configuracao.s2 == "eco":
        eco = RespostaDeEco()
        return MotorRoteirizado(
            resposta=lambda contexto: eco.responder(contexto.turno),
            nome="eco (repete o que você disse)",
        )
    pasta_de_trabalho.mkdir(parents=True, exist_ok=True)
    return MotorClaudeCli(pasta_de_trabalho=pasta_de_trabalho, modelo=configuracao.modelo_do_s2)


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
    escuta: Escuta | None = None
    """O modo de escuta **vivo** (ADR-0021): atalho, palavra de ativação ou contínua.

    Lido a cada tique, trocado de outra thread (a janela, o controlador) sem reiniciar a
    sessão. `None` monta um da configuração na primeira leitura — o terminal não precisa
    saber que isto existe."""
    ao_pedaco: Callable[[str], None] | None = None
    """A resposta **enquanto chega** (ADR-0025): o texto acumulado da resposta em curso, a cada
    pedaço de fala que o cérebro publica. A janela mostra em stream; o terminal não liga. Como
    as outras portas, é chamada da thread do laço."""
    texto_digitado: Callable[[], str | None] | None = None
    """Uma linha que o dono digitou, se houver. É consultada entre os quadros do laço de áudio.

    Digitar no meio do laço de voz é um turno como outro qualquer: mesmo epoch, mesma fila de
    playback, mesma interrupção. Fazer isso por fora (uma segunda thread chamando `responder`)
    daria dois donos do epoch — e dois donos do epoch é a origem do barge-in que não cancela."""

    ao_pedir_confirmacao: Callable[[Confirmacao], None] | None = None
    """A política mandou confirmar uma ferramenta (ADR-0028): a janela mostra o pedido. Não
    bloqueia — quem espera a resposta é o laço, em `_confirmar`. Sem janela, a resposta é não."""
    ao_fim_da_confirmacao: Callable[[str], None] | None = None
    """O pedido saiu (respondido, prazo vencido ou turno interrompido): a janela o tira."""
    avisos_dados: set[str] = field(default_factory=set)
    """Os avisos de privacidade que o dono já leu nesta execução. A janela passa o MESMO
    conjunto a cada conversa que abre: o texto longo sai uma vez ao ligar, e depois só vive no
    painel de Configuração (bug do dono, 2026-10-17: voltava a cada sessão, sujando a conversa)."""
    lar: Path = field(default_factory=Path.home)
    """A casa do dono, de onde saem as raízes do modo de acesso e a lista de negação (§5.5)."""
    ao_mudar_avisos: Callable[[], None] | None = None
    """A fila de avisos mudou (ADR-0025): a janela renova o card. Como `ao_mudar_estado`, é
    chamada da thread do laço — quem liga aqui emite sinal e volta."""
    ao_mudar_tarefas: Callable[[], None] | None = None
    """Uma tarefa em segundo plano mudou (ADR-0022): a janela renova o card `tarefas`. Chamada da
    linha da **tarefa**, não da do laço: quem liga aqui emite sinal e volta."""

    detector: DetectorDeEnderecamento | None = field(default=None, repr=False)
    """Diz, na escuta contínua, se a fala transcrita é para o Jarvis (ADR-0029). `None` = desligado
    (o padrão): todo trecho que o VAD abre segue virando pedido. Montado em `abrir` quando o dono
    escolheu e ligou o motor; injetável para o teste."""
    epoch: int = 1
    estado: Estado = Estado.PARADO
    session_id: str = field(default_factory=lambda: str(uuid7()))
    avisos: FilaDeAvisos = field(init=False)
    """A fila de avisos do laço, que aqui faz o papel do `agentd` (ADR-0025, regra 12)."""
    ferramentas: ExecutorDeFerramentas | None = field(default=None, repr=False)
    conversa: ConversaPersistente | None = field(default=None, repr=False)
    """A conversa que sobrevive ao reinício (ADR-0026). `None` = só na memória, como o terminal e
    a suíte sempre fizeram: quem quer persistir (a janela) passa uma aberta."""
    interruptor_de_entrada: Interruptor = field(init=False, repr=False)
    """O botão de parar do mouse e do teclado virtuais: a janela o aciona, e só ela o libera."""
    _entrada: tuple[tuple[bool], ControleDeEntrada] | None = field(default=None, repr=False)
    _auditoria: LogDeAuditoria | None = field(default=None, repr=False)
    _confirmacoes: dict[str, tuple[threading.Event, list[bool]]] = field(
        default_factory=dict, repr=False
    )
    turnos: list[Turno] = field(default_factory=list)
    _asr: MotorDeAsr | None = field(default=None, repr=False)
    _tts: MotorDeTts | None = field(default=None, repr=False)
    _motor: MotorDeConversa | None = field(default=None, repr=False)
    """O motor do cérebro. Trocável entre turnos: a conversa mora no `Cerebro`, não nele."""
    _cerebro: Cerebro | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.avisos = FilaDeAvisos(session_id=self.session_id)
        self.interruptor_de_entrada = Interruptor(self.raiz / "entrada")

    # --- avisos (ADR-0025) ---------------------------------------------------------------
    def receber_aviso(self, envelope: Envelope) -> None:
        """Um `Notification` entra na fila; a janela é avisada para renovar o card."""
        self.avisos.receber(envelope, time.monotonic())
        self._avisos_mudaram()

    def registrar_aviso(self, tipo: str, origem: str, resumo: str) -> None:
        """Aviso que nasce no próprio laço (a conversa caiu, o motor falhou). Vai **só para o
        card**: a frase já foi escrita na tela, e falar de novo seria repetir."""
        identificador = f"local-{uuid7()}"
        self.avisos.receber(
            notificacao(self.session_id, identificador, tipo=tipo, origem=origem, resumo=resumo),
            time.monotonic(),
        )
        self.avisos.decidido(identificador, Entrega.SO_CARD)
        self._avisos_mudaram()

    def _status_do_laco(self, resumo: str) -> None:
        """Progresso do encadeamento vai para a fila, nunca direto à fala em andamento."""
        self.receber_aviso(
            notificacao(
                self.session_id,
                f"raciocinio-{uuid7()}",
                tipo="evento",
                origem="raciocínio",
                resumo=resumo,
            )
        )

    def dados_dos_avisos(self) -> dict[str, list[dict[str, str]]]:
        """O que o card `notificacoes` mostra, no contrato `avisos` do componente."""
        return self.avisos.dados_do_card(time.monotonic())

    def _avisos_mudaram(self) -> None:
        if self.ao_mudar_avisos is not None:
            self.ao_mudar_avisos()

    # --- montagem -----------------------------------------------------------------------
    def cancelado_de(self, epoch: int) -> Callable[[], bool]:
        """A pergunta que todo mundo faz: "o epoch ainda é meu?" (ADR-0002, §3.3 regra 1)."""

        def cancelado() -> bool:
            return self.epoch > epoch

        return cancelado

    @property
    def modo_de_escuta(self) -> Escuta:
        """O estado vivo, montado da configuração na primeira vez que alguém pergunta."""
        if self.escuta is None:
            self.escuta = Escuta.de(
                self.configuracao.escuta,
                palavra=self.configuracao.palavra,
                limiar=self.configuracao.limiar_palavra,
                atalho=self.configuracao.atalho,
            )
        return self.escuta

    def _cancelado_agora(self) -> bool:
        return self.cancelado_de(self.epoch)()

    def _mudar(self, estado: Estado) -> None:
        """Muda o estado e avisa quem pediu para ser avisado. Sem mudança, sem aviso."""
        if estado is self.estado:
            return
        self.estado = estado
        # O piso da fila de avisos: enquanto o Jarvis fala, nenhum aviso sai por cima.
        self.avisos.tts_tocando(estado is Estado.FALANDO, time.monotonic())
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
                self._asr = self._abrir_o_ouvido(cancelado)
            if self._tts is None:
                self._tts = motor_de_tts(
                    self.configuracao, raiz=self.raiz, cancelado=cancelado, ambiente=self.ambiente
                )
        except (MotorRecusado, SegredoAusente, ErroDeRede) as erro:
            # As três recusas chegam ao dono como a mesma coisa — "não deu para começar, e
            # aqui está o porquê" —, porque para ele são: motor desligado, chave ausente e
            # nuvem proibida sob CI resolvem-se lendo a frase, não um traceback.
            raise AplicativoIndisponivel(str(erro)) from None
        if self._motor is None:
            self._motor = motor_de_conversa(
                self.configuracao, pasta_de_trabalho=self.raiz / "conversa"
            )
        if com_asr and self.detector is None and self.configuracao.enderecamento:
            self.detector = self._abrir_o_detector()
        if self._cerebro is None:
            self._cerebro = Cerebro(motor=self._motor, session_id=self.session_id)
            self._ligar_o_portao(self._cerebro)
        if self.ferramentas is None:
            self.ferramentas = self._montar_ferramentas()
        self._cerebro.ferramentas = self.ferramentas
        self._cerebro.confirmar = self._confirmar
        self._cerebro.ao_status = self._status_do_laco
        self._cerebro.maximo_de_passos = self.configuracao.laco_max_passos
        self._cerebro.prazo_do_laco_de_ferramentas_s = self.configuracao.laco_prazo_s
        self._sincronizar_conversa(self._cerebro)
        if self.ferramentas.tarefas is None:
            self.ferramentas.tarefas = self._montar_tarefas(self.ferramentas)
        self.ferramentas.portas().ambiente = self.ambiente
        self.ferramentas.portas().agenda = agenda_compartilhada(
            self.raiz / "area" / "alarmes.json", self._alarme_disparou
        )
        self._aquecer()

    def _alarme_disparou(self, alarme: Alarme) -> None:
        """Um lembrete venceu: entra pela fila de avisos (ADR-0025) — o Jarvis decide como dizê-lo,
        sem cortar fala — e também vira notificação do desktop, que chega mesmo com a janela
        escondida. O que venceu com o Jarvis fechado sai marcado como atrasado."""
        atraso = " (atrasado: venceu com o Jarvis fechado)" if alarme.atrasado else ""
        texto = alarme.mensagem + atraso
        self.receber_aviso(
            notificacao(
                self.session_id,
                f"alarme-{alarme.id}",
                tipo="evento",
                origem="lembrete",
                resumo=texto,
            )
        )
        if self.ferramentas is not None:
            with contextlib.suppress(Exception):  # sem notify-send, o aviso da fila basta
                desktop.notificar(self.ferramentas.portas().lancar, "Jarvis", texto)

    # --- tarefas em segundo plano (ADR-0022) ----------------------------------------------
    def _montar_tarefas(self, executor: ExecutorDeFerramentas) -> GestorDeTarefas:
        """O gestor de tarefas. O **motor** da tarefa é escolha do dono (`tarefa_motor`): o
        modelo pede a tarefa, nunca diz quem a conduz."""

        def catalogo() -> tuple[dict[str, Any], ...]:
            # O executor de agora: `atualizar_acesso` troca o executor e mantém este gestor.
            return (self.ferramentas or executor).catalogo_para_o_modelo()

        def fabrica() -> MotorDeTarefa:
            if self.configuracao.tarefa_motor == "agente" and self._motor is not None:
                return MotorDeAgente(motor=self._motor, catalogo=catalogo)
            return MotorDireto()

        return GestorDeTarefas(
            executor=executor,
            confirmar=self._confirmar_da_tarefa,
            fabrica_de_motor=fabrica,
            session_id=self.session_id,
            ao_mudar=self._tarefas_mudaram,
            ao_concluir=self._tarefa_concluida,
        )

    def _tarefas_mudaram(self) -> None:
        if self.ao_mudar_tarefas is not None:
            self.ao_mudar_tarefas()

    def dados_das_tarefas(self) -> dict[str, list[dict[str, str]]]:
        """O que o card `tarefas` mostra: nome, estado, progresso e o id do "parar"."""
        gestor = self.ferramentas.tarefas if self.ferramentas is not None else None
        return gestor.dados_do_card() if gestor is not None else {"itens": []}

    def parar_tarefa(self, tarefa_id: str) -> bool:
        """O botão "parar" do card — o dono, com o dedo, não passa pela política."""
        gestor = self.ferramentas.tarefas if self.ferramentas is not None else None
        if gestor is None or tarefa_id not in gestor.tarefas:
            return False
        gestor.cancelar(tarefa_id)
        return True

    def _tarefa_concluida(self, tarefa: Tarefa) -> None:
        """A conclusão entra pela fila de avisos (ADR-0025) como `Notification`: o Jarvis decide
        se fala e quando, sem cortar fala em andamento. O texto é **nosso** (a descrição e o
        estado), exceto o resumo de um motor `agente`, que é de terceiros e vem marcado."""
        if tarefa.estado is EstadoDaTarefa.CONCLUIDA:
            tipo, resumo = "concluida", f"a tarefa «{tarefa.descricao}» terminou"
            if tarefa.resumo and tarefa.de_terceiros:
                resumo += f": {tarefa.resumo}"
        elif tarefa.estado is EstadoDaTarefa.FALHOU:
            tipo, resumo = "falhou", f"a tarefa «{tarefa.descricao}» falhou: {tarefa.motivo}"
        else:
            tipo, resumo = "evento", f"a tarefa «{tarefa.descricao}» foi cancelada"
        self.receber_aviso(
            notificacao(
                self.session_id,
                f"tarefa-{tarefa.id}",
                tipo=tipo,
                origem=f"tarefa · {tarefa.descricao[:40]}",
                resumo=resumo,
                trust=Trust.THIRD_PARTY if tarefa.de_terceiros else Trust.SYSTEM,
            )
        )

    def _confirmar_da_tarefa(self, pergunta: Confirmacao, cancelada: Callable[[], bool]) -> bool:
        """O "sim" do dono para um passo perigoso de uma tarefa: a mesma faixa da conversa, mas a
        tarefa **espera sozinha** — o estado do núcleo e o epoch da fala não são dela."""
        return self._confirmar(pergunta, tarefa_cancelada=cancelada)

    def _cancelar_tarefas(self) -> None:
        if self._cerebro is not None:
            self._cerebro.pendencias.cancelar()
        gestor = self.ferramentas.tarefas if self.ferramentas is not None else None
        if gestor is not None:
            gestor.cancelar_todas()

    def _sincronizar_conversa(self, cerebro: Cerebro) -> None:
        """Põe no cérebro a conversa corrente do dono: o livro e os últimos turnos que ele ouviu.

        Roda ao abrir **e** a cada turno: "nova conversa" na janela troca o id de outra thread, e
        o cérebro só repara aqui — entre turnos, nunca no meio de um. O modelo lê o texto
        redigido (sem segredo nem dado pessoal); a tela mostra o original.
        """
        conversa = self.conversa
        if conversa is None or cerebro.id_da_conversa == conversa.conversa_id:
            return
        if not cerebro.id_da_conversa and conversa.aviso:
            self.escrever_na_tela(f"  {conversa.aviso}")
        cerebro.id_da_conversa = conversa.conversa_id
        cerebro.livro = conversa.livro
        cerebro.conversa.turnos[:] = [
            Mensagem("dono" if t.papel == "dono" else "jarvis", t.redigido, t.interrompida)
            for t in conversa.recentes()
        ]

    def _ligar_a_memoria(self, cerebro: Cerebro) -> None:
        """As tools `memoria.*` só existem para o modelo quando há livro (a persona manda usá-las
        quando o dono pede para lembrar), e o D20 precisa saber **qual** motor vai lê-las."""
        if self.ferramentas is None:
            return
        self.ferramentas.destino_onde = cerebro.motor.onde
        self.ferramentas.destino_motor = cerebro.motor.nome
        if cerebro.livro is not None and self.ferramentas.memoria is None:
            self.ferramentas.memoria = FerramentasDeMemoria(
                livro=cerebro.livro, alcance=cerebro.alcance_de_memoria
            )

    def _ligar_o_portao(self, cerebro: Cerebro) -> None:
        """O portão contextual (Jev) antes de cada ferramenta — com o mesmo classificador que o
        dono escolheu para o endereçamento. Sem ele, fica o caminho de antes (só o PDP).

        A pendência de confirmação aparece na mesma faixa da janela e vence sozinha no prazo."""
        cerebro.pendencias.ao_abrir = self._mostrar_pendencia
        cerebro.pendencias.ao_fechar = self._tirar_pendencia
        cerebro.pendencias.agendar = _agendar
        if cerebro.portao is not None or not self.configuracao.enderecamento:
            return
        classificador = self.detector.classificador if self.detector is not None else None
        if classificador is None:
            escolhido = self.configuracao.enderecamento
            if o_que_falta(escolhido, self.configuracao, ambiente=self.ambiente):
                return
            try:
                aberto = ClassificadorOpenRouter(
                    registrado=escolhido,
                    nuvem_ligada=self.configuracao.nuvem_ligada,
                    ambiente=self.ambiente,
                )
                aberto.abrir()
            except (MotorRecusado, SegredoAusente, ErroDeRede) as erro:
                self.escrever_na_tela(f"  (portão contextual das ferramentas desligado: {erro})")
                return
            classificador = aberto
        cerebro.portao = PortaoDeAcao(classificador=classificador)

    def _mostrar_pendencia(self, pergunta: Confirmacao) -> None:
        if self.ao_pedir_confirmacao is not None:
            self.ao_pedir_confirmacao(pergunta)
        else:
            self.escrever_na_tela(f"  (esperando o seu sim: {pergunta.detalhe})")

    def _tirar_pendencia(self, identificador: str) -> None:
        if self.ao_fim_da_confirmacao is not None:
            self.ao_fim_da_confirmacao(identificador)

    def _abrir_o_detector(self) -> DetectorDeEnderecamento | None:
        """O detector de endereçamento que o dono escolheu — ou `None`, com a razão na tela.

        Escolher o motor não o liga (ADR-0017): sem o interruptor do dono ou sem a chave, nada
        sai da máquina e a escuta contínua segue como era. Isso é dito, não calado: o dono
        pediu proteção contra fala alheia e tem de saber que ela não está valendo."""
        escolhido = self.configuracao.enderecamento
        falta = o_que_falta(escolhido, self.configuracao, ambiente=self.ambiente)
        if not falta:
            try:
                classificador = ClassificadorOpenRouter(
                    registrado=escolhido,
                    nuvem_ligada=self.configuracao.nuvem_ligada,
                    ambiente=self.ambiente,
                )
                classificador.abrir()
                return DetectorDeEnderecamento(classificador=classificador)
            except (MotorRecusado, SegredoAusente, ErroDeRede) as erro:
                falta = str(erro)
        frase = (
            f"o detector de endereçamento ({escolhido}) não está ativo: {falta}. Na escuta "
            "contínua todo trecho continua virando pedido."
        )
        self.escrever_na_tela(f"  {frase}")
        self.registrar_aviso("falhou", "endereçamento", frase)
        return None

    def _nomes_dos_apps(self) -> list[str]:
        """Os apps instalados (`.desktop`), pelo nome que o dono fala — dica para o ASR."""
        try:
            return [app.nome for app in listar_apps()]
        except OSError:  # sem pasta de apps legível, o ASR só perde a dica
            return []

    def _abrir_o_ouvido(self, cancelado: Callable[[], bool]) -> MotorDeAsr:
        """O ASR escolhido — ou, se ele é de nuvem e não roda, o local, com uma linha dizendo.

        Bug do dono (2026-10-17): com a Groq escolhida e desligada o laço desistia do áudio e
        caía no modo texto — sem microfone, sem ativação por voz, e o botão de falar sem o que
        fazer. A nuvem desligada é decisão do dono e continua valendo (nada sai daqui); o que
        não é decisão dele é ficar surdo por isso. O ASR local roda na máquina e não pede nada.
        """
        try:
            return motor_de_asr(
                self.configuracao,
                raiz=self.raiz,
                cancelado=cancelado,
                ambiente=self.ambiente,
                dicas_apps=self._nomes_dos_apps(),
            )
        except (OuvidoIndisponivel, MotorRecusado, SegredoAusente, ErroDeRede, ImportError) as erro:
            escolhido = motor_registrado(self.configuracao.asr)
            if escolhido is not None and escolhido.onde is Onde.NUVEM:
                try:
                    local = motor_de_asr(
                        self.configuracao.com(asr=ASR_PADRAO),
                        raiz=self.raiz,
                        cancelado=cancelado,
                        ambiente=self.ambiente,
                        dicas_apps=self._nomes_dos_apps(),
                    )
                except (AplicativoIndisponivel, MotorRecusado, ErroDeRede, ImportError):
                    local = None
                if local is not None:
                    self.escrever_na_tela(
                        f"  ouvindo pelo ASR local: {self.configuracao.asr} está desligado "
                        "(Configuração → Voz — ouvir)."
                    )
                    self.registrar_aviso(
                        "evento", "ouvir", f"{self.configuracao.asr} desligado: uso o ASR local"
                    )
                    return local
            if isinstance(erro, OuvidoIndisponivel):
                raise
            raise OuvidoIndisponivel(
                f"o ASR escolhido ({self.configuracao.asr}) não abriu: {erro}"
            ) from None

    def _montar_ferramentas(self) -> ExecutorDeFerramentas:
        """PDP, auditoria e executor com o alcance que o dono configurou (§5.5, ADR-0028)."""
        sistema = Sistema.WINDOWS if os.name == "nt" else Sistema.POSIX
        self._auditoria = LogDeAuditoria(self.raiz / "auditoria.sqlite")
        registro = RegistroDeApps.montar(
            self.configuracao.apps_autorizados,
            extras=self.configuracao.apps_extras,
            incluir_binarios_do_path=True,
            ambiente=self.ambiente,
            repositorio_de_aliases=RepositorioDeAliases.padrao(self.ambiente),
        )
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=self.lar,
            auditoria=self._auditoria,
            modo=ModoDeAcesso(self.configuracao.acesso),
            sistema=sistema,
            session_id=self.session_id,
            pasta_do_jarvis=self.raiz / "area",
            concedidas=tuple(
                Raiz(
                    nome="concedida",
                    caminho=canonicalizar(str(Path(r).expanduser()), sistema),
                    pode_ler=True,
                    pode_escrever=r in self.configuracao.raizes_escrita,
                )
                for r in self.configuracao.raizes
            ),
            apps_autorizados=frozenset(
                nome_de_app(n) for app in registro.autorizados.values() for n in app.nomes
            ),
            sites_sem_confirmar=frozenset(self.configuracao.sites_sem_confirmar),
            navegadores=frozenset(separar(self.configuracao.navegadores)),
            navegador_principal=self.configuracao.navegador_principal,
        )
        executor = ExecutorDeFerramentas(
            pdp=pdp,
            lar=self.lar,
            registro_de_apps=registro,
            sistema=sistema,
            navegadores=AbridorDeNavegador(
                navegadores=separar(self.configuracao.navegadores),
                principal=self.configuracao.navegador_principal,
                ambiente=self.ambiente,
            ),
            navegador=self._corpos_do_navegador(),
            estado_do_navegador=self.estado_do_navegador,
            entrada=self._controle_de_entrada(),
        )
        executor.preparar()
        return executor

    def _transporte_do_navegador(self) -> TransporteUnix:
        """O socket do host em `$XDG_RUNTIME_DIR` **deste** ambiente. Antes valia sempre o
        `os.environ` real: um teste podia falar com o navegador de verdade do dono."""
        return TransporteUnix.do_ambiente(ambiente_ou_os(self.ambiente))

    def _corpos_do_navegador(self) -> CorposDoNavegador | None:
        """As `browser.*` só existem se o dono ligou (`navegador_controlado`). O socket é o do host
        que o navegador lançou; sem navegador aberto, a tool diz isso em vez de falhar calada."""
        if not self.configuracao.navegador_controlado:
            return None
        cliente = ClienteDoNavegador(self._transporte_do_navegador())
        cliente.navegador = familia_do_host(self.configuracao.navegador_principal)
        return CorposDoNavegador(cliente)

    def estado_do_navegador(self) -> EstadoDaPonte:
        """O estado verdadeiro da ponte (`browser.estado`, `--diagnostico`): ligado ou não, com ou
        sem extensão conectada, e o que falta — sem falar com a extensão nem com a página."""
        return sondar(
            ligado=self.configuracao.navegador_controlado,
            principal=self.configuracao.navegador_principal,
            navegadores=separar(self.configuracao.navegadores),
            transporte=self._transporte_do_navegador(),
            home=self.lar,
        )

    def _controle_de_entrada(self) -> ControleDeEntrada | None:
        """Mouse e teclado virtuais só existem se o dono ligou (`entrada_virtual`). O controle é
        guardado: reconstruir o executor não reabre o diálogo do sistema nem solta a parada."""
        if not self.configuracao.entrada_virtual:
            return None
        chave = (self.configuracao.entrada_uinput,)
        if self._entrada is None or self._entrada[0] != chave:
            if self._entrada is not None:
                self._entrada[1].backend.fechar()
            ambiente = self.ambiente if self.ambiente is not None else os.environ
            backend = backend_do_ambiente(
                ambiente, uinput_liberado=self.configuracao.entrada_uinput
            )
            controle = ControleDeEntrada(
                backend=backend,
                foco=foco_do_ambiente(ambiente),
                interruptor=self.interruptor_de_entrada,
            )
            self.interruptor_de_entrada.ao_parar(backend.fechar)
            self._entrada = (chave, controle)
        return self._entrada[1]

    # --- confirmação de ferramenta (ADR-0028) -------------------------------------------------
    def atualizar_acesso(self, configuracao: Configuracao) -> None:
        """O dono mexeu em pastas, apps ou navegadores com a conversa aberta: vale já no próximo
        pedido, sem reiniciar o laço. Troca só o executor (PDP, registro e navegador); o resto
        da configuração — motores, voz, escuta — só muda na conversa seguinte."""
        self.configuracao = self.configuracao.com(
            acesso=configuracao.acesso,
            raizes=configuracao.raizes,
            raizes_escrita=configuracao.raizes_escrita,
            apps_autorizados=configuracao.apps_autorizados,
            apps_extras=configuracao.apps_extras,
            navegadores=configuracao.navegadores,
            navegador_principal=configuracao.navegador_principal,
            sites_sem_confirmar=configuracao.sites_sem_confirmar,
            navegador_controlado=configuracao.navegador_controlado,
            entrada_virtual=configuracao.entrada_virtual,
            entrada_uinput=configuracao.entrada_uinput,
        )
        if self._cerebro is None:
            return
        antigo, novo = self.ferramentas, self._montar_ferramentas()
        if antigo is not None:
            # Muda o alcance (PDP, registro, navegador); o que é da conversa fica. Antes o executor
            # novo nascia sem memória, tarefas e alarmes: mexer no acesso com a conversa aberta
            # sumia com as memoria.*, tarefa.* e timer.* e quebrava o "sim" das pendências
            # (bf9102c) até reiniciar. O gestor segue com as tarefas em curso e passa a usar o
            # executor novo — o PDP novo — já no próximo passo.
            novo.memoria = antigo.memoria
            novo.nativas = antigo.nativas
            novo.desfazeres = antigo.desfazeres
            novo.turno = antigo.turno
            novo.destino_onde = antigo.destino_onde
            novo.destino_motor = antigo.destino_motor
            if antigo.tarefas is not None:
                antigo.tarefas.executor = novo
                novo.tarefas = antigo.tarefas
        self.ferramentas = novo
        self._cerebro.ferramentas = novo

    def _confirmar(
        self, pergunta: Confirmacao, *, tarefa_cancelada: Callable[[], bool] | None = None
    ) -> bool:
        """Pede à janela e espera o dono — da linha do cérebro, sem travar a fala nem a tela.

        Não há "sim" sem o dono: sem janela, é não; prazo vencido, é não; o dono interrompeu o
        turno enquanto o pedido estava na tela, é não. E nada que o modelo escreva chega aqui:
        quem chama `responder_confirmacao` é o clique na janela.
        """
        if self.ao_pedir_confirmacao is None:
            self.escrever_na_tela(f"  (precisa da sua confirmação na janela: {pergunta.detalhe})")
            return False
        epoch = self.epoch
        da_tarefa = tarefa_cancelada is not None
        evento = threading.Event()
        resposta: list[bool] = []
        self._confirmacoes[pergunta.id] = (evento, resposta)
        # Enquanto a pergunta está na tela a vez é do dono: o núcleo não diz "falando" à toa.
        # (Pergunta de tarefa não mexe no núcleo: a conversa segue, e a tarefa espera sozinha.)
        if not da_tarefa:
            self._mudar(self._repouso)
        self.ao_pedir_confirmacao(pergunta)
        limite = time.monotonic() + pergunta.prazo_s
        try:
            while not evento.wait(INTERVALO_DE_CONSULTA_S * 10):
                if time.monotonic() > limite:
                    return False
                if tarefa_cancelada is not None:
                    if tarefa_cancelada():
                        return False
                elif self.epoch > epoch:
                    return False
            return bool(resposta and resposta[0])
        finally:
            if not da_tarefa and self.epoch == epoch:
                self._mudar(Estado.PENSANDO)
            self._confirmacoes.pop(pergunta.id, None)
            if self.ao_fim_da_confirmacao is not None:
                self.ao_fim_da_confirmacao(pergunta.id)

    def responder_confirmacao(self, identificador: str, sim: bool) -> bool:
        """O clique do dono na janela. Devolve se ainda havia alguém esperando a resposta."""
        espera = self._confirmacoes.get(identificador)
        if espera is None:
            # Pendência do portão contextual: não há linha esperando; o clique a resolve aqui.
            cerebro = self._cerebro
            return cerebro is not None and cerebro.resolver_pendencia(identificador, sim)
        evento, resposta = espera
        resposta.append(sim)
        evento.set()
        return True

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
        """Texto → cérebro em stream → áudio no sumidouro, falando enquanto o motor gera.

        O cérebro (`jarvis.s2.cerebro`, ADR-0025) roda numa linha de execução própria e publica
        um pedaço de fala por fronteira; este laço — que é o dono do epoch e da fila — sintetiza
        e toca cada pedaço assim que ele chega, olhando o teclado entre os quadros. A barra (ou
        o "parar" da janela) mata o epoch: o cérebro para de publicar e fecha o motor, a fila
        descarta o que não tocou, e a conversa guarda só o que o dono ouviu.
        """
        if self._tts is None or self._motor is None or self._cerebro is None:
            # Só o que este caminho usa: responder não transcreve nada.
            self.abrir(com_asr=False)
        assert self._tts is not None and self._motor is not None and self._cerebro is not None
        cerebro = self._cerebro
        cerebro.motor = self._motor
        self._sincronizar_conversa(cerebro)
        self._ligar_a_memoria(cerebro)

        epoch = self.epoch
        self._turno_cancelado = False
        cancelado = self.cancelado_de(epoch)
        parar_geracao = threading.Event()

        def geracao_cancelada() -> bool:
            return parar_geracao.is_set() or cancelado()

        self._mudar(Estado.PENSANDO)
        comeco = time.monotonic()
        pedacos: queue.Queue[dict[str, object] | None] = queue.Queue(
            maxsize=MAXIMO_DE_SINTESES_PENDENTES
        )
        resultado: dict[str, Resposta] = {}
        falha: list[str] = []
        exibido: list[str] = []
        primeiro_texto_ms: list[float] = []

        def colocar_no_stream(pedaco: dict[str, object] | None) -> bool:
            while not geracao_cancelada():
                try:
                    pedacos.put(pedaco, timeout=INTERVALO_DE_CONSULTA_S)
                    return True
                except queue.Full:
                    continue
            return False

        def publicar(pedaco: dict[str, object]) -> None:
            """Na linha do cérebro, no instante em que o pedaço nasce: a tela segue a geração.

            Antes isto ficava no gerador que o tocador consome, e o tocador só puxa o pedaço
            seguinte depois de **tocar** o anterior — o texto aparecia no ritmo da fala (um
            pedaço por segundo, achado do dono em 2026-10-17), embora a resposta estivesse pronta
            em milissegundos. O que o dono ouve continua sendo o que o tocador consome."""
            if not colocar_no_stream(pedaco):
                return
            if pedaco["text"] and not geracao_cancelada():
                if not primeiro_texto_ms:
                    primeiro_texto_ms.append((time.monotonic() - comeco) * 1000.0)
                exibido.append(str(pedaco["text"]))
                if self.ao_pedaco is not None:
                    self.ao_pedaco(" ".join(exibido))

        def gerar() -> None:
            try:
                resultado["r"] = cerebro.responder(
                    texto, epoch=epoch, publicar=publicar, cancelado=geracao_cancelada
                )
            except Exception as erro:  # o turno degrada e diz; a linha não leva o laço junto
                falha.append(f"{type(erro).__name__}: {erro}")
            finally:
                colocar_no_stream(None)

        linha = threading.Thread(target=gerar, name="jarvis-cerebro", daemon=True)
        linha.start()

        def do_cerebro() -> Iterator[dict[str, object]]:
            while True:
                if geracao_cancelada():
                    return
                try:
                    pedaco = pedacos.get(timeout=INTERVALO_DE_CONSULTA_S)
                except queue.Empty:
                    if geracao_cancelada():
                        return
                    continue
                if pedaco is None or geracao_cancelada():
                    return
                yield pedaco

        try:
            fala, turno = self._tocar(
                trechos_do_stream(do_cerebro(), epoch=epoch), epoch=epoch, fila=fila
            )
        finally:
            # Recusa da fila ou erro na síntese também precisam acordar publicar() quando
            # o produtor está bloqueado, mesmo sem alteração do epoch local.
            parar_geracao.set()
            linha.join(timeout=ESPERA_DO_CEREBRO_S)
        resposta = resultado.get("r")
        if falha or (
            resposta is not None and resposta.fim in (MotivoDoFim.ERRO, MotivoDoFim.PRAZO)
        ):
            motivo = falha[0] if falha else (resposta.detalhe if resposta else "")
            self.escrever_na_tela(f"  (sem resposta: {motivo or 'o motor não disse por quê'})")
            self.registrar_aviso(
                "falhou", f"cérebro · {self._motor.nome}", f"sem resposta: {motivo}"
            )
        if resposta is not None:
            tocadas = turno.amostras_tocadas
            cerebro.ouvido(
                resposta.response_id,
                fala.texto_ate(tocadas),
                interrompida=turno.cancelado,
                played_ms=int(1000 * tocadas / TAXA_PADRAO),
            )
        if self.conversa is not None:
            self.conversa.indexar_depois()
        self._mudar(self._repouso)
        respondeu = " ".join(exibido)
        return Turno(
            falou=texto,
            respondeu=respondeu,
            resposta_ms=primeiro_texto_ms[0] if primeiro_texto_ms else 0.0,
            primeiro_pedaco_ms=turno.primeiro_pedaco_ms,
            contexto_ms=resposta.ms_ate_contexto if resposta is not None else 0.0,
            primeiro_token_ms=(resposta.ms_ate_primeiro_token or 0.0) if resposta else 0.0,
            tts_ms=turno.tts_ms,
            amostras_tocadas=turno.amostras_tocadas,
            cancelado=cancelado() or turno.cancelado or not respondeu,
            epoch=epoch,
        )

    def falar(self, texto: str, *, epoch: int, fila: FilaDePlayback | None = None) -> Turno:
        """Sintetiza e entrega um texto pronto, parando no cancelamento (contrato do F1-09)."""
        return self._tocar(iter(fatiar(texto)), epoch=epoch, fila=fila, texto=texto)[1]

    def _tocar(
        self,
        trechos: Iterator[tuple[int, str]],
        *,
        epoch: int,
        fila: FilaDePlayback | None,
        texto: str | None = None,
    ) -> tuple[Fala, Turno]:
        """Antecipa os próximos trechos e toca em ordem, olhando o teclado entre os quadros.

        O estado vira `falando` no **primeiro pedaço de áudio** pronto — não antes: entre o fim
        da fala do dono e esse pedaço, o Jarvis está pensando, e a tela diz isso. Enquanto um
        pedaço toca, o agendador compartilhado pode sintetizar os próximos sem bloquear esta
        linha; a fila de playback continua sendo a autoridade da ordem e do epoch.
        """
        assert self._tts is not None
        if self.epoch == epoch:
            self._mudar(Estado.PENSANDO)
        sintetizador = SintetizadorEmStreaming(
            motor=self._tts,
            session_id=self.session_id,
            epoch=epoch,
            cancelado=self.cancelado_de(epoch),
            ao_esperar=self._olhar_o_teclado,
        )
        textos: list[str] = []

        def anotando() -> Iterator[tuple[int, str]]:
            try:
                for inicio, trecho in trechos:
                    textos.append(trecho)
                    yield inicio, trecho
            finally:
                fechar = getattr(trechos, "close", None)
                if fechar is not None:
                    fechar()

        comeco = time.monotonic()
        primeiro: float = 0.0
        tocadas = 0
        tocados: list[Pedaco] = []
        mapa: list[Trecho] = []
        recusado = False
        fluxo = sintetizador.pedacos_do_stream(anotando())
        try:
            for pedaco, trecho in fluxo:
                if primeiro == 0.0:
                    primeiro = (time.monotonic() - comeco) * 1000.0
                    self._mudar(Estado.FALANDO)
                if fila is None:
                    # Sem fila (modo texto sem áudio), o que se mede é a síntese: o pedaço conta
                    # como produzido, e fica claro no relatório que ninguém o tocou.
                    tocadas += pedaco.n_amostras
                    tocados.append(pedaco)
                    mapa.append(trecho)
                    self._olhar_o_teclado()
                    if self.epoch > epoch:
                        break
                    continue
                if not fila.enfileirar(pedaco):
                    recusado = True
                    break
                tocados.append(pedaco)
                mapa.append(trecho)
                # Drena o pedaço quadro a quadro, olhando o teclado entre eles: é aqui que a
                # barra interrompe **no meio** do pedaço, e não só entre pedaços.
                while fila.pedacos_na_fila and self.epoch == epoch:
                    antes = fila.sumidouro.amostras_consumidas
                    fila.tick()
                    tocadas += fila.sumidouro.amostras_consumidas - antes
                    self._olhar_o_teclado()
                if self.epoch > epoch:
                    break
        finally:
            fechar = getattr(fluxo, "close", None)
            if fechar is not None:
                fechar()
            if fila is not None and self.epoch > epoch:
                # Vale também durante a espera pelo primeiro áudio, sem entrar no playback.
                fila.cancelar(reason="barge_in", epoch_novo=self.epoch)
        cancelado = self.epoch > epoch or recusado
        fala = Fala(
            texto=texto if texto is not None else " ".join(textos),
            pedacos=tuple(tocados),
            trechos=tuple(mapa),
            cancelada_em=len(tocados) if cancelado else None,
        )
        return fala, Turno(
            falou="",
            respondeu=fala.texto,
            primeiro_pedaco_ms=primeiro,
            tts_ms=(time.monotonic() - comeco) * 1000.0,
            amostras_tocadas=tocadas,
            cancelado=cancelado,
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
        if tecla == ESPACO and (
            self.estado in (Estado.FALANDO, Estado.PENSANDO) or bool(self._confirmacoes)
        ):
            # Barge-in por tecla só vale com o Jarvis falando (ou preparando a fala, ou esperando
            # a confirmação do dono). Com ele
            # calado o mesmo aperto é o PTT do dono abrindo o turno: tratá-lo como interrupção
            # era o "interrompe sozinho" da janela (bug do dono, 2026-10-17) — a época subia a
            # cada aperto e a conversa dizia "interrompido (tecla)" sem ninguém ter sido calado.
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
        sumidouro = self._abrir_a_saida_do_texto()
        fila = (
            FilaDePlayback(sumidouro=sumidouro, session_id=self.session_id, epoch_atual=self.epoch)
            if sumidouro is not None
            else None
        )
        try:
            for linha in linhas:
                texto = linha.strip()
                if not texto:
                    continue
                if texto in {"/sair", "/quit", "/q"}:
                    break
                turno = self.responder(texto, fila=fila)
                self.turnos.append(turno)
                if turno.respondeu:
                    self.escrever_na_tela(f"Jarvis: {turno.respondeu}")
                self.escrever_na_tela(turno.resumo())
        finally:
            self._cancelar_tarefas()
            if sumidouro is not None:
                sumidouro.fechar()
        self._mudar(Estado.PARADO)
        return 0

    def _abrir_a_saida_do_texto(self) -> SumidouroDeAudio | None:
        """O alto-falante (ou o WAV) do modo texto — ou `None`, que é só medir a síntese.

        Foi a falta disto que calou a janela em 2026-10-17: o modo texto, onde a janela cai
        quando o ASR escolhido não roda, sintetizava a resposta e a jogava fora. Sem placa de som
        a frase diz o que faltou e o texto continua; ninguém fica achando que o som saiu.
        """
        backend = backend_escolhido(self.ambiente, de_produto=True)
        if backend is Backend.SINTETICO or (
            backend is Backend.ARQUIVO and self.caminho_de_saida is None
        ):
            return None
        try:
            sumidouro = sumidouro_do_ambiente(
                caminho=self.caminho_de_saida,
                ambiente=self.ambiente,
                de_produto=True,
                dispositivo=dispositivo_pedido(self.configuracao.saida),
            )
            sumidouro.abrir()
        except ErroDeAudio as erro:
            self.escrever_na_tela(f"  sem som: {erro}")
            return None
        self.escrever_na_tela(f"  som por: {sumidouro.device_id}")
        return sumidouro

    # --- modo áudio ----------------------------------------------------------------------
    def rodar_audio(self, *, limite_de_turnos: int | None = None, vad: Vad | None = None) -> int:
        """O laço de voz. Fecha o turno por silêncio (VAD) ou pela barra (PTT)."""
        self.abrir()
        self._dizer_o_que_esta_ligado()
        fonte = fonte_do_ambiente(
            relogio=self.relogio,
            caminho=self.caminho_de_entrada,
            ambiente=self.ambiente,
            de_produto=True,
            dispositivo=dispositivo_pedido(self.configuracao.entrada),
        )
        sumidouro = sumidouro_do_ambiente(
            caminho=self.caminho_de_saida,
            ambiente=self.ambiente,
            de_produto=True,
            dispositivo=dispositivo_pedido(self.configuracao.saida),
        )
        captura = Captura(
            fonte=fonte, relogio=self.relogio, session_id=self.session_id, epoch=self.epoch
        )
        if vad is not None:
            captura.detector = vad
        elif backend_escolhido(self.ambiente, de_produto=True) is Backend.DISPOSITIVO:
            # Microfone de verdade: o VAD do produto (silero, com histerese) e não o limiar cru
            # de energia do banco de teste, que dispara tarde, no meio da primeira palavra.
            captura.detector = vad_do_ambiente()
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
        # Os últimos quadros ANTES de o VAD disparar: a fala começa antes de o VAD notar, e sem
        # isto o turno perdia o começo ("Jarvis, que horas são" chegava ao ASR como "que hoje
        # são", e a palavra de ativação nunca era ouvida — bug do dono, 2026-10-17).
        antes_da_fala: deque[bytes] = deque(maxlen=QUADROS_ANTES_DA_FALA)
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
                        audio = bytearray(b"".join(antes_da_fala))
                        antes_da_fala.clear()
                        if fila.pedacos_na_fila:
                            self.interromper("barge_in")
                            fila.cancelar(reason="barge_in", epoch_novo=self.epoch)
                    silencio_ms = 0.0
                    audio.extend(quadro.amostras)
                elif falando:
                    silencio_ms += 20.0
                    audio.extend(quadro.amostras)
                    # No atalho o fim do turno é o dedo saindo do botão: esperar 700 ms de
                    # silêncio ali seria cobrar do dono um silêncio que ele já declarou. Nos
                    # outros dois quem fecha é o silêncio, mesmo com a porta do dedo ligada —
                    # o modo troca com a sessão aberta, e a porta fica.
                    fechou = self._pelo_dedo or silencio_ms >= SILENCIO_PARA_FECHAR_O_TURNO_MS
                    if fechou:
                        falando = False
                        turnos += 1
                        self._turno_de_audio(bytes(audio), transcritor, fila)
                        audio = bytearray()
                if not falando and not self._pelo_dedo:
                    antes_da_fala.append(quadro.amostras)
                _ = eventos
                if len(audio) > MAXIMO_DE_AUDIO_POR_TURNO_S * TAXA_PADRAO * BYTES_POR_AMOSTRA:
                    falando = False
                    turnos += 1
                    self._turno_de_audio(bytes(audio), transcritor, fila)
                    audio = bytearray()
        finally:
            self._cancelar_tarefas()
            self._publicar_estado(captura, aberta=False)
            captura.fechar()
            sumidouro.fechar()
            self._escutando = False
            self._mudar(Estado.PARADO)
        return 0

    @property
    def _pelo_dedo(self) -> bool:
        """Quem decide é o dedo: modo atalho **e** uma porta de tecla ligada (a janela).

        Sem a porta (o terminal, que não tem tecla solta) o atalho cai no VAD, como sempre
        foi."""
        return self.pressionado is not None and self.modo_de_escuta.modo is ModoDeEscuta.ATALHO

    def _quer_falar(self, captura: Captura) -> bool:
        """Quem diz que o dono está falando: o dedo dele (atalho na janela) ou o VAD."""
        if self._pelo_dedo:
            assert self.pressionado is not None
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
            if self.modo_de_escuta.modo is ModoDeEscuta.PALAVRA:
                # Esperando a chamada, ruído que não vira texto é o caso comum: avisar a cada
                # um encheria a tela de "não entendi" enquanto a TV fala.
                self.modo_de_escuta.descartar()
            else:
                self.escrever_na_tela("  (não entendi nada nesse trecho)")
            self._mudar(self._repouso)
            return
        if not self._enderecada_ao_jarvis(hipotese.texto):
            self._mudar(self._repouso)
            return
        pedido = self._pedido_do_trecho(hipotese.texto)
        if pedido is None:
            self._mudar(self._repouso)
            return
        self.escrever_na_tela(f"Você: {pedido}")
        turno = self.responder(pedido, fila=fila)
        completo = Turno(
            falou=pedido,
            respondeu=turno.respondeu,
            ouvido_ms=ouvido_ms,
            asr_ms=asr_ms,
            resposta_ms=turno.resposta_ms,
            primeiro_pedaco_ms=turno.primeiro_pedaco_ms,
            tts_ms=turno.tts_ms,
            contexto_ms=turno.contexto_ms,
            primeiro_token_ms=turno.primeiro_token_ms,
            amostras_tocadas=turno.amostras_tocadas,
            cancelado=turno.cancelado,
            epoch=turno.epoch,
        )
        self.turnos.append(completo)
        if completo.respondeu:
            self.escrever_na_tela(f"Jarvis: {completo.respondeu}")
        self.escrever_na_tela(completo.resumo())

    def _enderecada_ao_jarvis(self, texto: str) -> bool:
        """O detector de endereçamento (ADR-0029), só na escuta contínua e só se o dono o ligou.

        Na dúvida, **não age**; e a fala ignorada não aparece na tela nem no histórico (como na
        palavra de ativação): só a linha de método — a decisão, a probabilidade e o tempo."""
        if self.detector is None or self.modo_de_escuta.modo is not ModoDeEscuta.CONTINUA:
            return True
        anterior = self.turnos[-1].respondeu.rstrip() if self.turnos else ""
        decisao = self.detector.avaliar(
            texto, jarvis_perguntou=anterior.endswith("?"), cancelado=self._cancelado_agora
        )
        if decisao.agir:
            self.escrever_na_tela(f"  ({decisao.frase()})")
            return True
        if decisao.motivo is Motivo.FORA_DO_AR:
            if self.detector.falhas == 1 or self.detector.falhas % 10 == 0:
                self.registrar_aviso(
                    "falhou",
                    "endereçamento",
                    f"o detector não respondeu ({decisao.detalhe}); ignorei a fala, na dúvida "
                    "não ajo — fale de novo, ou use o atalho",
                )
        else:
            self.modo_de_escuta.descartar()
        return False

    def _pedido_do_trecho(self, texto: str) -> str | None:
        """O que vira pedido neste trecho — ou `None`, que é descartar (ADR-0021).

        Fora do modo `palavra`, o trecho inteiro. No modo `palavra`:

        - **armado** (ele disse só o nome há pouco): o trecho inteiro é o pedido;
        - **com a chamada e um pedido**: só o pedido, sem o nome ("jarvis, que horas são" e
          "que horas são, jarvis" pedem a mesma coisa);
        - **só o nome**: arma por alguns segundos e diz na tela;
        - **sem a chamada**: descarta. Sem resposta, sem histórico, e **sem o texto na tela** —
          fala que não era para o Jarvis não fica registrada em lugar nenhum; só a contagem de
          descartados sobe, para o indicador dizer que ouviu e não era com ele.
        """
        escuta = self.modo_de_escuta
        if escuta.modo is not ModoDeEscuta.PALAVRA:
            return texto
        agora = self.relogio.mono_ns()
        armado = escuta.armado(agora)
        achado = escuta.detector.achar(texto)
        if achado is None and not armado:
            escuta.descartar()
            return None
        if achado is not None and achado.so_o_nome:
            escuta.armar(agora)
            self.escrever_na_tela(f"  (ouvi “{achado.ouvido}”: pode falar)")
            return None
        escuta.desarmar()
        return achado.comando if achado is not None else texto

    def _publicar_estado(self, captura: Captura, *, aberta: bool) -> None:
        """O indicador do F1-13: o que a fonte **está** fazendo, não o que a tela quer."""
        escrever_estado(
            self.raiz,
            EstadoDaFonte(
                aberta=aberta and captura.aberta,
                amostras=captura.amostras_capturadas if aberta else 0,
                amostras_totais=captura.amostras_capturadas,
                device_id=captura.fonte.device_id if aberta else None,
                modo=Modo.PTT if self.modo_de_escuta.modo is ModoDeEscuta.ATALHO else Modo.ESCUTA,
            ),
        )

    def _dizer_o_que_esta_ligado(self) -> None:
        """Antes do primeiro turno, o dono lê o que está ligado — inclusive o que sai daqui."""
        assert self._tts is not None and self._motor is not None
        if self._asr is None:
            self.escrever_na_tela("ouvindo com: (modo texto — o microfone não entra aqui)")
        else:
            self.escrever_na_tela(f"ouvindo com: {self._asr.nome}  [{self._asr.onde}]")
        self.escrever_na_tela(f"falando com: {self._tts.nome}  [{self._tts.onde}]")
        self.escrever_na_tela(f"respondendo com: {self._motor.nome}  [{self._motor.onde}]")
        if self.ferramentas is not None:
            modo = self.ferramentas.pdp.modo
            self.escrever_na_tela(
                f"alcance: {modo.nome_do_dono} · {len(self.ferramentas.catalogo_para_o_modelo())}"
                " ferramentas"
            )
        for motor in self.configuracao.motores_de_nuvem_escolhidos():
            ligado = motor.id in self.configuracao.nuvem_ligada
            chave = f"{'ligado' if ligado else 'desligado'}:{motor.id}"
            if chave in self.avisos_dados:
                continue  # já dito nesta execução; o painel de Configuração guarda o texto
            self.avisos_dados.add(chave)
            self.escrever_na_tela("")
            if ligado:
                self.escrever_na_tela(f"  {motor.frase_de_aviso}")
            else:
                # Escolhido e desligado não manda nada para fora: dizer "o seu áudio sai"
                # aqui era mentira (bug do dono, 2026-10-16).
                self.escrever_na_tela(
                    f"  {motor.id} está escolhido e DESLIGADO: nada sai daqui, e ele não roda."
                )
        self.escrever_na_tela("")


def _agendar(segundos: float, funcao: Callable[[], None]) -> None:
    """A pendência vence sozinha (e a faixa some) mesmo sem ninguém falar."""
    relogio = threading.Timer(segundos, funcao)
    relogio.daemon = True
    relogio.start()
