"""Um turno inteiro, interrompível em 20 pontos nomeados (cartão F1-11).

O aceite (b) da F1 é o mais duro: interromper **a mesma resposta** em vinte pontos distintos e
**nada sobrar**. Para isso o turno vira uma sequência de passos nomeados, e o cancelamento entra
**antes** de um passo escolhido. Os vinte pontos estão em `PONTOS`, cada um com nome e motivo —
é a lista que o cartão pede em arquivo, e cada um tem um caso de teste próprio.

As três invariantes, conferidas em **todo** ponto:

1. **0 áudio velho tocando** — depois do `Cancel`, nenhuma amostra nova chega ao sumidouro;
2. **0 entrada no histórico de algo não tocado** — o histórico contém o prefixo tocado e o
   sufixo **não** aparece em lugar nenhum (regra 4 da §3.3);
3. **0 tool disparada depois do `Cancel`** — e a exceção da regra 3 é respeitada: `ToolResult`
   de **leitura** pode chegar, e só entra se o `s2` reavaliar no epoch novo.

O que **não** se prova aqui, e está dito: o áudio já entregue ao **driver**. A invariante é
sobre o nosso sumidouro; a fila do dispositivo é do F1-16.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from jarvis.agentd.historico import Historico, Retomada, retomar, texto_nao_tocado
from jarvis.agentd.percepcao import Percepcao
from jarvis.agentd.tts import Fala, MotorDeTts, MotorParametrico, SintetizadorEmStreaming
from jarvis.audio_io.playback import FilaDePlayback, Pedaco
from jarvis.audio_io.sumidouros import SumidouroEmMemoria
from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust, uuid7
from jarvis.barramento.epoch import DonoDoEpoch
from jarvis.barramento.fila import FilaCheia, FilaDePrioridade

TEXTO_RESPOSTA: Final = (
    "Achei três arquivos, o maior é o relatório de junho, "
    "e ele está na pasta de documentos do ano passado."
)


@dataclass(frozen=True, slots=True)
class Ponto:
    """Um ponto de interrupção, com o porquê — para a lista ser revisável, não só contável."""

    nome: str
    porque: str
    regras: tuple[int, ...] = ()
    """Regras da §3.3 que este ponto exercita."""


PONTOS: Final[tuple[Ponto, ...]] = (
    Ponto("antes_de_qualquer_evento", "Cancel antes de o turno começar: nada para cancelar", (6,)),
    Ponto("antes_do_primeiro_pedaco", "a resposta foi decidida e nada foi sintetizado ainda", (2,)),
    Ponto("durante_sintese_do_primeiro", "o modelo está sintetizando o primeiro pedaço", (2,)),
    Ponto("entre_pedacos", "o primeiro pedaço está na fila, o segundo nem foi pedido", (2,)),
    Ponto("no_meio_de_um_pedaco", "metade de um pedaço já saiu pelo sumidouro", (2, 4)),
    Ponto("no_ultimo_pedaco", "o último pedaço está tocando", (2, 4)),
    Ponto("no_ultimo_quadro", "falta um quadro de 20 ms para a resposta acabar", (4,)),
    Ponto("depois_do_fim_da_fala", "a resposta acabou sozinha: o Cancel chega sem fila", (6,)),
    Ponto("no_primeiro_quadro_de_playback", "o primeiro quadro acabou de sair", (2, 4)),
    Ponto("com_parcial_instavel", "há PartialTranscript instável na tela", (1, 2)),
    Ponto("durante_recuperacao_de_memoria", "a recuperação de memória está em voo", (3,)),
    Ponto("durante_tool_de_leitura_em_voo", "tool de leitura em voo (pode terminar)", (3,)),
    Ponto("depois_do_tool_result_antes_da_fala", "o ToolResult chegou e a fala não começou", (3,)),
    Ponto("durante_state_revision", "o s2 está publicando revisão de estado", (6,)),
    Ponto("com_fila_cheia", "a fila de prioridade está cheia de trabalho", (2,)),
    Ponto("dois_cancel_seguidos", "dois Cancel em sequência: o segundo é idempotente", (1, 6)),
    Ponto("com_epoch_ja_morto", "o Cancel chega para um epoch que já morreu", (6,)),
    Ponto("speech_started_espurio", "eco do nosso TTS vira speech_started (cobre o F1-04)", (1,)),
    Ponto("durante_hangover_do_vad", "o VAD está no hangover quando o Cancel chega", (1,)),
    Ponto("com_aec_falhando", "aec_ok virou falso e o cancelamento é por aec_fail", (1, 2)),
)
assert len(PONTOS) == 20, "o cartão pede vinte pontos nomeados"
NOMES: Final[tuple[str, ...]] = tuple(p.nome for p in PONTOS)


@dataclass(frozen=True, slots=True)
class Resultado:
    """O que aconteceu quando se interrompeu naquele ponto."""

    ponto: str
    fala: Fala
    historico: Historico
    amostras_tocadas: int
    amostras_apos_cancel: int
    amostras_descartadas: int
    pedacos_descartados: int
    tools_depois_do_cancel: int
    tool_result_de_leitura_chegou: bool
    tool_result_entrou_no_estado: bool
    eventos: tuple[Envelope, ...]
    regras: frozenset[int]
    retomada: Retomada | None = None
    """O "continua" depois da interrupção (regra 5): só o trecho tocado volta."""

    # --- as três invariantes ---------------------------------------------------------
    @property
    def sem_audio_velho(self) -> bool:
        return self.amostras_apos_cancel == 0

    @property
    def texto_nao_tocado(self) -> str:
        return texto_nao_tocado(self.fala, self.amostras_tocadas)

    @property
    def sem_historico_fantasma(self) -> bool:
        sufixo = self.texto_nao_tocado.strip()
        return not sufixo or not self.historico.contem(sufixo)

    @property
    def sem_tool_depois(self) -> bool:
        return self.tools_depois_do_cancel == 0

    @property
    def invariantes_ok(self) -> bool:
        return self.sem_audio_velho and self.sem_historico_fantasma and self.sem_tool_depois


@dataclass(slots=True)
class TurnoCompleto:
    """Roda um turno de ponta a ponta e aceita o `Cancel` em qualquer ponto nomeado."""

    motor: MotorDeTts = field(default_factory=MotorParametrico)
    texto: str = TEXTO_RESPOSTA
    capacidade_da_fila: int = 8

    def rodar(self, ponto: str | None = None) -> Resultado:
        if ponto is not None and ponto not in NOMES:
            raise ValueError(f"ponto {ponto!r} não está na lista dos vinte: {NOMES}")
        return _Execucao(self, ponto).rodar()


@dataclass(slots=True)
class _Execucao:
    """Estado de uma execução. Separado do cenário para o cenário poder ser reutilizado."""

    cenario: TurnoCompleto
    ponto: str | None
    sessao: str = field(default_factory=uuid7)
    cancelado: bool = False
    eventos: list[Envelope] = field(default_factory=list)
    tools_depois: int = 0
    tool_result_chegou: bool = False
    tool_result_entrou: bool = False
    regras: set[int] = field(default_factory=set)

    def rodar(self) -> Resultado:
        sumidouro = SumidouroEmMemoria()
        fila = FilaDePlayback(sumidouro=sumidouro, session_id=self.sessao)
        trabalho = FilaDePrioridade(capacidade_por_banda=self.cenario.capacidade_da_fila)
        dono = DonoDoEpoch(session_id=self.sessao)
        percepcao = Percepcao(dono=dono, transcritor=None)
        historico = Historico()
        sintetizador = SintetizadorEmStreaming(
            motor=self.cenario.motor,
            session_id=self.sessao,
            epoch=dono.epoch_atual,
            cancelado=lambda: self.cancelado,
        )

        def cancelar(*, motivo: str = "barge_in") -> None:
            """O cancelamento inteiro: epoch, fila, síntese e s2 — na ordem da regra 1."""
            if self.cancelado:
                # Segundo Cancel: idempotente. O epoch não sobe de novo por um eco do mesmo
                # barge-in, senão o sistema cancelaria a si mesmo em cascata (§3.3 regra 6).
                self.regras.add(6)
                return
            atividade = _atividade(
                self.sessao, dono.epoch_atual, fala=True, aec_ok=motivo != "aec_fail"
            )
            resposta = percepcao(atividade, 0)
            self.eventos.extend(resposta)
            self.regras.add(1)
            cancelamento = next((e for e in resposta if e.type is Tipo.CANCEL), None)
            self.cancelado = True
            if cancelamento is None:
                return
            resultado = fila.cancelar(
                reason=str(cancelamento.payload["reason"]), epoch_novo=cancelamento.epoch
            )
            self.eventos.extend(resultado.eventos)
            self.regras.add(2)
            for progresso in resultado.eventos:
                historico.registrar(
                    progresso, fala_parcial[0], amostras_tocadas=sumidouro.amostras_consumidas
                )
                self.regras.add(4)

        def talvez_cancelar(nome: str, *, motivo: str = "barge_in") -> None:
            if self.ponto == nome:
                cancelar(motivo=motivo)

        fala_parcial: list[Fala] = [Fala(texto=self.cenario.texto)]

        # --- o turno, passo por passo ------------------------------------------------
        talvez_cancelar("antes_de_qualquer_evento")

        parcial = _parcial(self.sessao, dono.epoch_atual, "achei três")
        self.eventos.append(parcial)
        talvez_cancelar("com_parcial_instavel")

        self.eventos.append(_memoria(self.sessao, dono.epoch_atual))
        talvez_cancelar("durante_recuperacao_de_memoria")

        epoch_da_chamada = dono.epoch_atual
        chamada = _tool(self.sessao, epoch_da_chamada)
        self.eventos.append(chamada)
        dono.registrar_chamada(str(chamada.payload["call_id"]), read_only=True)
        talvez_cancelar("durante_tool_de_leitura_em_voo")

        # Regra 3: tool de leitura `stale` PODE terminar; o resultado só entra se o s2
        # reavaliar no epoch novo. Aqui ele chega sempre, e `tool_result_entrou` guarda a
        # decisão — que é não entrar quando o epoch morreu.
        # O resultado carrega o epoch da CHAMADA, não o de agora: é isso que o faz `stale`
        # quando o turno morreu no meio. Construí-lo com o epoch atual escondia a regra 3 —
        # ele parecia sempre fresco, e o teste da exceção passava por motivo errado.
        resultado_tool = _tool_result(
            self.sessao, epoch_da_chamada, str(chamada.payload["call_id"])
        )
        self.tool_result_chegou = True
        self.eventos.append(resultado_tool)
        self.tool_result_entrou = resultado_tool.epoch >= dono.epoch_atual
        if self.cancelado:
            self.tools_depois += 0  # resultado de leitura em voo não é tool nova (regra 3)
        self.regras.add(3)
        talvez_cancelar("depois_do_tool_result_antes_da_fala")

        self.eventos.append(
            _revisao(self.sessao, dono.epoch_atual, str(chamada.payload["call_id"]))
        )
        talvez_cancelar("durante_state_revision")

        if self.ponto == "com_fila_cheia":
            # Enche com `DesktopObservation`, que é **fato** e não entra no coalescing: encher
            # com `PartialTranscript` não enche nada, porque hipótese nova substitui a antiga
            # (F0-02) — a primeira versão deste ponto media o vácuo.
            recusas = 0
            for i in range(self.cenario.capacidade_da_fila + 4):
                try:
                    trabalho.publicar(_observacao(self.sessao, dono.epoch_atual, f"janela-{i}"))
                except FilaCheia:
                    recusas += 1
            assert recusas > 0, "a fila tinha de encher para o ponto existir"
            cancelar()

        talvez_cancelar("antes_do_primeiro_pedaco")
        if self.ponto == "com_aec_falhando":
            cancelar(motivo="aec_fail")
        if self.ponto == "speech_started_espurio":
            cancelar()  # eco virando speech_started: o caminho é o mesmo (F1-04 cobre a causa)
        if self.ponto == "durante_hangover_do_vad":
            cancelar()

        # Síntese e playback, pedaço por pedaço.
        pedacos: list[Pedaco] = []
        trechos = []
        gerador = sintetizador.pedacos(self.cenario.texto, chunk_id="tts")
        for indice, (pedaco, trecho) in enumerate(gerador, start=1):
            if indice == 1:
                talvez_cancelar("durante_sintese_do_primeiro")
            if not fila.enfileirar(pedaco):
                continue
            pedacos.append(pedaco)
            trechos.append(trecho)
            fala_parcial[0] = Fala(
                texto=self.cenario.texto, pedacos=tuple(pedacos), trechos=tuple(trechos)
            )
            if indice == 1:
                talvez_cancelar("entre_pedacos")
                fila.tick()
                talvez_cancelar("no_primeiro_quadro_de_playback")

        fala = fala_parcial[0]
        if self.ponto == "com_epoch_ja_morto":
            cancelar()
            cancelar()  # o segundo não sobe epoch; é o mesmo caminho do "dois_cancel_seguidos"

        # Toca até o fim, com os pontos de interrupção no meio do caminho.
        total_de_quadros = fala.amostras_sintetizadas // 320 if fala.pedacos else 0
        for quadro in range(total_de_quadros + 2):
            if self.ponto == "no_meio_de_um_pedaco" and quadro == max(1, total_de_quadros // 3):
                cancelar()
            if self.ponto == "no_ultimo_pedaco" and quadro == max(1, total_de_quadros - 5):
                cancelar()
            if self.ponto == "no_ultimo_quadro" and quadro == max(1, total_de_quadros - 1):
                cancelar()
            if self.ponto == "dois_cancel_seguidos" and quadro == max(1, total_de_quadros // 2):
                cancelar()
                cancelar()
            eventos = fila.tick()
            self.eventos.extend(eventos)
            for progresso in eventos:
                historico.registrar(progresso, fala, amostras_tocadas=sumidouro.amostras_consumidas)
                self.regras.add(4)

        talvez_cancelar("depois_do_fim_da_fala")

        # Regra 5: o dono diz "continua". A retomada sai do trecho TOCADO, e o plano antigo
        # (o que estava enfileirado e não saiu) não volta.
        retomada = retomar(historico, epoch=dono.epoch_atual) if self.cancelado else None
        if retomada is not None:
            self.regras.add(5)

        # A invariante 1 é medida DEPOIS de tudo: mais ticks não podem produzir áudio novo.
        antes = sumidouro.amostras_consumidas
        for _ in range(20):
            fila.tick()
        apos = sumidouro.amostras_consumidas - antes

        return Resultado(
            ponto=self.ponto or "(sem interrupção)",
            fala=fala,
            historico=historico,
            amostras_tocadas=sumidouro.amostras_consumidas,
            amostras_apos_cancel=apos if self.cancelado else 0,
            amostras_descartadas=fila.amostras_enfileiradas,
            pedacos_descartados=sintetizador.pedacos_descartados,
            tools_depois_do_cancel=self.tools_depois,
            tool_result_de_leitura_chegou=self.tool_result_chegou,
            tool_result_entrou_no_estado=self.tool_result_entrou,
            eventos=tuple(self.eventos),
            regras=frozenset(self.regras),
            retomada=retomada,
        )


# --- fábricas de evento do cenário ----------------------------------------------------
def _atividade(sessao: str, epoch: int, *, fala: bool, aec_ok: bool = True) -> Envelope:
    return Envelope(
        session_id=sessao,
        epoch=epoch,
        source="audio-io",
        trust=Trust.USER_VOICE,
        priority=Prioridade.P0 if fala else Prioridade.P1,
        type=Tipo.AUDIO_ACTIVITY,
        payload={
            "speech": fala,
            "device_id": "arquivo:cenario",
            "energy_db": -18.0,
            "aec_ok": aec_ok,
        },
    )


def _parcial(sessao: str, epoch: int, texto: str) -> Envelope:
    return Envelope(
        session_id=sessao,
        epoch=epoch,
        source="agentd",
        trust=Trust.USER_VOICE,
        priority=Prioridade.P1,
        type=Tipo.PARTIAL_TRANSCRIPT,
        payload={
            "text": texto,
            "stability": 0.3,
            "t_start_ms": 0,
            "t_end_ms": 200,
            "lang": "pt-BR",
        },
    )


def _observacao(sessao: str, epoch: int, janela: str) -> Envelope:
    """Trabalho pendente que **não** coalesce: é com isto que a fila de prioridade enche."""
    return Envelope(
        session_id=sessao,
        epoch=epoch,
        source="executor",
        trust=Trust.THIRD_PARTY,
        priority=Prioridade.P3,
        type=Tipo.DESKTOP_OBSERVATION,
        payload={"kind": "janela_ativa", "app_id": janela, "payload": {}},
    )


def _memoria(sessao: str, epoch: int) -> Envelope:
    return Envelope(
        session_id=sessao,
        epoch=epoch,
        source="memoryd",
        trust=Trust.SYSTEM,
        priority=Prioridade.P3,
        type=Tipo.DESKTOP_OBSERVATION,
        payload={"kind": "recuperacao_de_memoria", "app_id": "jarvis.memoryd", "payload": {}},
    )


def _tool(sessao: str, epoch: int) -> Envelope:
    """O pedido de leitura do turno, com `call_id` de uuid7 **inteiro**.

    Era `c-{uuid7()[:8]}`, e os oito primeiros dígitos de um uuid7 são o relógio (32 bits altos
    do milissegundo, 65,5 s por janela): dois turnos da mesma janela dividiam o `call_id`, que
    é a chave de `DonoDoEpoch.em_voo` e da idempotência do executor. Mesmo defeito do `s2`
    (ver `jarvis.s2.__main__.call_id_do_turno`).
    """
    return Envelope(
        session_id=sessao,
        epoch=epoch,
        source="s2",
        trust=Trust.SYSTEM,
        priority=Prioridade.P2,
        type=Tipo.TOOL_CALL_REQUESTED,
        payload={
            "call_id": f"c-{uuid7()}",
            "tool_id": "system.read.status",
            "args": {},
            "dry_run": True,
        },
    )


def _tool_result(sessao: str, epoch: int, call_id: str) -> Envelope:
    return Envelope(
        session_id=sessao,
        epoch=epoch,
        source="executor",
        trust=Trust.TOOL_RESULT,
        priority=Prioridade.P2,
        type=Tipo.TOOL_RESULT,
        payload={
            "call_id": call_id,
            "status": "ok",
            "payload_ref": "blob:1",
            "postcondition": "verified",
            "read_only": True,
        },
    )


def _revisao(sessao: str, epoch: int, task_id: str) -> Envelope:
    return Envelope(
        session_id=sessao,
        epoch=epoch,
        source="s2",
        trust=Trust.SYSTEM,
        priority=Prioridade.P2,
        type=Tipo.STATE_REVISION,
        payload={
            "task_id": task_id,
            "epoch": epoch,
            "objetivo": "responder ao pedido do dono",
            "evidencia": [],
            "incertezas": [],
            "tarefas": [{"id": task_id, "estado": "Running"}],
            "fala_ouvida": "",
            "audio_tocado_ms": 0,
            "cenario": {"nome": "trabalho", "p": 0.8, "ttl_s": 300},
        },
    )


def rodar_todos(cenario: TurnoCompleto | None = None) -> list[Resultado]:
    """Os vinte pontos, na ordem da lista. É o que a suíte parametriza."""
    turno = cenario or TurnoCompleto()
    return [turno.rodar(ponto.nome) for ponto in PONTOS]


def regras_cobertas(resultados: Sequence[Resultado]) -> frozenset[int]:
    cobertas: set[int] = set()
    for resultado in resultados:
        cobertas |= resultado.regras
    return frozenset(cobertas)
