"""O pedido do dono que precisa de ferramenta, cumprido numa tarefa (ADR-0038; dono, 2026-10-21).

O dono ouvia o Jarvis ler a chamada da ferramenta em voz alta, esperava calado enquanto o laço
inteiro rodava dentro do turno e, em "abre um vídeo no YouTube", via o trabalho parar depois da
primeira tentativa. O desenho agora: o pedido vira **objetivo**, o cérebro diz uma frase curta e
o turno acaba; quem segue é uma **tarefa** do `GestorDeTarefas`, conduzida por este motor — o
**mesmo** motor da conversa, com o mesmo contexto (persona, método, memória, a fala do dono) —,
uma rodada por passo, até o objetivo estar cumprido e conferido, precisar do dono, falhar ou ser
cancelado. O fim é a resposta àquele pedido, e chega ao dono pela fila de avisos.

O que vale aqui, por cima do modelo:

- **pensar não é falar** (ADR-0031): o texto antes de uma proposta é narração, o depois é palpite,
  e o `Raciocinio` fica com a tarefa (com teto) — nada disso vira fala;
- **conferir antes de dizer** (critério do objetivo, C2): no navegador e na entrada virtual,
  efeito sem leitura depois não é "pronto"; o motor é cobrado uma vez e, se ainda assim não
  conferir, a resposta diz que não conferiu;
- **nunca fingir sucesso**: sem nenhum passo que tenha dado certo, a resposta é do **código**, com
  o motivo do último erro em frase de gente;
- **a resposta é fala, não protocolo**: passa pelo leitor do protocolo e perde a frase que cita
  uma ferramenta pelo id ou traz argumento em JSON.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final

from jarvis.imagem import Imagem
from jarvis.s2.consumo import Medicao, medir, precos_do_motor
from jarvis.s2.laco import QUEM_SUBAGENTE, mensagens_das_ferramentas, rodada_do_agente
from jarvis.s2.leitura_da_pagina import NOTA_DA_LEITURA, leitura_antes
from jarvis.s2.motor import (
    Contexto,
    Fim,
    Modo,
    MotivoDoFim,
    MotorDeConversa,
    PedidoDeTool,
    Raciocinio,
    Texto,
    aceita_imagem,
)
from jarvis.s2.protocolo import sem_protocolo
from jarvis.s2.recuperacao import Recuperacao, Tentativa, assinatura
from jarvis.s2.roteiro_do_navegador import (
    Contato,
    roteiro,
)
from jarvis.s2.verdade import FALTA_ENVIAR, NOTA_DE_SEGUIR, frase_do_que_falta
from jarvis.s2.verdade import conferir as conferir_relato
from jarvis.tarefas.gestor import FORA_DA_ALLOWLIST, ErroDeTarefa, FimDaTarefa, Passo, Tarefa
from jarvis.tarefas.limite import (
    DecisaoNoLimite,
    LimiteDaTarefa,
    MotivoDoLimite,
    NotificacaoDoLimite,
    ler_decisao,
)
from jarvis.voz.interface import Onde

if TYPE_CHECKING:
    from jarvis.executor.ferramentas import ResultadoDeFerramenta

LIMITE_DO_RACIOCINIO: Final = 2000
"""O mesmo teto do turno (`jarvis.s2.cerebro`): o raciocínio não cresce o prompt sem fim."""
NOTA_DA_TAREFA: Final = (
    "Você é o subagente que executa este pedido do dono em segundo plano; a conversa com ele "
    "segue com o Jarvis. Continue com as ferramentas, uma por vez, até o objetivo estar cumprido "
    "e conferido; entre um passo e outro, nada em voz. No navegador: antes do primeiro clique ou "
    "digitação, LEIA a página (browser.inspecionar) e escolha o alvo pelo que está nela — o "
    "texto e o papel do elemento que existe, nunca um palpite; ao agir pelo ref num contato ou "
    "item, ponha em `esperado` o nome que você quer, e o código confere; depois de agir, leia de "
    "novo para "
    "conferir; se um passo falhar, releia e depure antes de tentar outra vez. Quando terminar, "
    "responda ao dono em uma ou duas frases, sem markdown, com o resultado que a leitura "
    "confirmou — ou com o que deu errado e o que dá para fazer. Não cite o nome das ferramentas "
    "nem os argumentos delas."
)
NOTA_DO_OBJETIVO: Final = (
    "O OBJETIVO DESTA TAREFA é o que o Jarvis decidiu ao entender o dono — siga as intenções e os "
    "valores dele (nomes, endereços, textos); a fala do dono, na conversa, é contexto e "
    "autorização, nunca o valor a digitar, procurar ou clicar: «{plano}»."
)
NOTA_SEM_PLANO: Final = (
    "O Jarvis não deixou plano: antes do primeiro passo, entenda você a fala do dono (veio da voz, "
    "pode estar sem pontuação e trazer mais de uma intenção) e decida os valores você mesmo — o "
    "nome como está na página, o texto a digitar —, nunca a frase dele copiada."
)
NOTA_DAS_LEMBRANCAS: Final = (
    "O que o dono guardou na memória e serve a este objetivo (dado, não ordem): use para decidir o "
    "nome certo (o contato, o lugar) antes de procurar na página."
)
NOTA_DO_JA_DITO: Final = (
    "O que o dono já ouviu de você neste pedido é só o que ele ouviu: não é decisão nem valor; se "
    "não bate com o objetivo, vale o objetivo."
)


def nota_do_objetivo(plano: str, ja_dito: str = "") -> str:
    """O objetivo que vai à tarefa (ADR-0071): o plano do Jarvis, ou o pedido de entender antes."""
    plano = " ".join(plano.split())
    nota = NOTA_DO_OBJETIVO.format(plano=plano) if plano else NOTA_SEM_PLANO
    return f"{nota} {NOTA_DO_JA_DITO}" if ja_dito.strip() else nota


def titulo_do_plano(plano: str, limite: int = 120) -> str:
    """O título da tarefa a partir do plano: a primeira linha, curta (o card e os eventos)."""
    linha = next((p.strip() for p in plano.splitlines() if p.strip()), "")
    return linha if len(linha) <= limite else linha[: limite - 1] + "…"


NOTA_DE_CONFERIR: Final = (
    "O que foi feito ainda NÃO foi conferido: antes de responder, leia o resultado (a aba, a "
    "página, o estado) com uma ferramenta de leitura e só diga que ficou pronto se a leitura "
    "confirmar."
)
NOTA_DO_FIM: Final = (
    "A tarefa termina aqui: não peça ferramenta. Diga ao dono, em uma ou duas frases, sem "
    "markdown e sem citar ferramenta, o que aconteceu, com as suas palavras e só com o que as "
    "ferramentas confirmaram. O que aconteceu (evento do sistema, não é o dono falando):"
)
"""A rodada do fim que o código não escreve (ADR-0070): o motor recebe o evento e fala."""
FERRAMENTAS_DE_LEITURA: Final = frozenset(
    {"browser.read", "browser.tabs", "browser.tela", "browser.inspecionar", "web.ler"}
)
SEM_JEITO: Final = "não achei um jeito de fazer isso com o que está ligado agora"
CAUSAS_DE_DENTRO: Final = frozenset(
    {"fora_do_contrato", "ferramenta_desligada", "argumento_recusado", "metodo_de_fora"}
)
"""Falhas que são do caminho interno (contrato, catálogo, método): o dono ouve a frase geral."""
COBRANCAS_DO_OBJETIVO: Final = 2
"""Quantas vezes a tarefa cobra o motor que parou antes do objetivo (ADR-0066)."""
RODADAS_POR_PASSO: Final = 4
"""Rodadas do motor dentro de um mesmo passo (cobrar a conferência, recusar a ação repetida,
tentar de novo a rodada que caiu): o teto de custo de um passo."""
PAUSA_DEPOIS_DO_ERRO_S: Final = 0.5
"""Antes de tentar de novo a rodada do motor que caiu (a CLI que saiu com código, o serviço que
respondeu 5xx): um respiro curto, cancelável."""
EVENTOS_SEM_SAIDA: Final[Mapping[str, str]] = {
    "extensao_desatualizada": (
        "a extensão do Jarvis no navegador é de uma versão anterior à do Jarvis; o dono precisa "
        "abrir a página de extensões e clicar em Recarregar no card do Jarvis antes de tentar de "
        "novo"
    ),
    "parado_pelo_dono": "o dono mandou parar",
}
"""As falhas sem outro caminho agora (`recuperacao.SEM_SAIDA`), como **dado** para o motor dizer
com as palavras dele (ADR-0070)."""
_FRASE: Final = r"(?<=[.!?…])\s+"
_CODIGO_ENTRE_PARENTESES: Final = r"\s*\([a-z][a-z_]{2,40}\)"


@dataclass(slots=True)
class MotorDoObjetivo:
    """O `MotorDeTarefa` da tarefa de um pedido: propõe, nunca executa (P1)."""

    motor: MotorDeConversa
    contexto: Contexto
    """O do turno em que o pedido chegou: sistema (persona, método, memória) e a conversa até a
    fala do dono. As ferramentas vêm do `catalogo`, as de agora."""
    catalogo: Callable[[], Sequence[Mapping[str, Any]]]
    primeiro: PedidoDeTool | None
    """A proposta que o motor já fez no turno: é o primeiro passo, sem pedir de novo. `None` = o
    turno já fez o primeiro passo (o objetivo que precisa conferir, ADR-0046): a tarefa pergunta ao
    motor o próximo, com os resultados do turno na mão."""
    feitos_antes: tuple[ResultadoDeFerramenta, ...] = ()
    """O que o turno já tinha rodado antes de delegar (só o que não vai em tarefa)."""
    raciocinio: str = ""
    ja_dito: str = ""
    lembrancas: str = ""
    """O que o dono guardou por voz e serve a este objetivo (o livro, buscado pelo plano; ADR-0071):
    dado, nunca ordem — é por aqui que «salva que o contato da minha mãe é Mãe» chega à tarefa."""
    plano: str = ""
    """O objetivo FORMULADO pelo Jarvis no turno (o plano antes da 1ª ferramenta, ADR-0071): as
    intenções do dono e os valores escolhidos. É o que a tarefa persegue; a fala do dono segue na
    conversa como contexto e autorização, não como o objetivo."""
    """O que o dono já ouviu deste pedido (a frase curta): o motor não a repete."""
    ids: frozenset[str] = frozenset()
    """Os ids de todas as ferramentas do catálogo (as fora deste modo também): frase que cita um
    deles é etapa interna e não vai para a voz."""
    limite_do_raciocinio: int = LIMITE_DO_RACIOCINIO
    nome: str = "objetivo"
    raciocinio_descartado: int = 0
    cobrou_conferencia: bool = False
    cobrancas_do_objetivo: int = 0
    """Quantas vezes o motor que parou antes do objetivo (relato sem confirmação, «quer que eu
    mande?») foi cobrado a seguir (ADR-0066)."""
    _cobrar_objetivo: bool = False
    recuperacao: Recuperacao = field(default_factory=Recuperacao)
    """As falhas desta tarefa e o orçamento de tentativas (recuperação de falha, emenda de
    2026-10-30 à ADR-0038)."""
    na_tela: Callable[[str], None] | None = None
    """O canal de raciocínio na tela (ADR-0031): a linha de cada replanejamento — nunca a voz."""
    pausa_depois_do_erro_s: float = PAUSA_DEPOIS_DO_ERRO_S
    ao_medir: Callable[[Medicao], None] | None = None
    """Recebe o consumo (tokens, custo, 1º token) de cada chamada ao motor (ADR-0061)."""
    _propostos: list[str] = field(default_factory=list)
    """A assinatura (ferramenta + argumentos) de cada passo proposto, na ordem dos `feitos`."""
    contatos: tuple[Contato, ...] = ()
    """Os contatos das memórias fixas (nome e nota, nunca telefone): o roteiro do envio resolve
    «minha mãe» por eles (ADR-0066)."""
    leituras_forcadas: int = 0
    """Quantas vezes o código leu a página no lugar de uma ação proposta sem leitura (ADR-0069)."""
    _nota_da_leitura: bool = False

    @property
    def na_nuvem(self) -> bool:
        return self.motor.onde is Onde.NUVEM

    def proximo(
        self, tarefa: Tarefa, feitos: Sequence[ResultadoDeFerramenta], cancelado: Callable[[], bool]
    ) -> Passo:
        if not feitos and self.primeiro is not None:
            no_catalogo = [str(f["id"]) for f in self.catalogo()]
            return self._com_leitura(self.primeiro, feitos, no_catalogo)
        if feitos and feitos[-1].causa == "dono_nao_confirmou":
            # O dono disse não (ou cortou a pergunta, ou ela venceu): a tarefa acaba aqui. Chamar o
            # motor de novo era a mesma ação proposta outra vez — a pergunta em laço da trilha do
            # dono (2026-10-24: três perguntas seguidas para o mesmo apps.quit).
            return _recusado(feitos[-1])
        recuperacao = self.recuperacao
        recuperacao.observar(feitos, self._propostos)
        sem_saida = recuperacao.sem_saida()
        if sem_saida is not None:
            evento = EVENTOS_SEM_SAIDA.get(sem_saida.codigo, sem_saida.em_frase())
            return self._explicar(
                tarefa, feitos, f"não há outro caminho agora: {evento}.", cancelado, falhou=True
            )
        if recuperacao.esgotou():
            return self._no_limite_de_falhas()
        if recuperacao.ultima() is not None:
            self._mostrar(recuperacao.linha_na_tela())
        # O aviso da guarda de laço (ADR-0062) vai junto da nota de replanejar, uma vez.
        nota_de_laco, tarefa.nota_de_laco = tarefa.nota_de_laco, ""
        if nota_de_laco:
            self._mostrar("repetindo passos sem avançar: avisei o motor para mudar de caminho")
        objetivo = tarefa.contaminacao.objetivo
        catalogo = tuple(
            f for f in self.catalogo() if not str(f["id"]).startswith(FORA_DA_ALLOWLIST)
        )
        disponiveis = [str(f["id"]) for f in catalogo]
        for _rodada in range(RODADAS_POR_PASSO):
            cobrar = self.cobrou_conferencia
            try:
                pedido, texto = self._rodada(
                    tarefa,
                    feitos,
                    catalogo,
                    cancelado,
                    conferir=cobrar,
                    recuperar=" ".join(
                        n for n in (recuperacao.nota(disponiveis), nota_de_laco) if n
                    ),
                )
            except MotorFalhou as erro:
                recuperacao.motor_falhou += 1
                if recuperacao.motor_falhou > recuperacao.erros_do_motor or cancelado():
                    return self._sem_motor(tarefa, feitos, erro)
                self._mostrar(f"o motor não respondeu a esta rodada ({erro.detalhe[:80]}); de novo")
                _esperar(self.pausa_depois_do_erro_s * recuperacao.motor_falhou, cancelado)
                continue
            if pedido is not None:
                if self._falta_ler(pedido, feitos, disponiveis):
                    # Reler vem antes de julgar a repetição (ADR-0069 §2): depois do passo que
                    # falhou na página, a próxima ação é a releitura — com o mapa novo na mão, o
                    # motor decide de novo. Recusar a ação como «repetida» antes disso era desistir
                    # sem ter olhado a página outra vez.
                    return self._com_leitura(pedido, feitos, disponiveis)
                repetida = recuperacao.repetida(pedido)
                if repetida is None:
                    return self._com_leitura(pedido, feitos, disponiveis)
                # A mesma ação que já falhou: não roda de novo — volta ao motor como recusa.
                recuperacao.registrar_falha(
                    Tentativa(
                        pedido.tool_id,
                        assinatura(pedido.tool_id, pedido.args),
                        "repetida",
                        f"igual à que já falhou ({repetida.codigo})",
                    )
                )
                if recuperacao.esgotou():
                    return self._no_limite_de_falhas()
                self._mostrar(recuperacao.linha_na_tela())
                continue
            ids = self.ids | set(disponiveis)
            relato = conferir_relato(texto, (*self.feitos_antes, *feitos))
            if relato.cortadas and self.cobrancas_do_objetivo < COBRANCAS_DO_OBJETIVO:
                # Parou antes do objetivo (ADR-0038/0066): afirmou o que nada confirmou ou pediu
                # permissão para o que o dono já pediu. O motor é cobrado e segue.
                self.cobrancas_do_objetivo += 1
                self._cobrar_objetivo = True
                self._mostrar("a resposta afirmava sem confirmar: cobrei o objetivo")
                continue
            pode_ler = any(i in FERRAMENTAS_DE_LEITURA for i in disponiveis)
            if objetivo is not None and objetivo.falta_conferir and pode_ler and not cobrar:
                self.cobrou_conferencia = True  # uma vez: o motor lê, ou a resposta diz que não
                continue
            return self._fim(tarefa, feitos, texto, ids, cancelado)
        # As rodadas deste passo acabaram sem um passo válido: o motor recebe o estado e decide.
        return LimiteDaTarefa(
            MotivoDoLimite.RODADAS,
            f"{RODADAS_POR_PASSO} rodadas sem uma proposta que pudesse rodar",
        )

    def decidir_no_limite(
        self,
        tarefa: Tarefa,
        aviso: NotificacaoDoLimite,
        feitos: Sequence[ResultadoDeFerramenta],
        cancelado: Callable[[], bool],
    ) -> DecisaoNoLimite | None:
        """No limite (ADR-0070): uma rodada sem ferramentas em que o motor pensa com o estado real e
        decide continuar, perguntar ao dono ou encerrar. `None` = o motor caiu."""
        try:
            pedido, texto = self._rodada(
                tarefa, feitos, (), cancelado, conferir=False, recuperar=aviso.para_o_motor()
            )
        except MotorFalhou:
            return None
        if pedido is not None and "continuar" in aviso.opcoes:
            # Pediu ferramenta em vez de responder: é querer seguir, por um bloco.
            return DecisaoNoLimite("continuar", aviso.bloco)
        decisao = ler_decisao(texto if pedido is None else "", aviso.opcoes, aviso.bloco)
        todos = (*self.feitos_antes, *feitos)
        ids = self.ids | {r.tool_id for r in todos}
        fala = sem_etapas_internas(decisao.texto, ids)
        if decisao.acao == "encerrar":
            fala = conferir_relato(fala, todos).texto
        self._mostrar(f"no limite ({aviso.motivo}), decidi: {decisao.acao}")
        return replace(decisao, texto=fala)

    def retomar(self, motivo: MotivoDoLimite) -> None:
        """A tarefa segue depois do limite: o orçamento de falhas ganha outra rodada inteira."""
        if motivo is MotivoDoLimite.FALHAS:
            self.recuperacao.estender()

    def _no_limite_de_falhas(self) -> LimiteDaTarefa:
        """O orçamento de falhas acabou: não é o fim, é uma notificação (ADR-0070)."""
        detalhe = explicacao_do_que_tentou(self.recuperacao)
        self._mostrar(f"{self.recuperacao.total} falha(s): o orçamento acabou; decido o que fazer")
        return LimiteDaTarefa(MotivoDoLimite.FALHAS, detalhe)

    def _explicar(
        self,
        tarefa: Tarefa,
        feitos: Sequence[ResultadoDeFerramenta],
        evento: str,
        cancelado: Callable[[], bool],
        *,
        falhou: bool,
    ) -> FimDaTarefa:
        """O fim que o código não escreve (ADR-0070): o motor recebe o que aconteceu como evento,
        numa rodada sem ferramentas, e diz ao dono com as palavras dele. O relato verdadeiro corta o
        que nada confirmou. Sem texto (o motor caiu), a resposta fica vazia e o fim vai ao Jarvis
        do turno como evento, com o estado."""
        todos = (*self.feitos_antes, *feitos)
        ids = self.ids | {r.tool_id for r in todos}
        try:
            pedido, texto = self._rodada(
                tarefa, feitos, (), cancelado, conferir=False, recuperar=f"{NOTA_DO_FIM} {evento}"
            )
        except MotorFalhou:
            pedido, texto = None, ""
        fala = "" if pedido is not None else sem_etapas_internas(texto, ids)
        fala = conferir_relato(fala, todos).texto
        return FimDaTarefa(fala or evento, resposta=fala, falhou=falhou)

    def _com_leitura(
        self,
        pedido: PedidoDeTool,
        feitos: Sequence[ResultadoDeFerramenta],
        disponiveis: Sequence[str],
    ) -> PedidoDeTool:
        """A ação na página só depois de lê-la (ADR-0069 §2): sem leitura que valha — a página
        mudou, ou o último passo nela falhou —, o passo é a inspeção, e o motor decide de novo com
        o mapa na mão."""
        passos = ((r.tool_id, r.status) for r in (*self.feitos_antes, *feitos))
        leitura = leitura_antes(pedido, passos, disponiveis, forcadas=self.leituras_forcadas)
        if leitura is None:
            return self._propor(pedido)
        self.leituras_forcadas += 1
        self._nota_da_leitura = True
        self._mostrar("li a página antes de agir nela")
        return self._propor(leitura)

    def _falta_ler(
        self,
        pedido: PedidoDeTool,
        feitos: Sequence[ResultadoDeFerramenta],
        disponiveis: Sequence[str],
    ) -> bool:
        passos = ((r.tool_id, r.status) for r in (*self.feitos_antes, *feitos))
        return (
            leitura_antes(pedido, passos, disponiveis, forcadas=self.leituras_forcadas) is not None
        )

    def _propor(self, pedido: PedidoDeTool) -> PedidoDeTool:
        self._propostos.append(assinatura(pedido.tool_id, pedido.args))
        return pedido

    def _mostrar(self, linha: str) -> None:
        if linha and self.na_tela is not None:
            self.na_tela(linha)

    def _sem_motor(
        self, tarefa: Tarefa, feitos: Sequence[ResultadoDeFerramenta], erro: MotorFalhou
    ) -> FimDaTarefa:
        """O motor caiu de novo depois das tentativas: ninguém aqui escreve a fala. O fim vai ao
        Jarvis do turno como evento, com o estado (conferido ou não) e o motivo do motor."""
        objetivo = tarefa.contaminacao.objetivo
        conferido = objetivo is not None and objetivo.efeito_feito and not objetivo.falta_conferir
        if conferido and any(r.status == "ok" for r in feitos):
            titulo = _titulo_lido(feitos)
            resumo = "o objetivo foi feito e conferido" + (
                f"; a página lida: {titulo}" if titulo else ""
            )
            return FimDaTarefa(f"{resumo}; o motor da tarefa caiu antes de responder")
        raise ErroDeTarefa(
            "o motor da conversa falhou "
            f"{self.recuperacao.motor_falhou} vez(es) seguidas no próximo passo: {erro.detalhe}"
        )

    def _rodada(
        self,
        tarefa: Tarefa,
        feitos: Sequence[ResultadoDeFerramenta],
        catalogo: tuple[Mapping[str, Any], ...],
        cancelado: Callable[[], bool],
        *,
        conferir: bool,
        recuperar: str = "",
    ) -> tuple[PedidoDeTool | None, str]:
        todos = (*self.feitos_antes, *feitos)
        textos, _podados = mensagens_das_ferramentas(todos)
        notas = [NOTA_DA_TAREFA, nota_do_objetivo(self.plano, self.ja_dito)]
        if self.lembrancas:
            notas.append(f"{NOTA_DAS_LEMBRANCAS}\n{self.lembrancas}\n")
        objetivo = tarefa.contaminacao.objetivo
        if objetivo is not None:
            # Lote C, C2: o critério de pronto, a fase e o que já foi feito (só ferramenta e
            # status) — na nuvem sem o texto do pedido de novo (D20: ele já está na conversa).
            dados = objetivo.para_o_classificador(na_nuvem=self.na_nuvem)
            notas.append(
                f"Critério de pronto: {dados['criterio_de_pronto']}. Fase: {dados['fase']}. "
                f"Passos feitos: {', '.join(dados['passos_feitos']) or 'nenhum'}."
            )
            # Os passos concretos montados pelo código (dono, 2026-11-14): o que abrir, ler,
            # digitar e conferir — não só o objetivo. Só com ferramenta de navegador no catálogo.
            passos = roteiro(
                objetivo.pedido, (str(m.get("id", "")) for m in catalogo), self.contatos
            )
            if passos:
                notas.append(passos)
        if conferir:
            notas.append(NOTA_DE_CONFERIR)
        if self._nota_da_leitura:
            notas.append(NOTA_DA_LEITURA)
            self._nota_da_leitura = False
        if self._cobrar_objetivo:
            notas.append(NOTA_DE_SEGUIR)
            self._cobrar_objetivo = False
        if recuperar:
            notas.append(recuperar)
        contexto = Contexto(
            sistema=f"{self.contexto.sistema}\n\n" + " ".join(notas),
            mensagens=(*self.contexto.mensagens, *textos),
            ferramentas=catalogo,
            raciocinio=self.raciocinio,
            ja_dito=self.ja_dito,
            imagens=_imagens(todos) if aceita_imagem(self.motor) else (),
        )
        # O laço canônico (ADR-0072): a MESMA rodada do Jarvis (`jarvis.s2.laco`); o que vem
        # antes da proposta é narração e o depois, palpite: os dois vão ao raciocínio.
        pedido: PedidoDeTool | None = None
        texto: list[str] = []
        ao_medir = self.ao_medir
        deltas = rodada_do_agente(
            self.motor,
            contexto,
            Modo.RAPIDO,
            cancelado,
            quem=QUEM_SUBAGENTE,
            # O consumo de cada passo da tarefa vai à trilha (ADR-0061): só números.
            envolver=(
                (
                    lambda crus: medir(
                        crus,
                        caracteres_entrada=lambda: len(contexto.como_texto()),
                        precos=lambda: precos_do_motor(self.motor),
                        ao_medir=ao_medir,
                    )
                )
                if ao_medir is not None
                else None
            ),
        )
        try:
            for parte in deltas:
                if isinstance(parte, Fim):
                    if parte.motivo in (MotivoDoFim.ERRO, MotivoDoFim.PRAZO):
                        raise MotorFalhou(parte.detalhe or str(parte.motivo))
                    break
                if isinstance(parte, PedidoDeTool):
                    if pedido is None:
                        pedido = parte
                        self._pensou(" ".join(texto))
                        texto = []
                elif isinstance(parte, Raciocinio):
                    self._pensou(parte.texto)
                elif isinstance(parte, Texto):
                    if pedido is None:
                        texto.append(parte.texto)
                    else:
                        self._pensou(parte.texto)
        finally:
            deltas.close()  # o `finally` do motor para a geração
        return pedido, "".join(texto)

    def _pensou(self, trecho: str) -> None:
        trecho = trecho.strip()
        if not trecho:
            return
        guardado = trecho[: max(0, self.limite_do_raciocinio - len(self.raciocinio) - 1)]
        if guardado:
            self.raciocinio = f"{self.raciocinio}\n{guardado}" if self.raciocinio else guardado
        self.raciocinio_descartado += len(trecho) - len(guardado)

    def _fim(
        self,
        tarefa: Tarefa,
        feitos: Sequence[ResultadoDeFerramenta],
        texto: str,
        ids: frozenset[str],
        cancelado: Callable[[], bool],
    ) -> FimDaTarefa:
        """O motor respondeu sem ferramenta. Quando a resposta dele não pode ir como está (nada deu
        certo, afirmou sem confirmar, veio vazia, faltou conferir), o código não a troca por uma
        frase dele: o motor recebe o fato como evento e escreve de novo (ADR-0070)."""
        todos = (*self.feitos_antes, *feitos)
        objetivo = tarefa.contaminacao.objetivo
        nada_feito = (
            objetivo is not None and objetivo.efeitos_tentados and not objetivo.efeito_feito
        )
        if nada_feito or not any(r.status == "ok" for r in todos):
            ultimo = next((r for r in reversed(todos) if r.status != "ok"), todos[-1])
            if ultimo.causa == "dono_nao_confirmou" or ultimo.motivo == "o dono disse não":
                return FimDaTarefa(ultimo.motivo, resposta="", falhou=True, aviso="")
            tentou = explicacao_do_que_tentou(self.recuperacao) or motivo_para_ouvir(ultimo, ids)
            evento = (
                "nenhum passo que muda algo deu certo, então o pedido NÃO foi cumprido; "
                f"o que foi tentado e o erro real: {tentou}."
            )
            return self._explicar(tarefa, feitos, evento, cancelado, falhou=True)
        relato = conferir_relato(sem_etapas_internas(texto, ids), todos)
        if relato.cortadas:
            falta = frase_do_que_falta(relato)
            evento = (
                "estas afirmações suas não foram confirmadas por nenhuma ferramenta e não podem "
                f"ser ditas: «{' '.join(relato.cortadas)}». O que está confirmado: "
                f"«{relato.texto or 'nada'}». Situação: {falta}"
            )
            return self._explicar(tarefa, feitos, evento, cancelado, falhou=falta == FALTA_ENVIAR)
        if not relato.texto:
            evento = "a sua resposta final veio vazia; diga ao dono o resultado do pedido."
            return self._explicar(tarefa, feitos, evento, cancelado, falhou=False)
        if objetivo is not None and objetivo.falta_conferir:
            evento = (
                f"você ia dizer «{relato.texto}», mas o resultado não foi conferido por uma "
                "leitura: diga o que foi feito e que não deu para conferir."
            )
            return self._explicar(tarefa, feitos, evento, cancelado, falhou=False)
        return FimDaTarefa(relato.texto, resposta=relato.texto)


class MotorFalhou(ErroDeTarefa):
    """A rodada do motor acabou em erro ou prazo: a tarefa tenta de novo antes de desistir."""

    def __init__(self, detalhe: str) -> None:
        super().__init__(f"o motor da conversa não respondeu ao próximo passo: {detalhe}")
        self.detalhe = detalhe


def explicacao_do_que_tentou(recuperacao: Recuperacao) -> str:
    """O que foi tentado e o erro real de cada caminho, como dado para o motor (ADR-0070): no
    máximo cinco, sem a ação recusada por repetida. Vazio = nada falhou."""
    partes: list[str] = []
    for tentativa in recuperacao.historico:
        if tentativa.codigo == "repetida":
            continue
        motivo = " ".join(sem_protocolo(tentativa.motivo).split())[:160]
        parte = f"{tentativa.tool_id} [{tentativa.codigo}]" + (f": {motivo}" if motivo else "")
        if parte not in partes:
            partes.append(parte)
    return "; ".join(partes[-5:])


def _titulo_lido(feitos: Sequence[ResultadoDeFerramenta]) -> str:
    """O título da página da última leitura que deu certo (para a frase do código)."""
    for resultado in reversed(feitos):
        if resultado.status == "ok":
            titulo = resultado.dados.get("titulo") or resultado.dados.get("title")
            if isinstance(titulo, str) and titulo.strip():
                return f"«{titulo.strip()[:80]}»"
    return ""


def _esperar(segundos: float, cancelado: Callable[[], bool]) -> None:
    limite = time.monotonic() + max(0.0, segundos)
    while time.monotonic() < limite and not cancelado():
        time.sleep(min(0.05, max(0.0, limite - time.monotonic())))


def _recusado(resultado: ResultadoDeFerramenta) -> FimDaTarefa:
    """O fim da tarefa cuja pergunta o dono não confirmou. Ele disse não, clicou não ou cortou a
    pergunta com outro assunto: já ouviu (ou disse) o que importa, e o fim é calado — só o card
    muda. O prazo que venceu sem resposta é o único "não" que ele não viu acontecer: esse vai ao
    Jarvis como evento (ADR-0070), e ele decide como dizer."""
    origem = str(resultado.dados.get("resposta_do_dono", "prazo"))
    if origem == "prazo":
        resumo = (
            f"a pergunta ao dono venceu sem resposta, então nada foi feito ({resultado.motivo})"
        )
        return FimDaTarefa(resumo, resposta="", falhou=True)
    return FimDaTarefa(resultado.motivo, resposta="", falhou=True, aviso="")


def _imagens(feitos: Sequence[ResultadoDeFerramenta]) -> tuple[Imagem, ...]:
    """A tela mais nova que um passo capturou (ADR-0032): só ela vai ao motor."""
    for resultado in reversed(feitos):
        if resultado.anexos:
            return resultado.anexos
    return ()


def motivo_para_ouvir(resultado: ResultadoDeFerramenta, ids: frozenset[str]) -> str:
    """O motivo de uma falha em frase de gente: sem o código entre parênteses, sem o id de
    ferramenta, sem JSON. Falha do caminho interno vira a frase geral."""
    if resultado.causa in CAUSAS_DE_DENTRO or resultado.tool_id == "(malformado)":
        return SEM_JEITO
    limpo = re.sub(_CODIGO_ENTRE_PARENTESES, "", sem_protocolo(resultado.motivo))
    limpo = limpo.strip().rstrip(".!?…").strip()
    if not limpo or _cita_ferramenta(limpo, ids) or "{" in limpo:
        return SEM_JEITO
    return limpo


def sem_etapas_internas(texto: str, ids: frozenset[str]) -> str:
    """O texto do motor como fala: sem protocolo, e sem a frase que cita uma ferramenta pelo id
    ou traz argumento em JSON (é etapa interna, não resultado)."""
    frases = re.split(_FRASE, sem_protocolo(texto))
    return " ".join(
        f for f in frases if f.strip() and not _cita_ferramenta(f, ids) and "{" not in f
    ).strip()


def _cita_ferramenta(texto: str, ids: frozenset[str]) -> bool:
    return any(re.search(rf"(?<![\w.]){re.escape(i)}(?![\w])", texto) for i in ids)
