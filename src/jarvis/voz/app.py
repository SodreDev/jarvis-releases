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
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from jarvis.agentd.asr import MotorWhisper, TranscritorIncremental
from jarvis.agentd.fala_em_stream import trechos_do_stream
from jarvis.agentd.fila_de_avisos import ORIGEM_DO_PEDIDO, Entrega, FilaDeAvisos, notificacao
from jarvis.agentd.tts import (
    Fala,
    MotorParametrico,
    MotorPiperOnnx,
    SintetizadorEmStreaming,
    Trecho,
    fatiar,
)
from jarvis.ambiente import ambiente_ou_os, em_ci
from jarvis.apps.resolvedor import RepositorioDeAliases
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
from jarvis.executor.ferramentas import Confirmacao, Encerramento, ExecutorDeFerramentas
from jarvis.executor.janelas import focar_o_navegador, janelas_do_ambiente
from jarvis.executor.lancador import RegistroDeApps
from jarvis.executor.navegadores import AbridorDeNavegador, navegador_em_execucao, separar
from jarvis.memoryd.conversa import ConversaPersistente
from jarvis.memoryd.ferramentas import FerramentasDeMemoria
from jarvis.microfone import EstadoDaFonte, Modo, escrever_estado
from jarvis.navegador.cliente import (
    ClienteDoNavegador,
    NavegadorIndisponivel,
    TransporteUnix,
    familia_do_host,
)
from jarvis.navegador.estado import EstadoDaPonte, sondar
from jarvis.navegador.ferramentas import CorposDoNavegador
from jarvis.politica.abertura import nome_de_app
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.canonicalizacao import Sistema, canonicalizar
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo as ModoDeAcesso
from jarvis.politica.modos import Raiz
from jarvis.politica.objetivo import Objetivo
from jarvis.politica.pdp import Pdp
from jarvis.rede import ErroDeRede
from jarvis.relogio import Relogio, RelogioDoSistema
from jarvis.s2.avisos import FALAR, AvisoLiberado, decidir_entrega, frase_do_aviso
from jarvis.s2.cerebro import Cerebro, Resposta
from jarvis.s2.entrega import so_o_novo
from jarvis.s2.motor import (
    INTERVALO_DE_CONSULTA_S,
    Mensagem,
    MotivoDoFim,
    MotorDeConversa,
    aceita_imagem,
)
from jarvis.s2.motor_claude_cli import MotorClaudeCli
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.s2.orcamento_da_fala import orcar, quer_detalhe
from jarvis.s2.persona import sistema_do_jarvis
from jarvis.s2.portao import PortaoDeAcao, RespostaDoDono, resposta_literal
from jarvis.s2.protocolo import sem_protocolo
from jarvis.s2.regras import Regras, na_pasta
from jarvis.s2.regras import padrao as padrao_das_regras
from jarvis.tarefas.gestor import (
    EstadoDaTarefa,
    GestorDeTarefas,
    MotorDeTarefa,
    MotorDireto,
    Tarefa,
    TarefaRecusada,
)
from jarvis.tarefas.motores import MotorDeAgente
from jarvis.trilha import TrilhaDeDiagnostico
from jarvis.voz.chaves import SegredoAusente
from jarvis.voz.config import ASR_PADRAO, TTS_OMNIVOICE, TTS_PADRAO, Configuracao
from jarvis.voz.dica import dica_do_asr
from jarvis.voz.escuta import Escuta, ModoDeEscuta
from jarvis.voz.estado import Estado
from jarvis.voz.interface import MotorDeAsr, MotorDeTts, Onde, Sinais, transcrever_com_sinais
from jarvis.voz.interrupcao import Acao as AcaoDaVigia
from jarvis.voz.interrupcao import VigiaDeInterrupcao, so_ordem_de_parar
from jarvis.voz.prontidao import o_que_falta
from jarvis.voz.registro import MotorRecusado, motor_registrado
from jarvis.voz.ruido import (
    MedidaDoTrecho,
    PoliticaDeRuido,
    julgar_audio,
    julgar_texto,
    medir_trecho,
    palavras_da_dica,
    sinais_fortes,
    so_cortesia,
)
from jarvis.voz.ruido import Motivo as MotivoDoRuido
from jarvis.voz.s2_provisorio import RespostaDeEco
from jarvis.voz.teclado import ESPACO, TECLAS_DE_SAIDA, Teclado, TecladoMudo
from jarvis.voz.vocabulario import VAZIO, RepositorioDoVocabulario, Vocabulario

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
PASTA_DA_TRILHA: Final = "diagnostico"
"""Dentro da pasta da sessão: `turnos.jsonl` da trilha de diagnóstico (`jarvis.trilha`)."""
PREFIXO_DA_PERGUNTA: Final = "pergunta-"
"""O `notif_id` do aviso que leva à voz a pergunta de uma tarefa: o resto é o id da pendência."""
ERRO_CRU: Final = r"^[A-Z]\w*(?:Error|Exception)\b"
"""O motivo que é nome de exceção (a tarefa caiu num erro inesperado): não vai cru para a voz."""
MOTOR_DO_FOCO: Final = "foco"
"""A tarefa que só acompanha o foco de um app aberto (ADR-0037): encerrar não perde nada dela."""
QUADROS_POR_PUBLICACAO: Final = 25
"""Com o Jarvis falando, o indicador do microfone é renovado a cada meio segundo (ADR-0040)."""


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
    dica: str = "",
) -> MotorDeAsr:
    """O motor de ASR que a configuração pediu, já pelo portão (ADR-0017).

    `dica` é o texto que vai antes do áudio — a palavra de ativação e os termos do dono, montados
    por `jarvis.voz.dica` —, nos dois motores: `initial_prompt` no local, `prompt` na Groq. Curta de
    propósito (ADR-0043): a lista de apps instalados que ia aqui fazia ruído virar nome de app; quem
    casa a fala com o app é o resolvedor de `jarvis.apps`, contra o registro, depois do ASR."""
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
            dica=dica,
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
        dica=dica,
    )
    local.abrir()
    return local


def _aquecer_em_segundo_plano(*motores: object) -> None:
    """A conexão com a nuvem aberta no começo da sessão, numa linha à parte (2026-10-21, ADR-0045):
    o primeiro pedido não paga DNS, TCP e TLS. Motor sem `aquecer` (local, falso) fica de fora;
    falhar aqui não muda nada — o pedido abre a dele, como antes."""
    for motor in motores:
        aquecer = getattr(motor, "aquecer", None)
        if callable(aquecer):
            threading.Thread(
                target=_sem_falhar, args=(aquecer,), name="jarvis-aquecer", daemon=True
            ).start()


def _sem_falhar(funcao: Callable[[], object]) -> None:
    with contextlib.suppress(Exception):
        funcao()


