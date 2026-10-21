"""Stub determinístico do `s2`: estado de trabalho e pedido de tool, sem LLM (cartão F0-03).

O que este esqueleto prova: o reasoner reage a evento (nunca a laço cego), pede capacidade
pelo `tool_id` do catálogo e **não publica fala de epoch morto**.

**É aqui que a perda de rede é detectada** (cartão F1-14). O `s2` é o processo que, no produto,
fala com o serviço remoto — então o adaptador com prazo nosso mora no caminho dele, e um pedido
que cai **não entra no barramento**: nada pendurado em fila (§3.3 regra 5). Quem mostra e
degrada é a `ui`; quem fala o aviso é o `agentd`.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable

from jarvis.barramento.envelope import Envelope, Prioridade, Tipo, Trust
from jarvis.processo import Processo, analisador
from jarvis.rede import AdaptadorRemoto, sonda_do_ambiente

TOOL_DO_ESQUELETO = "system.read.status"
SERVICO = "o serviço de raciocínio"
INTERVALO_DEGRADADO_S = 2.0
"""Degradado, pergunta de dois em dois segundos: é o que faz a volta ser notada sem tráfego."""
INTERVALO_SAUDAVEL_S = 5.0
"""Com o serviço de pé a chamada é quem detecta a queda — mas um batimento mais lento existe
para a `ui` não ficar dizendo que está tudo bem enquanto a rede caiu sem ninguém falar."""


def reagir(processo: Processo, envelope: Envelope, veredito: str) -> list[Envelope]:
    if envelope.epoch < processo.epoch:
        # §3.3 regra 6 e aceite (c): nada de epoch morto sai daqui, nem como fala.
        return []
    if envelope.type is Tipo.CANCEL:
        processo.epoch = envelope.epoch
        return []
    if envelope.type is Tipo.PARTIAL_TRANSCRIPT:
        # Cartão F1-06, §3.4: o parcial é **hipótese**. Dez parciais em 200 ms não viram dez
        # raciocínios: o barramento coalesce (PartialTranscript está em TIPOS_COALESCIVEIS) e o
        # que chega aqui é a hipótese mais nova — uma revisão de estado, não dez.
        return [_revisao_de_hipotese(processo, envelope)]
    if envelope.type is Tipo.FINAL_TRANSCRIPT:
        return [_pedido_de_tool(processo, envelope)]
    if envelope.type is Tipo.TOOL_RESULT and veredito != "aceitar_stale":
        return [_revisao_de_estado(processo, envelope)]
    return []


def reacao_com_rede(adaptador: AdaptadorRemoto) -> Callable[..., list[Envelope]]:
    """A mesma reação, com o passo remoto atrás do adaptador do F1-14.

    O único passo que depende do serviço é transformar a transcrição final em **pedido de
    tool**: é o que, no produto, é o raciocínio remoto. Caindo a rede, isso não vira evento —
    e o `call_id` daquele pedido fica registrado como descartado, para a volta da rede **não**
    o ressuscitar.
    """

    def reagir_com_adaptador(
        processo: Processo, envelope: Envelope, veredito: str
    ) -> list[Envelope]:
        if envelope.type is not Tipo.FINAL_TRANSCRIPT or envelope.epoch < processo.epoch:
            return reagir(processo, envelope, veredito)
        pedido = adaptador.chamar(
            lambda _prazo: _pedido_de_tool(processo, envelope),
            call_id=call_id_do_turno(envelope),
            epoch=envelope.epoch,
        )
        return [] if pedido is None else [pedido]

    return reagir_com_adaptador


def call_id_do_turno(origem: Envelope) -> str:
    """O `call_id` do pedido é a identidade **inteira** da transcrição que o originou.

    **Isto é correção de um defeito que a repetição do teste do F1-14 pegou.** O id era
    `c-{event_id[:8]}`, e os oito primeiros dígitos de um uuid7 são os 32 bits altos do
    milissegundo: só mudam a cada 65,5 s. Todo turno dentro da mesma janela ganhava o **mesmo**
    `call_id`, e três coisas erradas saíam daí: depois que um pedido caía com a rede, cada turno
    **novo** da janela era recusado como "descartado" (a escuta voltava, mas o Jarvis ficava
    surdo por até um minuto); o executor engolia o segundo turno da janela por idempotência; e,
    quando a janela virava entre a queda e a volta, os turnos novos passavam — o que fazia o
    teste de integração falhar uma vez em vinte e parecer pedido velho ressuscitando.

    Com o id inteiro, a mesma transcrição reentregue tem o mesmo `call_id` — e continua
    descartada para sempre (§3.3 regra 5) —, e turno novo tem `call_id` novo.
    """
    return f"c-{origem.event_id}"


def _revisao_de_hipotese(processo: Processo, origem: Envelope) -> Envelope:
    """Revisão de estado a partir de um parcial: o que o dono parece estar pedindo, por ora."""
    return Envelope(
        session_id=processo.session_id,
        epoch=origem.epoch,
        source="s2",
        trust=Trust.SYSTEM,
        priority=Prioridade.P2,
        type=Tipo.STATE_REVISION,
        payload={
            "task_id": f"hipotese-{origem.epoch}",
            "epoch": origem.epoch,
            "objetivo": "entender o pedido em curso",
            "evidencia": [],
            "incertezas": ["transcrição parcial, pode mudar"],
            "tarefas": [{"id": f"hipotese-{origem.epoch}", "estado": "Draft"}],
            "fala_ouvida": str(origem.payload["text"]),
            "audio_tocado_ms": 0,
            "cenario": {"nome": "trabalho", "p": 0.5, "ttl_s": 300},
        },
    )


def _pedido_de_tool(processo: Processo, origem: Envelope) -> Envelope:
    return Envelope(
        session_id=processo.session_id,
        epoch=origem.epoch,
        source="s2",
        trust=Trust.SYSTEM,
        priority=Prioridade.P2,
        type=Tipo.TOOL_CALL_REQUESTED,
        payload={
            "call_id": call_id_do_turno(origem),
            "tool_id": TOOL_DO_ESQUELETO,
            "args": {"sobre": origem.payload["text"]},
            "dry_run": True,
        },
    )


def _revisao_de_estado(processo: Processo, origem: Envelope) -> Envelope:
    return Envelope(
        session_id=processo.session_id,
        epoch=origem.epoch,
        source="s2",
        trust=Trust.SYSTEM,
        priority=Prioridade.P2,
        type=Tipo.STATE_REVISION,
        payload={
            "task_id": str(origem.payload["call_id"]),
            "epoch": origem.epoch,
            "objetivo": "responder ao pedido do dono",
            "evidencia": [
                {"ref": str(origem.payload["call_id"]), "resumo": str(origem.payload["status"])}
            ],
            "incertezas": [],
            "tarefas": [{"id": str(origem.payload["call_id"]), "estado": "Succeeded"}],
            "fala_ouvida": "",
            "audio_tocado_ms": 0,
            "cenario": {"nome": "esqueleto", "p": 1.0, "ttl_s": 60},
        },
    )


def main(argv: list[str] | None = None) -> int:
    """O laço do `s2`. Com `--rede`, o passo remoto passa pelo adaptador do F1-14."""
    analisa = analisador("s2")
    analisa.add_argument(
        "--rede",
        action="store_true",
        help="liga o adaptador remoto: prazo nosso, degradação declarada e nada pendurado",
    )
    args = analisa.parse_args(argv)
    adaptador = (
        AdaptadorRemoto(servico=SERVICO, raiz=args.raiz, sonda=sonda_do_ambiente())
        if args.rede
        else None
    )
    processo = Processo(
        nome="s2",
        raiz=args.raiz,
        reacao=reagir if adaptador is None else reacao_com_rede(adaptador),
    )
    processo.abrir()
    try:
        if adaptador is None:
            processo.rodar(timeout=args.timeout)
            return 0
        fim = None if args.timeout is None else time.monotonic() + args.timeout
        # Sem evento nenhum o laço ainda tem de descobrir que a rede caiu ou voltou: é o
        # que o aceite (a) e o (c) cobram. Daí o batimento, mais rápido quando degradado.
        adaptador.conferir(epoch=processo.epoch)
        sondado = time.monotonic()
        while fim is None or time.monotonic() < fim:
            for envelope, veredito in processo.recebidos(timeout=0.05):
                for resposta in processo.reacao(processo, envelope, veredito):
                    processo.publicar(resposta)
            agora = time.monotonic()
            intervalo = INTERVALO_DEGRADADO_S if adaptador.degradado else INTERVALO_SAUDAVEL_S
            if agora - sondado >= intervalo:
                adaptador.conferir(epoch=processo.epoch)
                sondado = agora
    finally:
        processo.fechar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
