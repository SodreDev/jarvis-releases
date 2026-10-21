"""Do pedido de ferramenta ao efeito, com o portão contextual no meio (pedido do dono, 2026-10-19).

A ordem, com quem manda em cada passo:

1. **executor + PDP** (`ExecutorDeFerramentas.avaliar`): catálogo, contrato, `allow | confirm |
   deny`. `deny` acaba aqui — o Jev nem é consultado;
2. **Jev** (`PortaoDeAcao.classificar`): fazer / pedir permissão / não fazer, com o pedido do dono,
   a conversa recente e a situação. Só aperta: "não fazer" veta; nada aqui afrouxa o PDP;
3. **autorização explícita** (`AutorizacoesExplicitas`): o "pedir permissão" do Jev não vira
   pergunta se o dono disse esta ação, com estes argumentos, neste turno — uma vez. O `confirm` do
   PDP não é tocado;
4. `allow` do PDP e "fazer" → roda **agora**, no turno (o motor precisa do resultado);
5. o resto vira uma **pendência** (`RegistroDePendencias`): o Jarvis diz a pergunta e o turno
   acaba, sem prender o laço de voz;
6. o "sim" (voz, texto ou clique) resolve **só** aquela pendência, válida, uma vez; e a execução
   vai para uma **tarefa** (`GestorDeTarefas`, motor direto), com o "sim" valendo só para a
   chamada exata. O Jarvis segue conversando; o fim chega pela fila de avisos (ADR-0025), que
   nunca corta fala em andamento.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from jarvis.executor.ferramentas import (
    Cancelado,
    Confirmacao,
    Confirmar,
    ExecutorDeFerramentas,
    ResultadoDeFerramenta,
    negar_sempre,
)
from jarvis.politica.memoria import Proveniencia
from jarvis.politica.objetivo import Objetivo
from jarvis.politica.pdp import Veredito
from jarvis.s2.motor import Mensagem, PedidoDeTool
from jarvis.s2.pendencias import Pendencia, PendenciaOcupada, RegistroDePendencias
from jarvis.s2.portao import AutorizacoesExplicitas, Classe, PortaoDeAcao, RespostaDoDono
from jarvis.tarefas.gestor import FORA_DA_ALLOWLIST, MotorDireto, TarefaRecusada


@dataclass(frozen=True, slots=True)
class LeituraDaResposta:
    """O que a fala do dono fez com a pendência aberta."""

    frase: str = ""
    """Não vazia: o turno é **só** isto (a pendência foi resolvida); o motor não é chamado — e
    não tem como propor a mesma ação de novo."""
    nota: str = ""
    """Não vazia: vai ao prompt de sistema do turno (a pendência caiu: o dono mudou de assunto)."""
    resultado: ResultadoDeFerramenta | None = None


@dataclass(slots=True)
class FluxoDeAcao:
    portao: PortaoDeAcao
    pendencias: RegistroDePendencias
    autorizacoes: AutorizacoesExplicitas

    def chamar(
        self,
        executor: ExecutorDeFerramentas,
        pedido: PedidoDeTool,
        *,
        pedido_do_dono: str,
        mensagens: Sequence[Mensagem],
        cancelado: Cancelado,
        confirmar: Confirmar = negar_sempre,
        session_id: str = "",
        proveniencia: Proveniencia | None = None,
    ) -> ResultadoDeFerramenta:
        avaliacao = executor.avaliar(
            pedido.tool_id, pedido.args, session_id=session_id, proveniencia=proveniencia
        )
        if isinstance(avaliacao, ResultadoDeFerramenta):
            return avaliacao
        veredito = avaliacao.decisao.veredito
        if veredito is Veredito.DENY:
            return executor.concluir(avaliacao, cancelado=cancelado)  # nega, com a sugestão
        tool_id, chamada = avaliacao.tool_id, avaliacao.pedido.call_id
        entregue = False
        """A avaliação já foi concluída ou descartada: o grant deixou de ser desta função."""
        try:
            manifesto = executor.manifestos[tool_id]
            classificacao = self.portao.classificar(
                tool_id=tool_id,
                titulo=str(manifesto["title"]),
                argumentos=avaliacao.argumentos,
                pedido_do_dono=pedido_do_dono,
                mensagens=mensagens,
                situacao=_situacao(manifesto, executor, avaliacao.pedido.contaminado),
                cancelado=cancelado,
                objetivo=executor.objetivo,
            )
            classe, motivo = classificacao.classe, classificacao.motivo

            def trilhar(decisao: str) -> None:
                if executor.trilha is not None:
                    executor.trilha.evento(
                        "portao",
                        tool_id=tool_id,
                        pdp=str(veredito),
                        jev=motivo,
                        decisao=decisao,
                        ms=round(classificacao.ms, 1),
                    )

            if classe is Classe.NAO_FAZER:
                trilhar("negado")
                entregue = True
                executor.descartar(
                    avaliacao, "negado", f"portão contextual: {motivo}", causa="portao_negou"
                )
                return ResultadoDeFerramenta(
                    tool_id,
                    "negado",
                    motivo=(
                        f"não fiz: o portão contextual classificou como não fazer ({motivo}). Se o "
                        "dono quiser mesmo, ele pede de novo, com as palavras dele."
                    ),
                    call_id=chamada,
                )
            if classe is Classe.PEDIR_PERMISSAO and veredito is Veredito.ALLOW:
                if cabe_no_objetivo(executor.objetivo, tool_id, avaliacao.argumentos):
                    # Dentro do objetivo do dono, navegar/ler/clicar/digitar/buscar não pergunta:
                    # o Jev só veta (dono, 2026-10-20). O PDP e o risco dinâmico seguem valendo.
                    classe = Classe.FAZER
                    trilhar("objetivo")
                elif self.autorizacoes.consumir(
                    tool_id,
                    pedido.args,
                    p_explicito=classificacao.p_explicito,
                    limiar=self.portao.limiar_explicito,
                ):
                    classe = Classe.FAZER
                    trilhar("explicita")
            elif veredito is Veredito.ALLOW and classe is Classe.FAZER:
                trilhar("fazer")
            if veredito is Veredito.ALLOW and classe is Classe.FAZER:
                entregue = True  # daqui em diante o grant é do `concluir`
                return executor.concluir(
                    avaliacao, cancelado=cancelado, confirmar=confirmar, proveniencia=proveniencia
                )
            por_que = (
                avaliacao.decisao.motivo
                if veredito is Veredito.CONFIRM
                else f"o portão contextual pediu permissão ({motivo})"
            )
            causa = (
                "confirmacao_do_pdp" if veredito is Veredito.CONFIRM else "portao_pediu_permissao"
            )
            pergunta = executor.pergunta_de(avaliacao, por_que, causa)
            trilhar("pendente")
            if executor.trilha is not None:
                executor.trilha.evento(
                    "permissao",
                    tool_id=tool_id,
                    origem="pdp" if veredito is Veredito.CONFIRM else "portao",
                    motivo=causa,
                    resposta="pendente",
                )
            entregue = True
            executor.descartar(
                avaliacao,
                "pendente",
                f"esperando o sim do dono: {por_que}",
                causa="esperando_o_dono",
            )
            try:
                self.pendencias.abrir(pergunta, contaminado=avaliacao.pedido.contaminado)
            except PendenciaOcupada:
                return ResultadoDeFerramenta(
                    tool_id,
                    "negado",
                    motivo="já há uma pergunta pendente com o dono: espere a resposta dele",
                    call_id=chamada,
                )
            return ResultadoDeFerramenta(
                tool_id,
                "pendente",
                motivo=(
                    "nada foi feito ainda: a ação espera o sim do dono, e a pergunta já foi dita a "
                    "ele. Não repita a pergunta nem diga que fez; espere a resposta."
                ),
                call_id=chamada,
                aviso=f"Preciso do seu sim para {pergunta.detalhe}. Posso?",
            )
        finally:
            if not entregue:
                # Uma exceção entre o PDP e a entrega (revisão de bf9102c): nada rodou, e o grant
                # aberto pelo `avaliar` seguraria a raiz até o TTL. Solta já, e a auditoria diz.
                executor.descartar(
                    avaliacao, "erro", "o portão falhou antes de decidir", causa="portao_falhou"
                )

    def ler_a_resposta(
        self,
        executor: ExecutorDeFerramentas,
        fala: str,
        *,
        mensagens: Sequence[Mensagem],
        cancelado: Cancelado,
    ) -> LeituraDaResposta:
        """A fala do dono, lida contra a pendência aberta (se houver uma ainda válida)."""
        pendencia = self.pendencias.valida()
        if pendencia is None:
            return LeituraDaResposta()
        detalhe = pendencia.pergunta.detalhe
        resposta = self.portao.interpretar_resposta(
            fala, acao_pendente=detalhe, mensagens=mensagens, cancelado=cancelado
        )
        if resposta is RespostaDoDono.SIM:
            resultado = self.resolver(executor, pendencia.id, sim=True)
            if resultado is None:  # venceu entre a leitura e o tomar: o "sim" não vale mais
                return LeituraDaResposta(
                    frase=f"A pergunta sobre {detalhe} já tinha vencido; não fiz nada.",
                )
            if resultado.status == "despachado":
                frase = f"Certo, estou fazendo: {detalhe}. Aviso quando terminar."
            elif resultado.status == "ok":
                frase = f"Feito: {detalhe}."
            else:
                frase = f"Não deu para fazer {detalhe}: {resultado.motivo}."
            return LeituraDaResposta(frase=frase, resultado=resultado)
        self.pendencias.cancelar()
        if resposta is RespostaDoDono.NAO:
            return LeituraDaResposta(frase=f"Tudo bem, não vou fazer isso ({detalhe}).")
        return LeituraDaResposta(
            nota=(
                f"A pergunta que estava pendente («{detalhe}») foi cancelada porque o dono falou "
                "de outra coisa; nada foi feito. Responda ao que ele disse agora; se ele ainda "
                "quiser aquela ação, ele pede de novo."
            )
        )

    def resolver(
        self, executor: ExecutorDeFerramentas, pendencia_id: str, *, sim: bool
    ) -> ResultadoDeFerramenta | None:
        """Resposta do dono a **esta** pendência. `None` = não havia (vencida, outra, já usada)."""
        pendencia = self.pendencias.tomar(pendencia_id)
        if pendencia is None:
            return None
        if not sim:
            return ResultadoDeFerramenta(
                pendencia.pergunta.tool_id,
                "negado",
                motivo="o dono disse não",
                call_id=pendencia.id,
            )
        return _despachar(executor, pendencia)


def _despachar(executor: ExecutorDeFerramentas, pendencia: Pendencia) -> ResultadoDeFerramenta:
    """A execução autorizada vai para uma tarefa; o "sim" vale só para a chamada exata."""
    pergunta = pendencia.pergunta
    ja_confirmado = _sim_de_uso_unico(pergunta)
    if pergunta.tool_id.startswith(FORA_DA_ALLOWLIST):
        # `tarefa.*` e `acao.desfazer` não rodam dentro de tarefa (profundidade 1) e são só
        # registro: rodam aqui mesmo, ainda pelo PDP.
        return executor.executar(
            pergunta.tool_id,
            pergunta.argumentos,
            cancelado=lambda: False,
            confirmar=ja_confirmado,
        )
    gestor = executor.tarefas
    if gestor is None:
        return ResultadoDeFerramenta(
            pergunta.tool_id,
            "negado",
            motivo="não há gestor de tarefas nesta sessão para rodar em segundo plano",
            call_id=pendencia.id,
        )
    try:
        tarefa = gestor.iniciar(
            pergunta.detalhe,
            pergunta.tool_id,
            pergunta.argumentos,
            contaminado=pendencia.contaminado,
            motor=MotorDireto(),
            confirmar=ja_confirmado,
        )
    except TarefaRecusada as erro:
        return ResultadoDeFerramenta(
            pergunta.tool_id, "negado", motivo=str(erro), call_id=pendencia.id
        )
    return ResultadoDeFerramenta(
        pergunta.tool_id, "despachado", dados={"tarefa_id": tarefa.id}, call_id=pendencia.id
    )


def _sim_de_uso_unico(confirmada: Confirmacao) -> Confirmar:
    """Responde "sim" uma vez, e só à pergunta da mesma ferramenta com os mesmos argumentos.

    Qualquer outra pergunta (um segundo "sim" por ação do navegador, outra ferramenta) recebe
    "não daqui" — e cai na janela, como antes."""
    usado = False

    def responder(pergunta: Confirmacao) -> bool:
        nonlocal usado
        # A pergunta por ação (o alvo é envio, banco, terminal em foco…) traz `argumentos` vazios:
        # sem esta trava, o "sim" a `input.mouse.click {}` respondia também a ela (revisão de
        # 2026-10-19), e o clique saía sem o dono ver o que estava sob ele.
        if usado or pergunta.por_acao or pergunta.tool_id != confirmada.tool_id:
            return False
        if dict(pergunta.argumentos) != dict(confirmada.argumentos):
            return False
        usado = True
        return True

    return responder


NAVEGACAO_DO_OBJETIVO: Final = frozenset(
    {
        "browser.tabs",
        "browser.read",
        "browser.navigate",
        "browser.click",
        "browser.type",
        "browser.scroll",
        "browser.inspecionar",
        "browser.acionar",
        "sites.open",
        "web.buscar",
        "web.ler",
        "web.canal_videos",
    }
)
"""O que um objetivo de navegação faz a cada passo. Fora daqui (apagar, enviar, instalar, mexer em
arquivo, teclado virtual), o "pedir permissão" do Jev continua virando pergunta."""


def cabe_no_objetivo(
    objetivo: Objetivo | None, tool_id: str, argumentos: Mapping[str, Any]
) -> bool:
    """A chamada é um passo de navegação e o endereço dela (se tem) está dentro do objetivo, sem
    levar dado do dono para site que ele não citou."""
    if objetivo is None or tool_id not in NAVEGACAO_DO_OBJETIVO:
        return False
    url = argumentos.get("url")
    if isinstance(url, str) and url:
        return objetivo.dentro(url) and not objetivo.leva_dado_do_dono(url)
    return True


def _situacao(
    manifesto: Mapping[str, Any], executor: ExecutorDeFerramentas, contaminado: bool
) -> dict[str, str]:
    return {
        "modo_de_acesso": str(executor.pdp.modo),
        "nivel_da_acao": str(manifesto.get("tier", "")),
        "classe_de_risco": str(manifesto.get("risk_class", "")),
        "efeito": str(manifesto.get("side_effect", "")),
        "turno_ja_leu_conteudo_de_terceiros": "sim" if contaminado else "não",
    }