def motor_de_tts(
    configuracao: Configuracao,
    *,
    raiz: Path,
    cancelado: Callable[[], bool],
    ambiente: Mapping[str, str] | None = None,
) -> MotorDeTts:
    """O motor de TTS que a configuração pediu, já pelo portão (ADR-0017)."""
    if configuracao.tts == TTS_OMNIVOICE:
        # Uso pessoal (ADR-0039): sem a declaração, a instalação, a voz cadastrada — ou com
        # erro no meio —, fala o motor padrão, sem derrubar a abertura e sem anunciar erro em
        # voz. O motivo vai em `observacao`, que a tela de abertura mostra.
        from jarvis.voz.omnivoice import motor_omnivoice

        return motor_omnivoice(
            aceito=configuracao.omnivoice_uso_pessoal,
            voz=configuracao.voz_omnivoice,
            cancelado=cancelado,
            ambiente=ambiente,
            reserva=lambda: motor_de_tts(
                configuracao.com(tts=TTS_PADRAO), raiz=raiz, cancelado=cancelado, ambiente=ambiente
            ),
        )
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
    ao_mudar_navegador: Callable[[bool], None] | None = None
    """O Jarvis passou a controlar (ou soltou) alguma aba do navegador (ADR-0027 regra 4): a janela
    mostra o botão de parar. Chamada da linha que agiu ou da vigia do controle: emite e volta."""

    detector: DetectorDeEnderecamento | None = field(default=None, repr=False)
    """Diz, na escuta contínua, se a fala transcrita é para o Jarvis (ADR-0029). `None` = desligado
    (o padrão): todo trecho que o VAD abre segue virando pedido. Montado em `abrir` quando o dono
    escolheu e ligou o motor; injetável para o teste."""
    encerrado: bool = False
    """O laço acabou porque o dono pediu para encerrar o Jarvis (`jarvis.encerrar`, ADR-0041): quem
    o rodou (a janela) fecha tudo, em vez de só parar a conversa."""
    vocabulario: RepositorioDoVocabulario | None = field(default=None, repr=False)
    """O vocabulário do dono (ADR-0044), em `~/.config/jarvis/`: os nomes que ele quer ouvidos e
    falados certo — vão na dica do ASR, corrigem a transcrição e mudam a pronúncia do TTS. `None` =
    sem vocabulário, que é o caso da suíte (ela nunca lê a pasta do dono): quem monta o laço de
    produção (a janela, o `jarvis-voz`) passa o repositório."""
    regras: Regras | None = field(default=None, repr=False)
    """As regras de comportamento que valem nesta sessão (ADR-0047), lidas em `abrir`."""
    _vocabulario_lido: Vocabulario = field(default=VAZIO, repr=False)
    _vocabulario_carregado: bool = field(default=False, repr=False)
    vigia: VigiaDeInterrupcao | None = field(default=None, repr=False)
    """Ouve o dono enquanto o Jarvis fala, para ele interromper por voz (ADR-0040): na palavra de
    ativação e na escuta contínua. Montada em `rodar_audio` (`interromper_por_voz`, ligado por
    padrão); injetável para o teste. Fora do laço de áudio — o modo texto —, não há microfone."""
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
    trilha: TrilhaDeDiagnostico = field(init=False, repr=False)
    """Os metadados de cada turno (`jarvis.trilha`), na pasta da sessão: o que o
    `jarvis-voz --diagnostico` mostra do último turno."""
    """O botão de parar do mouse e do teclado virtuais: a janela o aciona, e só ela o libera."""
    _entrada: tuple[tuple[bool], ControleDeEntrada] | None = field(default=None, repr=False)
    _navegadores_de_outra_familia: dict[str, CorposDoNavegador] = field(
        default_factory=dict, repr=False
    )
    """O `sites.open` num navegador que não é o principal: o controle (faixa, PARAR) daquele."""
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
    relogio_dos_avisos: Callable[[], float] = field(default=time.monotonic, repr=False)
    """O relógio da fila de avisos (piso livre, teto): injetável para o teste não dormir."""
    _trava_dos_avisos: threading.RLock = field(default_factory=threading.RLock, repr=False)
    """A fila é mexida pela linha do laço, pelas das tarefas e pela da janela."""
    _falas_dos_avisos: dict[str, str] = field(default_factory=dict, repr=False)
    """O texto inteiro de cada aviso de um pedido (o `resumo` do evento corta em 280)."""
    _telas_dos_avisos: dict[str, str] = field(default_factory=dict, repr=False)
    """A resposta de uma tarefa como a tela a mostra, quando ela passou do orçamento da fala: a voz
    diz o que cabe (`_falas_dos_avisos`), a tela, tudo."""
    _ditos_das_tarefas: dict[str, list[str]] = field(default_factory=dict, repr=False)
    """O que cada tarefa de um pedido já pôs na voz (o aviso de um passo, a pergunta): o fim dela
    não repete (dono, 2026-10-25)."""
    _tarefas_entregues: set[str] = field(default_factory=set, repr=False)
    """As tarefas cujo fim já foi entregue: o fim de uma tarefa sai uma vez só, por id."""

    def __post_init__(self) -> None:
        self.avisos = FilaDeAvisos(session_id=self.session_id)
        self.interruptor_de_entrada = Interruptor(self.raiz / "entrada")
        self.trilha = TrilhaDeDiagnostico(self.raiz / PASTA_DA_TRILHA)

    # --- avisos (ADR-0025) ---------------------------------------------------------------
    def receber_aviso(self, envelope: Envelope) -> None:
        """Um `Notification` entra na fila; a janela é avisada para renovar o card."""
        with self._trava_dos_avisos:
            self.avisos.receber(envelope, self.relogio_dos_avisos())
        self._avisos_mudaram()

    def registrar_aviso(self, tipo: str, origem: str, resumo: str) -> None:
        """Aviso que nasce no próprio laço (a conversa caiu, o motor falhou). Vai **só para o
        card**: a frase já foi escrita na tela, e falar de novo seria repetir."""
        identificador = f"local-{uuid7()}"
        with self._trava_dos_avisos:
            self.avisos.receber(
                notificacao(
                    self.session_id, identificador, tipo=tipo, origem=origem, resumo=resumo
                ),
                self.relogio_dos_avisos(),
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
        with self._trava_dos_avisos:
            return self.avisos.dados_do_card(self.relogio_dos_avisos())

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
        with self._trava_dos_avisos:
            self.avisos.tts_tocando(estado is Estado.FALANDO, self.relogio_dos_avisos())
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
        if not self._vocabulario_carregado:
            # Antes do ASR: os termos do dono vão na dica dele (ADR-0044).
            self._ler_o_vocabulario()
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
        _aquecer_em_segundo_plano(self._asr, self._tts)
        if self._motor is None:
            self._motor = motor_de_conversa(
                self.configuracao, pasta_de_trabalho=self.raiz / "conversa"
            )
        if com_asr and self.detector is None and self.configuracao.enderecamento:
            self.detector = self._abrir_o_detector()
        if self._cerebro is None:
            self._cerebro = Cerebro(motor=self._motor, session_id=self.session_id)
            self._ligar_o_portao(self._cerebro)
            # As regras do dono (ADR-0047), depois da persona, em todo turno: as do arquivo dele
            # (a pasta do vocabulário, a do jarvis-voz.toml), ou as do repositório.
            self._cerebro.conversa.sistema = sistema_do_jarvis(self._ler_as_regras().bloco())
        if self.ferramentas is None:
            self.ferramentas = self._montar_ferramentas()
        self._cerebro.ferramentas = self.ferramentas
        # O pedido que precisa de ferramenta vira tarefa (ADR-0038): o laço fica livre para a
        # próxima fala enquanto ela trabalha.
        self._cerebro.delegar_em_tarefa = True
        # O caminho rápido (ADR-0045): comando simples vai à ferramenta pela regra, sem esperar o
        # motor — pelo mesmo PDP, Jev e pergunta da proposta do modelo.
        self._cerebro.caminho_rapido = self.configuracao.caminho_rapido
        self._cerebro.confirmar = self._confirmar
        self._cerebro.ao_status = self._status_do_laco
        self._cerebro.maximo_de_passos = self.configuracao.laco_max_passos
        self._cerebro.prazo_do_laco_de_ferramentas_s = self.configuracao.laco_prazo_s
        self.ferramentas.prazo_do_foco_s = self.configuracao.prazo_do_foco_s
        self._sincronizar_conversa(self._cerebro)
        if self.ferramentas.tarefas is None:
            self.ferramentas.tarefas = self._montar_tarefas(self.ferramentas)
        # Encerrar o Jarvis pela voz (ADR-0041): o executor pergunta o que está no ar e pede o fim.
        self.ferramentas.encerramento = Encerramento(
            pendente=self._o_que_esta_no_ar, pedir=self._pedir_o_fim
        )
        self.ferramentas.portas().ambiente = self.ambiente
        if self.ferramentas.portas().janelas is None and not em_ci(self.ambiente):
            # Quem vê e foca as janelas (ADR-0037): o critério da entrada virtual — `kdotool` no
            # KDE, `wmctrl` no X11. Sem ele, as `window.*` seguem pelo `wmctrl`, como antes.
            self.ferramentas.portas().janelas = janelas_do_ambiente(ambiente_ou_os(self.ambiente))
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
            ao_avisar=self._aviso_da_tarefa,
            ao_retirar_aviso=self._retirar_aviso,
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
        estado, ou o aviso que o código do motor escreveu — ADR-0037), exceto o resumo de um motor
        `agente`, que é de terceiros e vem marcado. O fim de uma tarefa é entregue **uma vez**, pelo
        id dela (dono, 2026-10-25: nada de responder duas vezes ao mesmo pedido)."""
        with self._trava_dos_avisos:
            if tarefa.id in self._tarefas_entregues:
                return
            self._tarefas_entregues.add(tarefa.id)
        if tarefa.de_objetivo:
            self._resposta_da_tarefa(tarefa)
            return
        if tarefa.confirmar is not None and tarefa.motor == "direto":
            self._resposta_da_acao_confirmada(tarefa)
            return
        if tarefa.estado is EstadoDaTarefa.CONCLUIDA:
            if tarefa.aviso == "":
                return  # o código do motor pediu silêncio (ADR-0037): o card mostra o fim
            tipo, resumo = "concluida", tarefa.aviso or f"a tarefa «{tarefa.descricao}» terminou"
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

    def _resposta_da_tarefa(self, tarefa: Tarefa) -> None:
        """O fim da tarefa de um pedido é a **resposta** a ele (ADR-0038): o resultado conferido
        ou o erro em frase de gente, dito como fala do Jarvis — nunca o nome da ferramenta.

        Entrega silenciosa (dono, 2026-10-25): o que o dono já ouviu deste pedido — a frase do
        turno, o aviso de um passo, a pergunta — não volta à voz. O fim só fala se traz algo novo
        (`jarvis.s2.entrega`); senão, só o card e a tela mudam. Cancelada (pelo botão, pela
        `tarefa.cancelar` que ele pediu) e recusada por ele (disse não à pergunta) acabam caladas:
        quem decidiu foi ele."""
        if tarefa.estado is EstadoDaTarefa.CANCELADA:
            self._entrega_silenciosa(
                tarefa, "cancelada_pelo_dono", "Parei o que você tinha pedido."
            )
            return
        if tarefa.aviso == "":
            self._entrega_silenciosa(tarefa, "recusada_pelo_dono", tarefa.motivo)
            return
        if tarefa.estado is EstadoDaTarefa.CONCLUIDA:
            tipo, frase = "concluida", tarefa.resposta or "Terminei o que você pediu."
        else:
            motivo = tarefa.motivo
            if not motivo or re.match(ERRO_CRU, motivo):
                motivo = "deu um erro aqui dentro"
            tipo = "falhou"
            frase = tarefa.resposta or f"Não consegui terminar o que você pediu: {motivo}."
        frase = sem_protocolo(frase)
        with self._trava_dos_avisos:
            ditos = [tarefa.ja_dito, *self._ditos_das_tarefas.get(tarefa.id, [])]
        novo = so_o_novo(frase, ditos)
        if not novo:
            self._entrega_silenciosa(tarefa, "ja_dito", frase)
            return
        # Falar menos (dono, 2026-10-21): a voz resume a execução em até quatro frases, a não ser
        # que o pedido peça detalhe; o que passar disso vai só para a tela.
        falado, _so_na_tela = orcar(novo, livre=quer_detalhe(tarefa.descricao))
        self._aviso_da_tarefa(tarefa, f"tarefa-{tarefa.id}", tipo, falado, na_tela=frase)
        self.trilha.evento(
            "entrega",
            turno=tarefa.turno or tarefa.id,
            origem="tarefa",
            decisao="falada",
            motivo="falha" if tipo == "falhou" else "nova_informacao",
        )

    def _resposta_da_acao_confirmada(self, tarefa: Tarefa) -> None:
        """A ação que o dono confirmou no clique (`fluxo_de_acao._despachar`): o fim é a resposta a
        ela, dita como fala — o aviso da ferramenta («Encerrei o Steam.») ou a frase da ação."""
        if tarefa.estado is EstadoDaTarefa.CANCELADA:
            self._entrega_silenciosa(tarefa, "cancelada_pelo_dono", "Parei o que você confirmou.")
            return
        if tarefa.estado is EstadoDaTarefa.CONCLUIDA:
            tipo, frase = "concluida", tarefa.aviso or f"Feito: {tarefa.descricao}."
        else:
            tipo, frase = "falhou", f"Não deu para {tarefa.descricao}: {tarefa.motivo}."
        self._aviso_da_tarefa(tarefa, f"tarefa-{tarefa.id}", tipo, frase)

    def _entrega_silenciosa(self, tarefa: Tarefa, motivo: str, frase: str) -> None:
        """O fim de uma tarefa que não vai à voz: o card guarda (`SO_CARD`), a tela mostra, e a
        trilha diz por quê — o dono olha a janela e vê o estado, sem ouvir a repetição."""
        texto = " ".join(sem_protocolo(frase).split()) or tarefa.descricao
        identificador = f"tarefa-{tarefa.id}"
        with self._trava_dos_avisos:
            self.avisos.receber(
                notificacao(
                    self.session_id,
                    identificador,
                    tipo="concluida" if tarefa.estado is EstadoDaTarefa.CONCLUIDA else "evento",
                    origem=f"{ORIGEM_DO_PEDIDO}{tarefa.descricao}"[:80],
                    resumo=texto,
                ),
                self.relogio_dos_avisos(),
            )
            self.avisos.decidido(identificador, Entrega.SO_CARD)
        self._avisos_mudaram()
        if tarefa.estado is EstadoDaTarefa.CONCLUIDA:
            self.escrever_na_tela(f"  ({texto})")
        self.trilha.evento(
            "entrega",
            turno=tarefa.turno or tarefa.id,
            origem="tarefa",
            decisao="silenciosa",
            motivo=motivo,
        )

    def _aviso_da_tarefa(
        self, tarefa: Tarefa, identificador: str, tipo: str, frase: str, *, na_tela: str = ""
    ) -> None:
        """Algo da tarefa de um pedido para o dono (a pergunta que ela espera, o aviso de uma
        moderada, a resposta): entra na fila com a origem do pedido — que fala o texto como ele é
        e não espera o teto dos avisos espontâneos —, e nunca por cima da fala em andamento.
        `na_tela` é o texto inteiro quando a voz diz só o que cabe no orçamento da fala."""
        texto = sem_protocolo(frase)
        if not texto:
            return
        tela = sem_protocolo(na_tela)
        with self._trava_dos_avisos:
            self._falas_dos_avisos[identificador] = texto
            # O que esta tarefa já pôs na voz: o fim dela não repete (dono, 2026-10-25).
            self._ditos_das_tarefas.setdefault(tarefa.id, []).append(texto)
            if tela and tela != texto:
                self._telas_dos_avisos[identificador] = tela
            self.avisos.receber(
                notificacao(
                    self.session_id,
                    identificador,
                    tipo=tipo,
                    origem=f"{ORIGEM_DO_PEDIDO}{tarefa.descricao}"[:80],
                    resumo=texto,
                ),
                self.relogio_dos_avisos(),
            )
        self._avisos_mudaram()

    def _retirar_aviso(self, _tarefa: Tarefa, identificador: str) -> None:
        """A pergunta foi respondida (ou venceu) antes de tocar: fica só no card."""
        with self._trava_dos_avisos:
            aviso = self.avisos.avisos.get(identificador)
            if aviso is not None and aviso.pendente:
                self.avisos.decidido(identificador, Entrega.SO_CARD)
        self._avisos_mudaram()

    # --- avisos em voz (ADR-0025, ADR-0038) ----------------------------------------------
    def _liberados(self, liberacao: Envelope | None) -> list[AvisoLiberado]:
        """Os avisos de uma liberação que vão à voz; os outros ficam só no card."""
        if liberacao is None:
            return []
        liberados: list[AvisoLiberado] = []
        for identificador in liberacao.payload["notif_ids"]:
            na_fila = self.avisos.avisos[str(identificador)]
            liberados.append(
                AvisoLiberado(
                    notif_id=na_fila.notif_id,
                    tipo=na_fila.tipo,
                    origem=na_fila.origem,
                    resumo=self._falas_dos_avisos.get(na_fila.notif_id, na_fila.resumo),
                    de_terceiros=na_fila.trust == str(Trust.THIRD_PARTY),
                )
            )
        decisoes = decidir_entrega(liberados)
        for liberado in liberados:
            if decisoes[liberado.notif_id] != FALAR:
                self.avisos.decidido(liberado.notif_id, Entrega(decisoes[liberado.notif_id]))
        return [a for a in liberados if decisoes[a.notif_id] == FALAR]

    def entregar_avisos(self, fila: FilaDePlayback | None = None) -> bool:
        """Piso livre (o dono calado, o TTS parado, 1,5 s): **um** aviso liberado vai à voz — a
        resposta de uma tarefa, a pergunta que ela espera. Devolve se falou."""
        if self._cerebro is None or self._tts is None:
            return False
        with self._trava_dos_avisos:
            avisos = self._liberados(self.avisos.liberar(self.relogio_dos_avisos()))
        if not avisos:
            return False
        self._falar_os_avisos(avisos, fila)
        return True

    def _falar_os_avisos(self, avisos: list[AvisoLiberado], fila: FilaDePlayback | None) -> None:
        """Os avisos como um turno sem motor: o que tocou entra na conversa (e no livro)."""
        assert self._cerebro is not None
        cerebro = self._cerebro
        epoch = self.epoch
        self._turno_cancelado = False
        pedacos: list[dict[str, Any]] = []
        resposta = cerebro.avisar(avisos, epoch=epoch, publicar=pedacos.append)
        # A tela mostra a resposta inteira; a voz, o que coube no orçamento da fala.
        with self._trava_dos_avisos:
            telas = {a.notif_id: self._telas_dos_avisos.pop(a.notif_id, "") for a in avisos}
        texto = " ".join(telas[a.notif_id] or frase_do_aviso(a) for a in avisos)
        so_na_tela = [orcar(telas[a.notif_id])[1] for a in avisos if telas[a.notif_id]]
        resposta.so_na_tela = " ".join(t for t in so_na_tela if t)
        if self.ao_pedaco is not None:
            self.ao_pedaco(texto)
        fala, turno = self._tocar(
            trechos_do_stream(iter(pedacos), epoch=epoch), epoch=epoch, fila=fila
        )
        tocadas = turno.amostras_tocadas
        cerebro.ouvido(
            resposta.response_id,
            fala.texto_ate(tocadas),
            interrompida=turno.cancelado,
            played_ms=int(1000 * tocadas / TAXA_PADRAO),
        )
        self._avisos_tocados([a.notif_id for a in avisos], cortados=turno.cancelado)
        self.escrever_na_tela(f"Jarvis: {texto}")
        self.turnos.append(Turno(falou="", respondeu=texto, amostras_tocadas=tocadas, epoch=epoch))
        self._mudar(self._repouso)

    def _avisos_tocados(self, identificadores: list[str], *, cortados: bool) -> None:
        """Entregue é o que tocou (regra 15): cortado volta para a fila. A pergunta de uma tarefa
        que tocou inteira passa a aceitar o "sim" falado."""
        if not identificadores:
            return
        with self._trava_dos_avisos:
            if cortados:
                self.avisos.cortado(identificadores)
            else:
                self.avisos.tocou(identificadores, self.relogio_dos_avisos())
        if not cortados and self._cerebro is not None:
            for identificador in identificadores:
                if identificador.startswith(PREFIXO_DA_PERGUNTA):
                    self._cerebro.pendencias.marcar_ouvida(
                        identificador.removeprefix(PREFIXO_DA_PERGUNTA)
                    )
        self._avisos_mudaram()

    def _confirmar_da_tarefa(self, pergunta: Confirmacao, cancelada: Callable[[], bool]) -> bool:
        """O "sim" do dono para um passo perigoso de uma tarefa: a mesma faixa da conversa, mas a
        tarefa **espera sozinha** — o estado do núcleo e o epoch da fala não são dela."""
        return self._confirmar(pergunta, tarefa_cancelada=cancelada)

    # --- encerrar o Jarvis (ADR-0041) ---------------------------------------------------------
    def _o_que_esta_no_ar(self) -> str:
        """O que encerrar agora interromperia — e por isso pede o sim: uma tarefa do dono rodando
        ou uma pergunta esperando a resposta dele. Acompanhar o foco de um app (ADR-0037) não conta:
        parar isso não perde nada."""
        gestor = self.ferramentas.tarefas if self.ferramentas is not None else None
        rodando = [
            t
            for t in (gestor.tarefas.values() if gestor is not None else ())
            if not t.estado.final and t.motor != MOTOR_DO_FOCO
        ]
        if rodando:
            nomes = ", ".join(f"«{t.descricao[:50]}»" for t in rodando[:2])
            if len(rodando) == 1:
                return f"a tarefa {nomes} ainda está rodando e vai ser cancelada"
            return f"as {len(rodando)} tarefas {nomes} ainda estão rodando e vão ser canceladas"
        if self._cerebro is not None and self._cerebro.pendencias.valida() is not None:
            return "há uma pergunta esperando a sua resposta, e ela vai ser descartada"
        return ""

    def _fim_pedido(self) -> bool:
        """Lido por método: o pedido de fim chega no meio do turno, de dentro do executor."""
        return self._encerrar_pedido

    def _pedir_o_fim(self) -> int:
        """O corpo da `jarvis.encerrar`: só marca. O laço acaba o turno (a despedida toca) e então
        sai pelo caminho de sempre — e `_encerrar_limpo` faz o resto."""
        self._encerrar_pedido = True
        gestor = self.ferramentas.tarefas if self.ferramentas is not None else None
        if gestor is None:
            return 0
        return sum(1 for t in gestor.tarefas.values() if not t.estado.final)

    def _encerrar_limpo(self) -> None:
        """O fim que o dono pediu: além do de sempre (tarefas canceladas, microfone e alto-falante
        fechados, a voz solta), solta o mouse e o teclado virtuais e as abas do navegador. A
        conversa já está no livro, turno a turno; quem a fecha é quem a abriu (a janela)."""
        with contextlib.suppress(Exception):  # sem extensão conectada, não há aba a soltar
            self.parar_navegador()
        self.interruptor_de_entrada.parar("o Jarvis foi encerrado")
        if self.conversa is not None:
            self.conversa.indexar_depois()
        self.encerrado = True
        self.escrever_na_tela("  ⏻ Jarvis encerrado")

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

    def _dica_do_asr(self) -> str:
        """A dica do ASR (ADR-0043): a palavra de ativação e os termos do dono — curta."""
        return dica_do_asr(self.configuracao.palavra, self._vocabulario_lido.termos_da_dica())

    # --- o vocabulário do dono (ADR-0044) -------------------------------------------------------
    def _ler_as_regras(self) -> Regras:
        """As regras de comportamento do dono (ADR-0047): o `regras.toml` da pasta de configuração
        dele, ou as do repositório. A suíte, sem o repositório do vocabulário, nunca lê a pasta do
        dono. O que não serviu fica de fora com aviso, como no vocabulário."""
        pasta = self.vocabulario.pasta if self.vocabulario is not None else None
        self.regras = na_pasta(pasta) if pasta is not None else padrao_das_regras()
        if self.regras.avisos:
            self.escrever_na_tela(
                f"  (regras: {len(self.regras.avisos)} aviso(s) — `jarvis-voz --diagnostico` diz"
                " quais)"
            )
        return self.regras

    def _ler_o_vocabulario(self) -> None:
        """Lê o vocabulário uma vez por abertura. O que não serve fica de fora com aviso — a voz
        não cai por um arquivo torto; a tela diz quantas entradas e onde ver."""
        self._vocabulario_carregado = True
        if self.vocabulario is None:
            return
        self._vocabulario_lido = self.vocabulario.carregar()
        if self._vocabulario_lido.avisos:
            self.escrever_na_tela(
                f"  (vocabulário: {len(self._vocabulario_lido.avisos)} entrada(s) ficaram de fora"
                " — `jarvis-voz --diagnostico` diz quais)"
            )

    def recarregar_vocabulario(self) -> None:
        """O dono corrigiu um nome (`vocabulario.aprender`, ou o "desfaz"): vale já — na
        pós-correção, na pronúncia e na dica do ASR aberto, sem reabrir o motor."""
        self._ler_o_vocabulario()
        if self._asr is not None and hasattr(self._asr, "dica"):
            self._asr.dica = self._dica_do_asr()

    def _pronunciar(self, texto: str) -> str:
        """O texto que o motor de TTS recebe: a grafia trocada pela pronúncia do dono."""
        motor = str(getattr(self._tts, "registrado", "") or self.configuracao.tts)
        return self._vocabulario_lido.pronunciar(texto, motor)

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
                dica=self._dica_do_asr(),
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
                        dica=self._dica_do_asr(),
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
                reutilizar_aba=self._na_aba_atual,
                mostrar_aberto=self._mostrar_o_navegador,
                em_execucao=navegador_em_execucao,
                focar_janela=self._focar_o_navegador,
            ),
            navegador=self._corpos_do_navegador(),
            estado_do_navegador=self.estado_do_navegador,
            # A tela da aba só existe se o motor do chat de agora recebe imagem (ADR-0032).
            motor_ve_imagem=lambda: aceita_imagem(self._motor),
            entrada=self._controle_de_entrada(),
            trilha=self.trilha,
            # Aprender um nome do dono (ADR-0044): só com o repositório, e vale já no laço.
            vocabulario=self.vocabulario,
            ao_mudar_vocabulario=self.recarregar_vocabulario,
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
        return self._ligar_o_controle(familia_do_host(self.configuracao.navegador_principal))

    def _ligar_o_controle(self, familia: str) -> CorposDoNavegador:
        """As `browser.*` de um navegador, com o PARAR e o aviso de controle ligados ao app."""
        cliente = ClienteDoNavegador(self._transporte_do_navegador())
        cliente.navegador = familia
        corpos = CorposDoNavegador(cliente)
        corpos.ao_parar = self._parar_pelo_navegador
        corpos.ao_mudar = self._navegador_mudou
        # No Wayland o navegador não pega o foco sozinho: o KWin traz a janela dele (2026-10-21).
        corpos.trazer_a_frente = lambda titulo: self._focar_o_navegador(
            self.configuracao.navegador_principal or familia, titulo
        )
        return corpos

    def _focar_o_navegador(self, familia: str, titulo: str = "") -> bool:
        """O navegador aberto vem para a frente pelo gerenciador de janelas (KWin, `kdotool`),
        quando a extensão não conseguiu ou não está conectada (dono, 2026-10-21: «não consegue
        abrir o Brave» com ele aberto, e o Brave na frente do principal que o Jarvis não via)."""
        janelas = self.ferramentas.portas().janelas if self.ferramentas is not None else None
        return janelas is not None and focar_o_navegador(janelas, familia, titulo)

    def _parar_pelo_navegador(self, objetivos: Sequence[Objetivo]) -> None:
        """O dono apertou PARAR (na faixa da página, no botão da extensão ou na janela do Jarvis):
        as tarefas daqueles pedidos são canceladas e o turno, se ainda está no ar, é interrompido
        (epoch) — o mecanismo de parar de sempre. A extensão já soltou as abas."""
        executor = self.ferramentas
        if executor is None:
            return
        gestor = executor.tarefas
        if gestor is not None:
            for tarefa in list(gestor.tarefas.values()):
                parada = any(tarefa.contaminacao.objetivo is o for o in objetivos)
                if parada and not tarefa.estado.final:
                    with contextlib.suppress(TarefaRecusada):
                        gestor.cancelar(tarefa.id)
        no_ar = self.estado in (Estado.FALANDO, Estado.PENSANDO) or bool(self._confirmacoes)
        if no_ar and any(executor.objetivo is o for o in objetivos):
            self.interromper("parar no navegador")
        else:
            self.escrever_na_tela("  ⟂ parei o que o Jarvis fazia no navegador")

    def _navegador_mudou(self, ativo: bool) -> None:
        if self.ao_mudar_navegador is not None:
            self.ao_mudar_navegador(ativo)

    def parar_navegador(self) -> int:
        """O botão PARAR da janela do Jarvis: solta todas as abas que ele controla e cancela o turno
        e as tarefas que estavam nelas. Devolve quantos pedidos pararam."""
        parados = 0
        corpos = self.ferramentas.navegador if self.ferramentas is not None else None
        for controle in (corpos, *self._navegadores_de_outra_familia.values()):
            if controle is not None:
                parados += len(controle.parar())
        return parados

    def _controle_da_familia(self, familia: str) -> CorposDoNavegador | None:
        """As `browser.*` do navegador daquela família (o principal, ou outro que o dono nomeou),
        ou `None` com o controle desligado."""
        if not self.configuracao.navegador_controlado:
            return None
        alvo = familia_do_host(familia)
        corpos = self.ferramentas.navegador if self.ferramentas is not None else None
        if corpos is None or (alvo and corpos.cliente.navegador not in ("", alvo)):
            corpos = self._navegadores_de_outra_familia.get(alvo)
            if corpos is None:
                corpos = self._navegadores_de_outra_familia[alvo] = self._ligar_o_controle(alvo)
        return corpos

    def _na_aba_atual(
        self, url: str, familia: str, nova_aba: bool = False
    ) -> dict[str, Any] | None:
        """`sites.open` pela extensão, no navegador que já está aberto (dono, 2026-10-20 e
        2026-10-21): reaproveita a aba que já tem o site, senão abre uma guia nova na janela do
        dono — também quando o pedido é de aba nova —, e termina à vista, conferido, com a faixa
        "no controle" (ADR-0027). Sem o controle ligado ou sem a extensão daquele navegador,
        devolve `None` e o navegador é aberto com a URL; página que não abre é erro."""
        corpos = self._controle_da_familia(familia)
        if corpos is None:
            return None
        objetivo = self.ferramentas.objetivo if self.ferramentas is not None else None
        try:
            return corpos.abrir_site(url, objetivo=objetivo, nova_aba=nova_aba)
        except NavegadorIndisponivel:
            return None

    def _mostrar_o_navegador(self, familia: str) -> dict[str, Any] | None:
        """«Abre o navegador» com ele já aberto pela extensão: a janela do dono vem para a frente,
        sem outra janela nem instância (dono, 2026-10-21). `None` sem a extensão conectada."""
        corpos = self._controle_da_familia(familia)
        if corpos is None:
            return None
        try:
            return corpos.mostrar_o_navegador()
        except NavegadorIndisponivel:
            return None

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
            novo.prazo_do_foco_s = antigo.prazo_do_foco_s
            novo.encerramento = antigo.encerramento
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

    def _fechar_a_voz(self) -> None:
        """O motor que tem processo próprio (o trabalhador do OmniVoice) o encerra com o laço.

        Se o laço voltar, o motor sobe de novo no primeiro lote — ele não é trocado aqui.
        """
        fechar = getattr(self._tts, "fechar", None)
        if callable(fechar):
            fechar()

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
    _captura_viva: Captura | None = field(default=None, repr=False)
    _fila_viva: FilaDePlayback | None = field(default=None, repr=False)
    """A captura e a fila do laço de áudio que está rodando: é por elas que a vigia ouve o dono
    durante a fala (ADR-0040). `None` fora do `rodar_audio`."""
    _fala_por_cima: bytes | None = field(default=None, repr=False)
    """O trecho em que o dono cortou o Jarvis (ou já falava quando ele acabou): o laço o continua
    como o começo do turno novo, em vez de jogar fora o que ele disse."""
    _fonte_acabou: bool = False
    _trava_do_asr: threading.Lock = field(default_factory=threading.Lock, repr=False)
    """O ASR é um só: o turno do laço e a vigia (numa linha à parte) não transcrevem juntos."""
    _encerrar_pedido: bool = False
    """O dono pediu o fim (`jarvis.encerrar`): o laço termina o turno — a despedida toca — e sai."""
    _escuta_por_cima: ThreadPoolExecutor | None = field(default=None, repr=False)
    _vigia_montada_aqui: bool = False
    _decisoes_na_trilha: int = 0

    # --- um turno -----------------------------------------------------------------------
    def responder(
        self,
        texto: str,
        *,
        fila: FilaDePlayback | None = None,
        ms_ouvido: float | None = None,
        ms_asr: float | None = None,
    ) -> Turno:
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
        turn_id = f"t-{uuid7()}"
        self.trilha.novo_turno(
            turn_id, motor=self._motor.nome, epoch=epoch, caracteres_do_pedido=len(texto)
        )

        def geracao_cancelada() -> bool:
            return parar_geracao.is_set() or cancelado()

        # Mensagem do dono: os avisos pendentes vão junto com ela, antes da resposta (ADR-0025).
        with self._trava_dos_avisos:
            com_a_mensagem = self._liberados(
                self.avisos.mensagem_do_dono(turn_id, self.relogio_dos_avisos())
            )
        self._mudar(Estado.PENSANDO)
        comeco = time.monotonic()
        # Sem teto: texto é pequeno, e quem limita o trabalho é a janela de síntese do
        # `SintetizadorEmStreaming` (3 lotes à frente). Com teto aqui (7507cd5) o cérebro parava de
        # ler o motor enquanto o alto-falante falava: a tela voltava ao ritmo da fala e o prazo
        # total do motor (30 s no claude, contado a cada `next()`) cortava resposta longa.
        pedacos: queue.Queue[dict[str, object] | None] = queue.Queue()
        resultado: dict[str, Resposta] = {}
        falha: list[str] = []
        exibido: list[str] = []
        primeiro_texto_ms: list[float] = []

        def publicar(pedaco: dict[str, object]) -> None:
            """Na linha do cérebro, no instante em que o lote de fala nasce: vai para o tocador
            sem esperar. O que o dono ouve continua sendo o que o tocador consome."""
            if geracao_cancelada():
                return
            pedacos.put(pedaco)
            if pedaco["text"]:
                if not primeiro_texto_ms:
                    primeiro_texto_ms.append((time.monotonic() - comeco) * 1000.0)
                exibido.append(str(pedaco["text"]))

        def mostrar(texto_da_resposta: str) -> None:
            """A tela, a cada delta do motor, na linha do cérebro: segue a geração.

            Antes ela seguia o tocador (um pedaço por segundo, achado do dono em 2026-10-17) e,
            com os lotes de fala de 14..18 palavras (7507cd5), crescia só de lote em lote — uma
            resposta de 28 palavras aparecia em dois saltos."""
            if self.ao_pedaco is not None and not geracao_cancelada():
                self.ao_pedaco(texto_da_resposta)

        def gerar() -> None:
            try:
                resultado["r"] = cerebro.responder(
                    texto,
                    epoch=epoch,
                    publicar=publicar,
                    turn_id=turn_id,
                    cancelado=geracao_cancelada,
                    avisos=com_a_mensagem,
                    mostrar=mostrar,
                )
            except Exception as erro:  # o turno degrada e diz; a linha não leva o laço junto
                falha.append(f"{type(erro).__name__}: {erro}")
            finally:
                pedacos.put(None)

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
            # Recusa da fila ou erro na síntese também encerram a geração, mesmo sem alteração
            # do epoch local: o cérebro para de publicar e fecha o motor.
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
        self._avisos_tocados(
            [a.notif_id for a in com_a_mensagem], cortados=turno.cancelado or resposta is None
        )
        if self.conversa is not None:
            self.conversa.indexar_depois()
        self._mudar(self._repouso)
        respondeu = " ".join(exibido)
        self.trilha.evento(
            "turno.fim",
            turno=turn_id,
            fim=str(resposta.fim) if resposta is not None else "falhou",
            cancelado=cancelado() or turno.cancelado,
            ms_primeiro_token=resposta.ms_ate_primeiro_token if resposta else None,
            ms_primeira_fala=primeiro_texto_ms[0] if primeiro_texto_ms else None,
            ms_primeiro_audio=turno.primeiro_pedaco_ms,
            ms_total=(time.monotonic() - comeco) * 1000.0,
            ferramentas=len(resposta.ferramentas) if resposta else 0,
            caracteres_falados=len(respondeu),
            # Pensar não é falar (ADR-0031): do raciocínio, só o tamanho — o texto morre no turno.
            caracteres_de_raciocinio=len(resposta.raciocinio) if resposta else 0,
            raciocinio_descartado=resposta.raciocinio_descartado if resposta else 0,
            narracao_retida=resposta.narracao_retida if resposta else 0,
            # Falar menos (emenda de 2026-10-21 à ADR-0031): o tamanho do que ficou só na tela.
            caracteres_so_na_tela=len(resposta.so_na_tela) if resposta else 0,
            resultados_podados=resposta.resultados_podados if resposta else 0,
            objetivo=resposta.estado_do_objetivo if resposta else "",
            erro=falha[0] if falha else "",
            # As etapas da velocidade (ADR-0045): só tempos e códigos.
            ms_ouvido=ms_ouvido,
            ms_asr=ms_asr,
            ms_contexto=resposta.ms_ate_contexto if resposta else None,
            ms_primeira_ferramenta=resposta.ms_ate_primeira_ferramenta if resposta else None,
            atalho=resposta.atalho if resposta else "",
            motor_chamado=resposta.motor_chamado if resposta else True,
            frases_caladas=len(resposta.caladas) if resposta else 0,
        )
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
        # A vigia ouve o dono desde já — enquanto a fala é preparada e enquanto toca (ADR-0040).
        vigia = self.vigia if self._captura_viva is not None and fila is not None else None
        if vigia is not None:
            vigia.comecar(self.modo_de_escuta.modo, palavra=self.modo_de_escuta.detector)
        sintetizador = SintetizadorEmStreaming(
            motor=self._tts,
            session_id=self.session_id,
            epoch=epoch,
            cancelado=self.cancelado_de(epoch),
            ao_esperar=self._enquanto_fala,
            pronunciar=self._pronunciar,
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
                if vigia is not None:
                    vigia.falando(trecho.texto)  # é com isto que o eco dele é reconhecido
                # Drena o pedaço quadro a quadro, olhando o teclado **e o microfone** entre eles:
                # é aqui que a barra — ou a voz do dono — interrompe no meio do pedaço, e não só
                # entre pedaços. Pausada (a contínua conferindo quem falou), a fila não anda e
                # quem dá o ritmo é o microfone.
                while fila.pedacos_na_fila and self.epoch == epoch:
                    antes = fila.sumidouro.amostras_consumidas
                    fila.tick()
                    tocadas += fila.sumidouro.amostras_consumidas - antes
                    self._enquanto_fala()
                if self.epoch > epoch:
                    break
        finally:
            fechar = getattr(fluxo, "close", None)
            if fechar is not None:
                fechar()
            if fila is not None:
                fila.pausado = False
            if fila is not None and self.epoch > epoch:
                # Vale também durante a espera pelo primeiro áudio, sem entrar no playback.
                fila.cancelar(reason="barge_in", epoch_novo=self.epoch)
            if vigia is not None and self.epoch == epoch:
                # O Jarvis acabou de falar com o dono já falando: o que ele disse não se perde.
                continuado = vigia.terminar()
                if continuado and self._fala_por_cima is None:
                    self._fala_por_cima = continuado
            self._trilhar_a_vigia()
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
        if self._cerebro is not None:
            # A pergunta de uma tarefa que o dono ainda não ouviu inteira cai (é não, ADR-0038).
            self._cerebro.pendencias.interrompida()
        self._mudar(self._repouso)
        self.escrever_na_tela(f"  ⟂ interrompido ({motivo})")
        return self.epoch

    # --- interromper por voz (ADR-0040) -------------------------------------------------------
    def _enquanto_fala(self) -> None:
        """Entre um quadro tocado e o próximo (e enquanto a fala é preparada): a tecla e o
        microfone. É aqui que o dono interrompe — pelo botão, como sempre, ou pela voz."""
        self._olhar_o_teclado()
        self._ouvir_por_cima()

    def _ouvir_por_cima(self) -> None:
        """Um quadro do microfone para a vigia, e o que ela decidir: pausar (a contínua conferindo
        quem falou), retomar, ou cortar — o epoch morre, como no botão, e o trecho do dono vira o
        começo do turno novo. No atalho quem interrompe é o dedo (a barra), como antes."""
        captura, fila, vigia = self._captura_viva, self._fila_viva, self.vigia
        if captura is None or fila is None or vigia is None or self._fonte_acabou:
            return
        if self.modo_de_escuta.modo is ModoDeEscuta.ATALHO:
            return
        antes = captura.quadros
        captura.tick()
        quadro = captura.ultimo_quadro
        if quadro is None or captura.quadros == antes:
            # A fonte acabou (o WAV terminou): ninguém mais fala por cima; o laço sai depois.
            self._fonte_acabou = True
            fila.pausado = False
            return
        if captura.quadros % QUADROS_POR_PUBLICACAO == 0:
            # O indicador do F1-13 diz o que a fonte faz — e agora ela segue lendo durante a fala.
            self._publicar_estado(captura, aberta=True)
        acao = vigia.ouvir(quadro, fala_no_vad=bool(captura.detector.falando))
        if acao is AcaoDaVigia.PAUSAR:
            fila.pausado = True
        elif acao is AcaoDaVigia.RETOMAR:
            fila.pausado = False
        elif acao is AcaoDaVigia.CORTAR:
            fila.pausado = False
            self._fala_por_cima = vigia.audio_do_corte()
            with self._trava_dos_avisos:
                self.avisos.dono_falando(True, self.relogio_dos_avisos())
            self.interromper("voz")
        if acao is not AcaoDaVigia.NADA:
            self._trilhar_a_vigia()

    def _trilhar_a_vigia(self) -> None:
        """Cada decisão da vigia vai para a trilha: o modo, o que fez, o motivo (código) e em
        quantos milissegundos de trecho — nunca o que o dono disse."""
        vigia = self.vigia
        if vigia is None:
            return
        for decisao in vigia.decisoes[self._decisoes_na_trilha :]:
            self.trilha.evento(
                "interrupcao",
                modo=str(vigia.modo),
                decisao=str(decisao.acao),
                motivo=str(decisao.motivo),
                ms=decisao.ms,
            )
        self._decisoes_na_trilha = len(vigia.decisoes)

    def _montar_a_vigia(self) -> VigiaDeInterrupcao | None:
        """A vigia do laço de áudio, com o ASR da sessão numa linha à parte (o áudio não espera a
        transcrição) e, na contínua, o detector de endereçamento, se o dono o ligou."""
        if self.vigia is not None:
            return self.vigia  # já montada (ou injetada pelo teste)
        if not self.configuracao.interromper_por_voz or self._asr is None:
            return None
        asr, trava = self._asr, self._trava_do_asr

        def transcrever(amostras: bytes) -> str:
            # O mesmo filtro do turno (ADR-0043): o "Jarvis." que o ASR inventa na respiração
            # não corta a fala dele — a vigia recebe vazio, que é "não era fala".
            with trava:
                transcricao = transcrever_com_sinais(asr, amostras)
            veredito = julgar_texto(
                transcricao.hipotese.texto,
                transcricao.sinais,
                politica=self.politica_de_ruido,
                dica=self._palavras_da_dica(),
            )
            return "" if veredito.descartado else veredito.texto

        enderecada: Callable[[str], bool] | None = None
        detector = self.detector
        if detector is not None:

            def com_o_jarvis(texto: str) -> bool:
                return detector.avaliar(texto, jarvis_perguntou=False).agir

            enderecada = com_o_jarvis
        self._escuta_por_cima = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="jarvis-por-cima"
        )
        self.vigia = VigiaDeInterrupcao(
            transcrever=transcrever,
            palavra=self.modo_de_escuta.detector,
            enderecada=enderecada,
            enviar=self._escuta_por_cima.submit,
        )
        self._vigia_montada_aqui = True
        return self.vigia

    def _soltar_a_vigia(self) -> None:
        if self._escuta_por_cima is not None:
            self._escuta_por_cima.shutdown(wait=False, cancel_futures=True)
            self._escuta_por_cima = None
        if self._vigia_montada_aqui:
            self.vigia = None
            self._vigia_montada_aqui = False
        self._decisoes_na_trilha = 0

    def _continuar_o_dono(self, antes_da_fala: deque[bytes]) -> bytearray | None:
        """Depois de o Jarvis falar: o trecho em que o dono o cortou (ou já falava quando ele
        acabou) volta ao laço como o começo do turno dele. Sem isso, o "antes da fala" do turno
        seguinte são os últimos quadros que a vigia ouviu — não os de antes de o Jarvis falar."""
        continuado, self._fala_por_cima = self._fala_por_cima, None
        if continuado is None:
            if self.vigia is not None and self._captura_viva is not None:
                antes_da_fala.clear()
                antes_da_fala.extend(self.vigia.ultimos_quadros())
            return None
        with self._trava_dos_avisos:
            self.avisos.dono_falando(True, self.relogio_dos_avisos())
        return bytearray(continuado)

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
    def rodar_texto(self, linhas: Iterable[str | None]) -> int:
        """Sem microfone: o dono digita, o Jarvis responde e **fala** pelo sumidouro.

        É o caminho que funciona sem placa de som — e é o que prova o resto do laço quando o
        dispositivo não abre (aceite do pedido do dono). Uma "linha" `None` é o tique de quem não
        digitou nada (a janela manda um a cada fração de segundo): é quando o aviso que espera o
        piso livre — a resposta de uma tarefa — vai à voz.
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
                if self._fim_pedido():
                    break  # o dono pediu para encerrar o Jarvis, e a despedida já tocou
                if linha is None:
                    self.entregar_avisos(fila)
                    continue
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
                if self._fim_pedido():
                    break
        finally:
            self._cancelar_tarefas()
            if self._fim_pedido():
                self._encerrar_limpo()
            if sumidouro is not None:
                sumidouro.fechar()
            self._fechar_a_voz()
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
        vigia = self._montar_a_vigia()
        if vigia is not None:
            # A referência do eco é o que saiu para o alto-falante, fatia a fatia (ADR-0040).
            fila.escuta = vigia.portao.referencia
        self._captura_viva, self._fila_viva, self._fonte_acabou = captura, fila, False

        falando = False
        por_cima = False  # o turno em curso começou cortando o Jarvis (ADR-0040)
        silencio_ms = 0.0
        audio = bytearray()
        # Os últimos quadros ANTES de o VAD disparar: a fala começa antes de o VAD notar, e sem
        # isto o turno perdia o começo ("Jarvis, que horas são" chegava ao ASR como "que hoje
        # são", e a palavra de ativação nunca era ouvida — bug do dono, 2026-10-17).
        antes_da_fala: deque[bytes] = deque(maxlen=QUADROS_ANTES_DA_FALA)
        turnos = 0
        try:
            while limite_de_turnos is None or turnos < limite_de_turnos:
                if self._fim_pedido():
                    break  # o dono pediu para encerrar o Jarvis, e a despedida já tocou
                self._publicar_estado(captura, aberta=True)
                if self._olhar_o_teclado() in TECLAS_DE_SAIDA:
                    break
                digitado = self.texto_digitado() if self.texto_digitado is not None else None
                if digitado:
                    turnos += 1
                    self._turno_digitado(digitado, fila)
                    continuado = self._continuar_o_dono(antes_da_fala)
                    falando = por_cima = continuado is not None
                    silencio_ms, audio = 0.0, continuado if continuado is not None else bytearray()
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
                if vigia is not None:
                    # Com o Jarvis calado, o portão aprende o ambiente (a TV ligada) e o fim do eco.
                    vigia.portao.ver(quadro)
                if self._quer_falar(captura):
                    if not falando:
                        with self._trava_dos_avisos:
                            self.avisos.dono_falando(True, self.relogio_dos_avisos())
                        falando, por_cima = True, False
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
                        with self._trava_dos_avisos:
                            self.avisos.dono_falando(False, self.relogio_dos_avisos())
                        falando = False
                        turnos += 1
                        self._turno_de_audio(bytes(audio), transcritor, fila, por_cima=por_cima)
                        continuado = self._continuar_o_dono(antes_da_fala)
                        falando = por_cima = continuado is not None
                        silencio_ms = 0.0
                        audio = continuado if continuado is not None else bytearray()
                if not falando and not self._pelo_dedo:
                    antes_da_fala.append(quadro.amostras)
                if (
                    not falando
                    and not audio
                    and not fila.pedacos_na_fila
                    and not self._fim_pedido()
                    and self.entregar_avisos(fila)
                ):
                    # Piso livre: a resposta de uma tarefa (ou a pergunta dela) saiu agora — e o
                    # dono pode tê-la cortado por voz (ADR-0040).
                    continuado = self._continuar_o_dono(antes_da_fala)
                    falando = por_cima = continuado is not None
                    silencio_ms = 0.0
                    audio = continuado if continuado is not None else bytearray()
                _ = eventos
                if len(audio) > MAXIMO_DE_AUDIO_POR_TURNO_S * TAXA_PADRAO * BYTES_POR_AMOSTRA:
                    falando = False
                    turnos += 1
                    self._turno_de_audio(bytes(audio), transcritor, fila, por_cima=por_cima)
                    continuado = self._continuar_o_dono(antes_da_fala)
                    falando = por_cima = continuado is not None
                    silencio_ms = 0.0
                    audio = continuado if continuado is not None else bytearray()
        finally:
            self._cancelar_tarefas()
            if self._fim_pedido():
                self._encerrar_limpo()
            self._captura_viva = self._fila_viva = None
            self._soltar_a_vigia()
            self._publicar_estado(captura, aberta=False)
            captura.fechar()
            sumidouro.fechar()
            self._fechar_a_voz()
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
        self,
        amostras: bytes,
        transcritor: TranscritorIncremental,
        fila: FilaDePlayback,
        *,
        por_cima: bool = False,
    ) -> None:
        """Um trecho do dono → pedido → resposta. `por_cima` = o trecho começou cortando o Jarvis
        (ADR-0040): a vigia já decidiu que era com ele, e o começo pode ser o eco do fim da fala."""
        assert self._asr is not None
        self._mudar(Estado.PENSANDO)
        politica = self.politica_de_ruido
        medida = medir_trecho(amostras, politica)
        motivo = None if por_cima else julgar_audio(medida, politica)
        if motivo is not None:
            # Estalo, tecla, ventilador (ADR-0043): o ASR nem roda — nem a Groq cobra os 10 s.
            # Descarte em silêncio: só a contagem e a trilha (códigos e números).
            self._ruido_descartado(motivo, "trecho", medida)
            self._mudar(self._repouso)
            return
        comeco = time.monotonic()
        with self._trava_do_asr:
            transcricao = transcrever_com_sinais(self._asr, amostras)
        asr_ms = (time.monotonic() - comeco) * 1000.0
        ouvido_ms = 1000.0 * (len(amostras) // BYTES_POR_AMOSTRA) / TAXA_PADRAO
        veredito = julgar_texto(
            transcricao.hipotese.texto,
            transcricao.sinais,
            politica=politica,
            dica=self._palavras_da_dica(),
        )
        if veredito.descartado:
            assert veredito.motivo is not None
            self._ruido_descartado(veredito.motivo, "texto", medida, transcricao.sinais)
            self._mudar(self._repouso)
            return
        if self._sim_sem_certeza(veredito.texto, transcricao.sinais):
            # Um "sim" para a pergunta pendente que o ASR não teve certeza de ter ouvido: não
            # confirma nada. A pergunta segue de pé — o dono repete, ou responde na tela.
            self._ruido_descartado(MotivoDoRuido.SIM_INCERTO, "texto", medida, transcricao.sinais)
            self.escrever_na_tela(
                "  (não tive certeza de ter ouvido o seu «sim»: repita, ou responda na tela)"
            )
            self._mudar(self._repouso)
            return
        # Os nomes do dono escritos certo (ADR-0044): o apelido que o ASR errou e o nome composto
        # escrito de outro jeito. Daqui em diante — palavra de ativação, pedido, tela — é este.
        hipotese = transcricao.hipotese._replace(
            texto=self._vocabulario_lido.corrigir(veredito.texto)
        )
        if not hipotese.texto.strip():
            if self.modo_de_escuta.modo is ModoDeEscuta.PALAVRA:
                # Esperando a chamada, ruído que não vira texto é o caso comum: avisar a cada
                # um encheria a tela de "não entendi" enquanto a TV fala.
                self.modo_de_escuta.descartar()
            else:
                self.escrever_na_tela("  (não entendi nada nesse trecho)")
            self._mudar(self._repouso)
            return
        if not por_cima and not self._enderecada_ao_jarvis(hipotese.texto):
            self._mudar(self._repouso)
            return
        pedido = (
            self._pedido_por_cima(hipotese.texto)
            if por_cima
            else self._pedido_do_trecho(hipotese.texto)
        )
        if pedido is None:
            self._mudar(self._repouso)
            return
        if por_cima and so_ordem_de_parar(pedido):
            # "Para", "chega", "Jarvis, silêncio": o corte já foi o pedido; não há o que responder.
            self.escrever_na_tela("  (parei)")
            self._mudar(self._repouso)
            return
        self.escrever_na_tela(f"Você: {pedido}")
        turno = self.responder(pedido, fila=fila, ms_ouvido=ouvido_ms, ms_asr=asr_ms)
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

    # --- ruído não vira pedido (ADR-0043) ------------------------------------------------------
    @property
    def politica_de_ruido(self) -> PoliticaDeRuido:
        """Os limiares do filtro, da configuração viva (o dono troca com a sessão aberta), e as
        frases que ele mandou ignorar no vocabulário."""
        return self.configuracao.politica_de_ruido(ignorar=self._vocabulario_lido.ignorar)

    def _palavras_da_dica(self) -> frozenset[str]:
        """O que foi de dica ao ASR (a palavra de ativação, os termos): é o eco que o filtro
        reconhece quando o modelo devolve a própria dica no meio do ruído."""
        dica = getattr(self._asr, "dica", "")
        return palavras_da_dica(dica) if isinstance(dica, str) else frozenset()

    def _sim_sem_certeza(self, texto: str, sinais: Sinais) -> bool:
        """Um "sim" literal para a pergunta pendente, sem os sinais fortes do ASR? Ruído que vira
        "Sim." é o pior caso de todos: confirmaria a ação que o dono não autorizou."""
        cerebro = self._cerebro
        if cerebro is None or cerebro.pendencias.valida() is None:
            return False
        if resposta_literal(texto) is not RespostaDoDono.SIM:
            return False
        return not sinais_fortes(sinais, self.politica_de_ruido)

    def _ruido_descartado(
        self,
        motivo: MotivoDoRuido,
        etapa: str,
        medida: MedidaDoTrecho,
        sinais: Sinais | None = None,
    ) -> None:
        """Conta e registra o trecho que não virou pedido — em silêncio: nada na tela, nada no
        histórico, e na trilha só o código e os números (`turno` = "escuta": não é de um turno)."""
        self.modo_de_escuta.descartar_ruido()
        self.trilha.evento(
            "ruido",
            turno="escuta",
            etapa=etapa,
            motivo=str(motivo),
            modo=str(self.modo_de_escuta.modo),
            ms=medida.duracao_ms,
            maior_fala_ms=medida.maior_fala_ms,
            contraste_db=round(medida.contraste_db, 1),
            sem_fala=None
            if sinais is None or sinais.sem_fala is None
            else round(sinais.sem_fala, 3),
            logprob=None if sinais is None or sinais.logprob is None else round(sinais.logprob, 3),
        )

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

    def _pedido_por_cima(self, texto: str) -> str | None:
        """O pedido do turno que cortou o Jarvis (ADR-0040). O microfone pegou o fim da fala dele
        junto com a do dono, então o que vem **antes** da chamada é eco: com a palavra de ativação,
        o pedido é o que vem depois dela (sem nada depois, ele só chamou — arma a escuta, como no
        modo palavra); sem ela (a contínua), o trecho sem o prefixo que era o Jarvis falando."""
        escuta = self.modo_de_escuta
        achado = escuta.detector.achar(texto)
        if achado is not None:
            if achado.depois and not so_cortesia(achado.depois):
                escuta.desarmar()
                return achado.depois
            escuta.armar(self.relogio.mono_ns())
            self.escrever_na_tela(f"  (ouvi “{achado.ouvido}”: pode falar)")
            return None
        limpo = self.vigia.sem_o_eco(texto) if self.vigia is not None else texto
        return limpo.strip() or None

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
        if achado is not None and (achado.so_o_nome or so_cortesia(achado.comando)):
            # "Jarvis. Obrigado." é o dono chamando: a cortesia depois do nome é o que o ASR
            # inventa no silêncio do fim do trecho (ADR-0043) — e agradecer não pede resposta.
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
        observacao = str(getattr(self._tts, "observacao", ""))
        if observacao:
            self.escrever_na_tela(f"  ({observacao})")
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
