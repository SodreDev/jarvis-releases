"""O cérebro: uma conversa contínua, dona do contexto, que responde em stream (ADR-0025).

Decisão do dono (2026-10-16): **um** cérebro com conversa contínua, interrompível, que começa a
falar enquanto gera e, interrompido, para de falar **e de gerar**. Este módulo é a parte do
`s2` que faz isso, sem processo e sem barramento — quem publica é o chamador, por `publicar` —,
para o contrato ser testado inteiro em memória:

- **A conversa é nossa** (regra 2). O motor recebe o contexto montado aqui a cada pedido.
- **Só o tocado volta** (regra 3). A resposta só entra na conversa por `ouvido`, com o texto que
  o dono ouviu; resposta de que ninguém confirmou o tocado **não existe** para o modelo (§3.3,
  regra 4) — inclusive a que foi gerada inteira.
- **Pedaço por fronteira** (regra 7). O texto do motor passa pelo `FatiadorDeFala` (a mesma regra
  do TTS) e sai um `ResponseChunk` por pedaço.
- **Cancelamento** (regra 9). Visto o cancelamento, nada mais daquele epoch é publicado, e o
  iterador do motor é fechado — é o `finally` dele que mata processo ou conexão. O tempo entre
  ver o cancelamento e o motor parado é medido e fica na `Resposta`.
- **O que as ferramentas trazem é do turno** (ADR-0034). Cada rodada leva os resultados dentro de
  um orçamento (os antigos podados), e nada deles vai para a conversa nem para o livro.
- **Pensar não é falar** (ADR-0031, dono 2026-10-20). O `Raciocinio` do motor fica com o turno,
  com teto, e volta só para o motor na rodada seguinte; a fala é o resultado, uma pergunta
  necessária e no máximo um aviso curto antes da primeira ferramenta.
- **Falar menos** (emenda de 2026-10-21 à ADR-0031). O texto do motor vai inteiro para a tela, e
  para a voz inteira até o teto de segurança (`jarvis.s2.orcamento_da_fala`: 120 palavras, ~45 s),
  que corta numa frase inteira e pergunta «Quer que eu monte o resto na tela?» — a não ser que o
  dono tenha pedido detalhe. Quem faz a resposta curta é a persona, não o teto (2026-10-29).
- **Uma resposta por pedido** (dono, 2026-10-25, ADR-0046). O pedido de um passo responde no
  turno: a primeira ferramenta roda aqui, e só o trabalho longo (mais passos, mais tempo) vai para
  uma tarefa. Depois de uma ferramenta, a frase que repete o que o dono já ouviu fica só na tela
  (`jarvis.s2.entrega`).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from jarvis.barramento.contrato import prioridade_canonica, validar
from jarvis.barramento.envelope import Envelope, Tipo, Trust, uuid7
from jarvis.executor.desfazer import Contaminacao
from jarvis.executor.ferramentas import (
    Confirmacao,
    Confirmar,
    ExecutorDeFerramentas,
    ResultadoDeFerramenta,
    negar_sempre,
)
from jarvis.fatiador import PALAVRAS_MINIMAS_POR_PEDACO, Corte, FatiadorDeFala, PedacoDeFala
from jarvis.imagem import Imagem
from jarvis.memoryd.livro import LivroDeMemoria
from jarvis.navegador.cliente import SEM_NAVEGADOR_ABERTO
from jarvis.politica.atalho import Atalho, fala_simples, frase_da_ferramenta
from jarvis.politica.atalho import frase as frase_do_atalho
from jarvis.politica.memoria import AlcanceDeMemoria, Proveniencia, TurnoCorrente
from jarvis.politica.objetivo import EstadoDoObjetivo
from jarvis.s2.avisos import AvisoLiberado, frase_do_aviso
from jarvis.s2.entrega import FiltroDoJaDito, traz_algo_novo
from jarvis.s2.fluxo_de_acao import FluxoDeAcao, frase_do_feito
from jarvis.s2.memoria_do_turno import MemoriaDoTurno, consultar
from jarvis.s2.motor import (
    Contexto,
    Delta,
    Fim,
    Mensagem,
    Modo,
    MotivoDoFim,
    MotorDeConversa,
    PedidoDeTool,
    Pensar,
    Raciocinio,
    Texto,
    aceita_imagem,
)
from jarvis.s2.orcamento_da_fala import OrcamentoDaFala, quer_detalhe
from jarvis.s2.pendencias import Espera, RegistroDePendencias
from jarvis.s2.persona import sistema_do_jarvis
from jarvis.s2.portao import AutorizacoesExplicitas, PortaoDeAcao
from jarvis.s2.protocolo import LeitorDoProtocolo
from jarvis.s2.rascunho import textos_no_contexto
from jarvis.s2.tarefa_do_pedido import MotorDoObjetivo
from jarvis.tarefas.gestor import FORA_DA_ALLOWLIST, ChamarNaTarefa, Tarefa, TarefaRecusada
from jarvis.tela.guia import nota_da_tela
from jarvis.voz.interface import Cancelado, nunca_cancelado

MAXIMO_DE_PASSOS: Final = 12
"""Chamadas de ferramenta que um turno pode encadear antes de ter de responder."""
PRAZO_DO_LACO_DE_FERRAMENTAS_S: Final = 90.0
"""Orçamento total do laço agêntico; inclui pensar e executar as ferramentas."""
# Nome preservado para quem importava o teto antigo. Agora cada rodada tem exatamente um passo:
# o resultado volta ao motor antes de ele poder propor o próximo.
MAXIMO_DE_RODADAS: Final = MAXIMO_DE_PASSOS
TURNOS_NO_CONTEXTO: Final = 12
"""Orçamento fixo de conversa no contexto (regra 5): os últimos turnos estáveis. O resumo do que
ficou para trás é trabalho de segundo plano, fora desta fatia."""
LIMITE_DO_RACIOCINIO: Final = 2000
"""Caracteres de raciocínio que um turno guarda e devolve ao motor (ADR-0031). O resto é contado
e descartado: o canal interno não pode crescer o prompt de cada rodada sem fim."""
LIMITE_DO_JA_DITO: Final = 300
"""Caracteres do que o dono já ouviu no turno que voltam ao motor (o fim, que é o mais novo)."""
FRASE_AO_DELEGAR: Final = "Certo, já cuido disso."
"""O que o dono ouve quando o pedido vira tarefa e o motor não disse nada antes da ferramenta
(ADR-0038): curto, e a resposta de verdade vem quando a tarefa acabar."""
NOTA_DO_ATALHO: Final = (
    "O primeiro passo deste pedido o código já fez, pelo caminho rápido: o resultado está entre os "
    "das ferramentas. Siga daí, sem repetir esse passo."
)
PASSOS_NO_TURNO: Final = 2
"""Ferramentas que o próprio turno roda antes de passar o resto do pedido a uma tarefa (dono,
2026-10-25: pedido simples ou de um passo responde no turno; tarefa só para trabalho longo). No
objetivo que precisa conferir (navegador, entrada virtual: agir e depois ler), é uma."""
ESPERA_DA_EXTENSAO_S: Final = 12.0
"""Quanto se espera a extensão conectar depois de o Jarvis abrir o navegador (o Brave frio leva
alguns segundos para carregar a extensão)."""
INTERVALO_DA_EXTENSAO_S: Final = 0.25
SEGUNDOS_NO_TURNO: Final = 12.0
"""Laço que já passou disto é trabalho longo: a próxima ferramenta vai para a tarefa."""
ACOES_DE_UM_PASSO: Final = frozenset(
    {
        "apps.launch",
        "apps.quit",
        "browser.launch",
        "clipboard.text.write",
        "jarvis.encerrar",
        "media.player.control",
        "notify.desktop.send",
        "system.brightness.set",
        "system.volume.set",
        "tela.fechar",
        "tela.mostrar",
        "timer.alarm.cancel",
        "timer.alarm.set",
        "vocabulario.aprender",
        "window.close",
        "window.focus_app",
    }
)
"""Ações que cumprem sozinhas um pedido simples: deu certo e o dono já ouviu o que mudou (o aviso,
a frase do código ou a do motor antes dela), o turno acaba — sem outra rodada do motor para dizer
"pronto" de novo."""

Publicar = Callable[[dict[str, Any]], None]
"""Recebe o payload de um `ResponseChunk`. No processo, vira envelope (`envelope_do_pedaco`)."""
Mostrar = Callable[[str], None]
"""Recebe o texto da resposta como está agora, a cada delta: é o que a tela mostra. A fala vai em
lotes de 14..18 palavras (`FatiadorDeFala`); a tela não espera o lote — segue a geração."""
AvisarStatus = Callable[[str], None]
"""Enfileira um status curto; a fronteira de voz decide quando (e se) ele será falado."""


@dataclass(slots=True)
class Conversa:
    """Os turnos estáveis da sessão. Do Jarvis, só o que tocou."""

    sistema: str = field(default_factory=sistema_do_jarvis)
    """A persona (`persona.md`) e as regras do dono (ADR-0047), no lugar do prompt curto do
    provisório. O aplicativo põe as do arquivo do dono, quando ele tem."""
    turnos: list[Mensagem] = field(default_factory=list)
    maximo: int = TURNOS_NO_CONTEXTO

    def contexto(self) -> Contexto:
        return Contexto(sistema=self.sistema, mensagens=tuple(self.turnos[-self.maximo :]))


@dataclass(slots=True)
class Resposta:
    """O que aconteceu num turno, para a auditoria e para o harness."""

    response_id: str
    turn_id: str
    epoch: int
    motor: str
    gerado: str = ""
    """O texto que foi à tela e à fala — **não** é o que o dono ouviu, e não volta ao contexto.
    Sem o raciocínio: esse fica em `raciocinio`."""
    raciocinio: str = ""
    """O raciocínio do turno (`Raciocinio` do motor, a narração retida), até
    `LIMITE_DO_RACIOCINIO`. Nunca vai à fala nem à tela, nem ao histórico, nem à trilha (só o
    tamanho): morre com o turno."""
    raciocinio_descartado: int = 0
    """Caracteres de raciocínio que passaram do teto e não voltaram ao motor."""
    estado_do_objetivo: str = ""
    """Como o objetivo do pedido terminou o turno (`EstadoDoObjetivo`), para a trilha."""
    resultados_podados: int = 0
    """Passos antigos que foram ao motor podados numa rodada (o máximo do turno, ADR-0034): o volume
    do que eles trouxeram ficou fora do contexto."""
    narracao_retida: int = 0
    """Trechos de narração de passo que não foram ditos (ADR-0031): o "achei, vou abrir" antes de
    uma ferramenta, depois da primeira, e o que o modelo disse depois de propor uma."""
    publicados: list[dict[str, Any]] = field(default_factory=list)
    fim: MotivoDoFim = MotivoDoFim.CONCLUIDO
    detalhe: str = ""
    pediu_pensar: bool = False
    deltas_depois_do_cancelamento: int = 0
    ferramentas: list[ResultadoDeFerramenta] = field(default_factory=list)
    """Cada chamada do turno, com o que aconteceu — para a auditoria e para o teste."""
    memoria: MemoriaDoTurno | None = None
    """O que o livro lembrou e foi ao prompt neste turno (fatia 7), com a proveniência."""
    ms_ate_contexto: float = 0.0
    ms_ate_primeiro_token: float | None = None
    """Do turno aceito ao primeiro texto que o motor entregou (antes do fatiador)."""
    ms_ate_primeiro_pedaco: float | None = None
    ms_ate_primeira_ferramenta: float | None = None
    """Do turno aceito à primeira ferramenta (a do caminho rápido, a do turno ou a que foi para a
    tarefa): a etapa «1ª tool» da medição de velocidade (ADR-0045)."""
    ms_cancelamento_ate_motor_parado: float | None = None
    tarefa_id: str = ""
    """O pedido virou a tarefa deste id (ADR-0038): o turno acabou na frase curta, e o resultado
    chega pela fila de avisos quando ela terminar."""
    so_na_tela: str = ""
    """O que passou do orçamento da fala e foi só para a tela (emenda de 2026-10-21 à ADR-0031):
    entra na conversa marcado, para o modelo saber que o dono viu e não ouviu."""
    atalho: str = ""
    """A regra do caminho rápido que fez o primeiro passo (`jarvis.politica.atalho.Regra`), ou
    vazio: o turno foi todo do motor."""
    motor_chamado: bool = True
    """`False` quando o atalho resolveu o pedido sozinho e o motor nem foi chamado."""
    caladas: list[str] = field(default_factory=list)
    """Frases do motor que repetiam o que o dono já tinha ouvido neste turno (o aviso, a frase do
    código): foram à tela e não à voz (`jarvis.s2.entrega`, dono, 2026-10-25)."""

    @property
    def cancelada(self) -> bool:
        return self.fim is MotivoDoFim.CANCELADO


@dataclass(slots=True)
class Cerebro:
    """Uma conversa, um motor trocável, e o stream de pedaços de fala."""

    motor: MotorDeConversa
    conversa: Conversa = field(default_factory=Conversa)
    livro: LivroDeMemoria | None = None
    """O histórico persistente (ADR-0026, M1). Sem ele, a conversa vive só na memória."""
    session_id: str = ""
    id_da_conversa: str = ""
    """A conversa persistente a que os turnos pertencem no livro (reabrir o app a continua).
    Vazio = a da sessão, como antes."""
    turno_corrente: TurnoCorrente | None = None
    ferramentas: ExecutorDeFerramentas | None = None
    """O executor das tools do catálogo v1 (ADR-0028). Sem ele, pedido de tool volta negado."""
    confirmar: Confirmar = negar_sempre
    """Como o dono confirma: a janela liga aqui. Sem janela, toda confirmação é não."""
    lembrar_a_cada_turno: bool = True
    """Com livro, consulta a memória antes de cada resposta (fatia 7, `memoria_do_turno`)."""
    alcance_de_memoria: AlcanceDeMemoria = field(default_factory=AlcanceDeMemoria)
    """O que o dono deixou a memória alcançar (ADR-0026, regra 7) — o D20 decide com ele."""
    ao_lembrar: Callable[[MemoriaDoTurno], None] | None = None
    """Chamada da linha do cérebro quando a consulta termina, antes do motor: é por onde a tela
    mostra "lembrei: …". Quem liga aqui guarda e volta."""
    maximo_de_passos: int = MAXIMO_DE_PASSOS
    """Teto configurável de chamadas no encadeamento de ferramentas deste turno."""
    prazo_do_laco_de_ferramentas_s: float = PRAZO_DO_LACO_DE_FERRAMENTAS_S
    """Teto configurável, em segundos, para o encadeamento inteiro."""
    ao_status: AvisarStatus | None = None
    """Porta para a fila de avisos: status nunca é publicado por cima da fala em curso."""
    relogio: Callable[[], float] = time.monotonic
    """Relógio injetável para medir o prazo do laço sem tornar o teste lento."""
    portao: PortaoDeAcao | None = None
    """O portão contextual (Jev) antes de cada ferramenta (`jarvis.s2.fluxo_de_acao`). Com ele, a
    confirmação vira pendência que não prende o turno, o "sim" pode ser falado e a execução
    confirmada vai para uma tarefa. `None` = o caminho de antes: só o PDP, e a janela bloqueia."""
    pendencias: RegistroDePendencias = field(default_factory=RegistroDePendencias)
    autorizacoes: AutorizacoesExplicitas = field(default_factory=AutorizacoesExplicitas)
    pendencia_sem_portao: bool = False
    """A confirmação vira pendência mesmo sem o portão (o dono não ligou o classificador): o
    turno acaba na pergunta, e o dono responde com o «sim»/«não» falado — o literal, lido pelo
    código — ou com o clique (dono, 2026-10-25; ADR-0048). O aplicativo liga; desligado, a janela
    bloqueia a linha do cérebro até o clique, como antes (o que os testes do laço usam)."""
    delegar_em_tarefa: bool = False
    """O trabalho longo de um pedido vira uma **tarefa** do objetivo (ADR-0038, emendada pela
    ADR-0046): a primeira ferramenta roda no turno — o pedido de um passo responde aqui —, e
    quando o motor pede mais do que `passos_no_turno` ferramentas (uma, no objetivo que precisa
    conferir) ou o laço passa de `segundos_no_turno`, o resto vai para a tarefa: o turno diz a
    frase curta e acaba — o Jarvis segue ouvindo —, e ela itera pelo mesmo PDP, Jev e objetivo até
    cumprir, precisar do dono, falhar ou ser cancelada. Precisa do gestor de tarefas no executor;
    o aplicativo liga. Desligado = o laço todo no turno (o que os testes do laço e o harness
    usam)."""
    caminho_rapido: bool = False
    """O comando simples vai à ferramenta pela regra do código, sem esperar o motor (dono,
    2026-10-21: «precisa ser muito rápido»; `jarvis.politica.atalho`). A chamada passa pelo mesmo
    PDP, Jev, objetivo e pergunta da proposta do modelo; pronta e certa, a frase é do código e o
    motor nem é chamado. O aplicativo liga; desligado, como antes (os testes do laço)."""
    passos_no_turno: int = PASSOS_NO_TURNO
    """Com `delegar_em_tarefa`: ferramentas que o turno roda antes de passar o resto à tarefa."""
    segundos_no_turno: float = SEGUNDOS_NO_TURNO
    """Com `delegar_em_tarefa`: laço mais longo que isto passa a próxima ferramenta à tarefa."""
    _pendentes: dict[str, Resposta] = field(default_factory=dict)

    @property
    def fluxo(self) -> FluxoDeAcao | None:
        if self.portao is None and not self.pendencia_sem_portao:
            return None
        return FluxoDeAcao(self.portao, self.pendencias, self.autorizacoes)

    def resolver_pendencia(self, pendencia_id: str, sim: bool) -> bool:
        """O clique do dono numa pendência (não bloqueante). Devolve se ela ainda valia."""
        aberta = self.pendencias.valida()
        if aberta is not None and aberta.id == pendencia_id and aberta.espera is not None:
            # A tarefa de um pedido parada nesta pergunta (ADR-0038): o clique a acorda, com ou
            # sem portão, e ela segue sozinha.
            return self.pendencias.tomar(pendencia_id, sim=sim, origem="clique") is not None
        fluxo = self.fluxo
        if fluxo is None or self.ferramentas is None:
            return False
        resultado = fluxo.resolver(self.ferramentas, pendencia_id, sim=sim)
        if resultado is None:
            return False
        # Confirmado no clique, a ação vai para uma tarefa e o fim dela é a resposta (o aviso da
        # ferramenta): nada de "está rodando, aviso quando terminar" antes (dono, 2026-10-25). A
        # que roda aqui mesmo (a memória) tem a frase dela, como no "sim" falado.
        if sim and resultado.status == "ok" and aberta is not None and aberta.id == pendencia_id:
            self._status(frase_do_feito(aberta.pergunta, resultado))
        elif sim and resultado.status not in ("ok", "despachado"):
            self._status(f"Não deu para fazer o que você confirmou: {resultado.motivo}")
        return True

    @property
    def proveniencia(self) -> Proveniencia:
        """A origem de uma escrita de memória neste turno — do estado do cérebro, nunca do
        modelo (ADR-0026, regra 2). Sem histórico não há episódio, e a escrita é negada."""
        return Proveniencia(turno=self.turno_corrente, motor=self.motor.nome)

    def responder(
        self,
        texto_do_dono: str,
        *,
        epoch: int,
        publicar: Publicar,
        turn_id: str = "",
        cancelado: Cancelado = nunca_cancelado,
        modo: Modo = Modo.RAPIDO,
        trust: str = "user_voice",
        avisos: Sequence[AvisoLiberado] = (),
        mostrar: Mostrar | None = None,
    ) -> Resposta:
        """Responde a um turno estável do dono, publicando os pedaços enquanto o motor gera.

        `avisos` são os que a fila liberou junto com esta mensagem e que o `s2` decidiu falar
        (ADR-0025, regra 13, decisão do dono): vão **antes** da resposta, em pedaços marcados
        com `notif_ids`, e o motor fica sabendo que já foram ditos — informa, depois responde.
        """
        comeco = time.monotonic()
        # Resposta anterior sem `ouvido`: ninguém confirmou que tocou, então não existe (P4).
        self._pendentes.clear()
        anteriores = tuple(self.conversa.turnos)
        self.conversa.turnos.append(Mensagem("dono", texto_do_dono))
        self.turno_corrente = None
        if self.ferramentas is not None:
            self.ferramentas.novo_turno(texto_do_dono)
        if self.livro is not None:
            episodio = self.livro.gravar_turno(
                session_id=self.id_da_conversa or self.session_id,
                papel="dono",
                texto=texto_do_dono,
                trust=trust,
            )
            self.turno_corrente = TurnoCorrente(episodio, texto_do_dono, trust)
        fluxo = self.fluxo
        nota_da_pendencia = ""
        if fluxo is not None and self.ferramentas is not None:
            # A fala é lida primeiro contra a pergunta pendente (se houver uma válida): "sim"
            # resolve **aquela** e o turno é só a confirmação; outro assunto a cancela.
            leitura = fluxo.ler_a_resposta(
                self.ferramentas, texto_do_dono, mensagens=anteriores, cancelado=cancelado
            )
            if leitura.frase:
                return self._so_dizer(
                    leitura.frase,
                    epoch=epoch,
                    turn_id=turn_id,
                    publicar=publicar,
                    cancelado=cancelado,
                    comeco=comeco,
                    ferramentas=[leitura.resultado] if leitura.resultado else [],
                    mostrar=mostrar,
                )
            nota_da_pendencia = leitura.nota
            self.autorizacoes.novo_turno(texto_do_dono)
        memoria = None
        contexto = self.conversa.contexto()
        metodo = self.ferramentas.metodo if self.ferramentas is not None else None
        if metodo is not None and metodo.nota():
            # O roteador de método (ADR-0035): o caminho direto para este pedido, dito ao modelo.
            contexto = Contexto(
                sistema=f"{contexto.sistema}\n\n{metodo.nota()}", mensagens=contexto.mensagens
            )
        if nota_da_pendencia:
            contexto = Contexto(
                sistema=f"{contexto.sistema}\n\n{nota_da_pendencia}", mensagens=contexto.mensagens
            )
        nota_da_tela = self._nota_da_tela(texto_do_dono, anteriores)
        if nota_da_tela:
            # O guia de design só no turno que monta ou muda a tela (ADR-0055): sob demanda, e
            # nunca o conteúdo da exibição — esse pode ter texto de página e vem pelo tela.ler.
            contexto = Contexto(
                sistema=f"{contexto.sistema}\n\n{nota_da_tela}", mensagens=contexto.mensagens
            )
        if self.livro is not None and self.lembrar_a_cada_turno:
            memoria = consultar(
                self.livro,
                texto_do_dono,
                onde=self.motor.onde,
                motor=self.motor.nome,
                alcance=self.alcance_de_memoria,
            )
            if self.ao_lembrar is not None:
                self.ao_lembrar(memoria)
            if memoria.bloco():
                contexto = Contexto(
                    sistema=f"{contexto.sistema}\n\n{memoria.bloco()}",
                    mensagens=contexto.mensagens,
                )
        if avisos:
            ditos = " ".join(frase_do_aviso(a) for a in avisos)
            contexto = Contexto(
                sistema=f"{contexto.sistema}\n\nAntes desta resposta você já disse ao dono, em "
                f"voz: «{ditos}» Não repita o aviso: responda à mensagem dele.",
                mensagens=contexto.mensagens,
            )
        resposta = Resposta(
            response_id=f"r-{uuid7()}",
            turn_id=turn_id or f"t-{uuid7()}",
            epoch=epoch,
            motor=self.motor.nome,
            ms_ate_contexto=_ms_desde(comeco),
            memoria=memoria,
        )
        fatiador = FatiadorDeFala()
        # O que vai para a voz cabe no orçamento; a tela recebe tudo (dono, 2026-10-21).
        orcamento = OrcamentoDaFala(livre=quer_detalhe(texto_do_dono))
        crescer = _tela(resposta, mostrar)
        visto_cancelamento = self._falar_avisos(
            avisos, resposta, publicar, comeco, cancelado, crescer
        )
        catalogo = self.ferramentas.catalogo_para_o_modelo() if self.ferramentas else ()
        # A tela mais nova que uma ferramenta deste turno capturou (ADR-0032): vai só ao motor que
        # a aceita, e só neste turno.
        imagens: tuple[Imagem, ...] = ()
        limite_do_laco = self.relogio() + self.prazo_do_laco_de_ferramentas_s

        def prazo_esgotado() -> bool:
            return self.relogio() >= limite_do_laco

        def cancelado_no_laco() -> bool:
            return cancelado() or prazo_esgotado()

        # O caminho rápido (dono, 2026-10-21): o comando simples vai à ferramenta pela regra do
        # código, sem esperar o motor — pelo mesmo `_chamar` (PDP, Jev, objetivo, pergunta) que a
        # proposta do modelo. Pronto e certo, a frase é do código e o motor nem é chamado; erro,
        # pergunta ou pedido que continua (abrir o canal de alguém): o motor segue dali.
        pular_o_motor = False
        atalho = self._atalho(texto_do_dono) if visto_cancelamento is None else None
        if atalho is not None:
            resposta.atalho = str(atalho.regra)
            _marcar_a_primeira_ferramenta(resposta, comeco)
            resultado = self._chamar(
                PedidoDeTool(atalho.tool_id, dict(atalho.args)), cancelado_no_laco, texto_do_dono
            )
            resposta.ferramentas.append(resultado)
            # Nenhum navegador com a extensão (o Brave fechado): o Jarvis abre o do dono — o
            # sites.open já com a página (ADR-0036, emenda (2); ADR-0046).
            extras = self._abrir_o_navegador(
                PedidoDeTool(atalho.tool_id, dict(atalho.args)),
                resultado,
                lambda p: self._chamar(p, cancelado_no_laco, texto_do_dono),
                lambda p: self._chamar(p, cancelado_no_laco, texto_do_dono, self._sem_o_metodo()),
            )
            resposta.ferramentas.extend(extras)
            resultado = extras[-1] if extras else resultado
            if self.ferramentas is not None and self.ferramentas.trilha is not None:
                self.ferramentas.trilha.evento(
                    "atalho",
                    regra=str(atalho.regra),
                    tool_id=atalho.tool_id,
                    status=resultado.status,
                    completo=atalho.completo,
                )
            if resultado.aviso:  # o de uma moderada, ou a pergunta: do código, já em voz
                resposta.gerado += resultado.aviso + " "
                crescer()
                for pedaco in fatiador.alimentar(resultado.aviso + " ") + fatiador.descarregar():
                    self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
            if cancelado():
                visto_cancelamento = time.monotonic()
            elif resultado.status == "pendente":
                pular_o_motor = True  # a pergunta é a última coisa do turno, como no laço
            elif resultado.status == "ok":
                # Pronto e certo, a frase é do código. No primeiro passo à vista ("Abri a busca do
                # YouTube por …") ela sai já, e o motor segue — sem o "Certo, já cuido disso."
                # Frase do código: não passa pelo orçamento da fala (como o aviso) e sai já.
                dita = frase_do_atalho(atalho, resultado.dados)
                if dita:
                    resposta.gerado += dita
                    crescer()
                    for pedaco in fatiador.alimentar(dita + " ") + fatiador.descarregar():
                        self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
                pular_o_motor = atalho.completo
                if not atalho.completo:
                    contexto = Contexto(
                        sistema=f"{contexto.sistema}\n\n{NOTA_DO_ATALHO}",
                        mensagens=contexto.mensagens,
                    )
            else:
                contexto = Contexto(
                    sistema=f"{contexto.sistema}\n\n{NOTA_DO_ATALHO}", mensagens=contexto.mensagens
                )
        resposta.motor_chamado = not pular_o_motor
        passos = range(0) if pular_o_motor else range(1, self.maximo_de_passos + 1)
        for passo in passos:
            if visto_cancelamento is not None:
                break
            if cancelado_no_laco():
                if cancelado():
                    visto_cancelamento = time.monotonic()
                else:
                    resposta.fim = MotivoDoFim.PRAZO
                    resposta.detalhe = (
                        f"o laço de ferramentas passou de "
                        f"{self.prazo_do_laco_de_ferramentas_s:.0f} s"
                    )
                break
            if self._continua_na_tarefa(resposta) and not cancelado():
                # O objetivo que precisa conferir (navegador, entrada virtual): o turno fez o
                # primeiro passo; ler, seguir e conferir antes de dizer «abri» é da tarefa — o turno
                # não afirma o que ninguém conferiu (ADR-0038, ADR-0046).
                self._delegar(
                    None, contexto, texto_do_dono, resposta, fatiador, publicar, comeco, crescer
                )
                break
            # A memória de trabalho do turno (ADR-0034): o passo mais novo inteiro, os antigos
            # inteiros enquanto couberem no orçamento e, depois, podados.
            textos, podados = textos_no_contexto(resposta.ferramentas)
            resposta.resultados_podados = max(resposta.resultados_podados, podados)
            da_vez = Contexto(
                sistema=contexto.sistema,
                mensagens=(*contexto.mensagens, *(Mensagem("ferramenta", t) for t in textos)),
                ferramentas=catalogo,
                raciocinio=resposta.raciocinio,
                ja_dito=_ja_dito(resposta),
                imagens=imagens,
            )
            # Depois de uma ferramenta, a frase que repete o que o dono já ouviu neste turno (o
            # aviso, a frase do código, o "vou abrir") vai só à tela (dono, 2026-10-25), e a que
            # cita uma ferramenta pelo id nem à tela da voz chega (ADR-0038, agora também no turno).
            dito = _dito_no_turno(resposta)
            filtro = (
                FiltroDoJaDito(ditos=[dito] if dito else [], ids=self._ids_das_ferramentas())
                if resposta.ferramentas
                else None
            )
            pedidos, visto_cancelamento = self._rodada(
                da_vez,
                modo,
                cancelado_no_laco,
                fatiador,
                resposta,
                publicar,
                comeco,
                crescer,
                segurar=passo > 1 or bool(resposta.ferramentas),
                orcamento=orcamento,
                filtro=filtro,
            )
            if prazo_esgotado() and not cancelado():
                visto_cancelamento = None
                resposta.fim = MotivoDoFim.PRAZO
                resposta.detalhe = (
                    f"o laço de ferramentas passou de {self.prazo_do_laco_de_ferramentas_s:.0f} s"
                )
                break
            if (
                visto_cancelamento is not None
                or not pedidos
                or resposta.fim is not MotivoDoFim.CONCLUIDO
            ):
                break
            # O que o motor disse antes de pedir a ferramenta ("deixa eu ver") sai agora, mesmo
            # abaixo do piso de 14 palavras do lote: até a ferramenta voltar não há mais texto.
            # Com `alimentar(" ")` (antes de 7507cd5 bastava), a frase ficava no buffer e era
            # falada só depois da ferramenta. Da segunda rodada em diante a narração curta nem
            # chega aqui: `_rodada` a segura e a passa ao raciocínio (ADR-0031).
            for pedaco in fatiador.descarregar():
                self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
            # Uma por vez: o próximo pedido só pode nascer depois que o modelo viu este
            # resultado. Pedidos adicionais da mesma geração são especulativos e ficam de fora.
            pedido = pedidos[0]
            _marcar_a_primeira_ferramenta(resposta, comeco)
            if self._vai_para_tarefa(pedido, resposta, comeco) and not cancelado():
                # O trabalho longo vira tarefa (ADR-0038, ADR-0046): o turno acaba na frase curta.
                self._delegar(
                    pedido, contexto, texto_do_dono, resposta, fatiador, publicar, comeco, crescer
                )
                break
            if cancelado_no_laco():
                if cancelado():
                    visto_cancelamento = time.monotonic()
                else:
                    resposta.fim = MotivoDoFim.PRAZO
                    resposta.detalhe = (
                        f"o laço de ferramentas passou de "
                        f"{self.prazo_do_laco_de_ferramentas_s:.0f} s"
                    )
                break
            resultado = self._chamar(pedido, cancelado_no_laco, texto_do_dono)
            resposta.ferramentas.append(resultado)
            # O navegador fechado não é motivo para mandar o dono abri-lo (dono, 2026-10-25): o
            # Jarvis abre e segue — a página pelo sites.open, ou o navegador e o passo de novo.
            extras = self._abrir_o_navegador(
                pedido,
                resultado,
                lambda p: self._chamar(p, cancelado_no_laco, texto_do_dono),
                lambda p: self._chamar(p, cancelado_no_laco, texto_do_dono, self._sem_o_metodo()),
            )
            resposta.ferramentas.extend(extras)
            resultado = extras[-1] if extras else resultado
            if resultado.anexos and aceita_imagem(self.motor):
                imagens = resultado.anexos
            # Sem status entre passos (dono, 2026-10-20, ADR-0031): ele não acompanha passo a
            # passo. O aviso de uma moderada é resultado (o que mudou e se desfaz); o passo de
            # navegação vem sem aviso (`aviso_silencioso` no manifesto).
            if resultado.aviso:
                # Tool moderada: o aviso é do código, e sai agora, em voz (dono, 2026-10-18).
                resposta.gerado += resultado.aviso + " "
                crescer()
                for pedaco in fatiador.alimentar(resultado.aviso + " ") + fatiador.descarregar():
                    self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
            if resultado.status == "pendente":
                # A pergunta é a última coisa do turno: o laço de voz fica livre para o "sim".
                break
            # A ação de um passo que deu certo (dono, 2026-10-25): o resultado sai já, na frase do
            # código, se o dono ainda não o ouviu; e o pedido simples acaba aqui, sem outra rodada
            # do motor para dizer "pronto" de novo.
            dita = self._frase_da_acao(pedido, resultado, resposta)
            if dita:
                resposta.gerado += dita + " "
                crescer()
                for pedaco in fatiador.alimentar(dita + " ") + fatiador.descarregar():
                    self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
            if self._cumpriu_no_turno(pedido, resultado, resposta, texto_do_dono):
                break
            if prazo_esgotado() and not cancelado():
                resposta.fim = MotivoDoFim.PRAZO
                resposta.detalhe = (
                    f"o laço de ferramentas passou de {self.prazo_do_laco_de_ferramentas_s:.0f} s"
                )
                break
            if cancelado():
                visto_cancelamento = time.monotonic()
        else:
            if not pular_o_motor:
                resposta.detalhe = (
                    f"o motor pediu ferramenta {self.maximo_de_passos} vezes sem responder"
                )
        if visto_cancelamento is None and cancelado():
            visto_cancelamento = time.monotonic()
        if visto_cancelamento is not None or resposta.fim is MotivoDoFim.CANCELADO:
            resposta.fim = MotivoDoFim.CANCELADO
            parado = time.monotonic()
            resposta.ms_cancelamento_ate_motor_parado = (
                (parado - visto_cancelamento) * 1000.0 if visto_cancelamento is not None else 0.0
            )
        else:
            # A quarta frase que esperava, a última sem ponto, ou o fecho do que ficou na tela.
            for pedaco in fatiador.alimentar(orcamento.fechar()):
                self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
            for pedaco in fatiador.fechar():
                self._publicar(resposta, pedaco, publicar, comeco, ultimo=pedaco.corte is Corte.FIM)
        resposta.so_na_tela = orcamento.so_na_tela
        objetivo = self.ferramentas.objetivo if self.ferramentas is not None else None
        if resposta.tarefa_id:
            # O objetivo foi com a tarefa: é ela que o conclui.
            resposta.estado_do_objetivo = str(EstadoDoObjetivo.EM_ANDAMENTO)
        elif objetivo is not None:
            # O pedido como objetivo (Lote C, C2): a resposta final é a fase de concluir; o estado
            # diz se acabou, se espera o dono, se falhou ou se ele interrompeu.
            objetivo.concluir(_estado_final(resposta))
            resposta.estado_do_objetivo = str(objetivo.estado)
        self.autorizacoes.encerrar()
        self._pendentes[resposta.response_id] = resposta
        return resposta

    def _nota_da_tela(self, texto_do_dono: str, anteriores: Sequence[Mensagem]) -> str:
        """A nota da tela deste turno (`jarvis.tela.guia`), só quando as `tela.*` existem (a
        janela está aberta)."""
        executor = self.ferramentas
        porta = executor.portas().tela if executor is not None else None
        if porta is None:
            return ""
        ultima = next((m.texto for m in reversed(anteriores) if m.papel == "jarvis"), "")
        return nota_da_tela(texto_do_dono, ultima, porta.abertas())

    def _abrir_o_navegador(
        self,
        pedido: PedidoDeTool,
        resultado: ResultadoDeFerramenta,
        chamar: Callable[[PedidoDeTool], ResultadoDeFerramenta],
        abrir: Callable[[PedidoDeTool], ResultadoDeFerramenta] | None = None,
    ) -> list[ResultadoDeFerramenta]:
        """Com o navegador fechado, o Jarvis o abre — ele pode e deve (dono, 2026-10-25: «abre um
        vídeo no YouTube» com o Brave fechado mandava o dono abrir). A navegação com endereço vai
        pelo `sites.open`, que abre o navegador do dono já na página; outro passo (ler as abas, a
        página) abre o navegador (`browser.launch`), espera a extensão conectar e tenta de novo,
        uma vez. As chamadas passam pelo PDP, Jev e pergunta de sempre; `abrir` é a do
        `browser.launch`, sem o método do pedido — que tira o `browser.launch` do **modelo** num
        pedido de site, e aqui quem decide abrir é o código. Devolve o que rodou a mais."""
        if not _sem_navegador_aberto(pedido, resultado):
            return []
        url = pedido.args.get("url")
        if (
            pedido.tool_id == "browser.navigate"
            and isinstance(url, str)
            and self._pode("sites.open")
        ):
            return [chamar(PedidoDeTool("sites.open", {"url": url}))]
        executor = self.ferramentas
        if pedido.tool_id == "browser.launch" or executor is None:
            return []
        if executor.navegadores is None or not executor.disponivel("browser.launch"):
            return []  # nenhum navegador configurado: não há o que abrir, e o motor diz
        aberto = (abrir or chamar)(PedidoDeTool("browser.launch", {}))
        if aberto.status != "ok" or not self._esperar_a_extensao():
            return [aberto]
        return [aberto, chamar(pedido)]

    def _sem_o_metodo(self) -> Contaminacao | None:
        """A marca do turno sem o método do pedido — a contaminação e o objetivo de agora seguem
        para o PDP — para a chamada que o próprio código decide (abrir o navegador fechado)."""
        executor = self.ferramentas
        if executor is None:
            return None
        return Contaminacao(executor.turno.valor, executor.objetivo, None)

    def _esperar_a_extensao(self) -> bool:
        """Espera a extensão do navegador recém-aberto conectar (até `ESPERA_DA_EXTENSAO_S`). Sem
        como sondar a ponte (o teste, a sessão sem navegador configurado), tenta de novo direto."""
        executor = self.ferramentas
        sondar = executor.estado_do_navegador if executor is not None else None
        if sondar is None:
            return True
        limite = time.monotonic() + ESPERA_DA_EXTENSAO_S
        while time.monotonic() < limite:
            try:
                if sondar().conectado:
                    return True
            except Exception:
                return False
            time.sleep(INTERVALO_DA_EXTENSAO_S)
        return False

    def _ids_das_ferramentas(self) -> frozenset[str]:
        return (
            frozenset(self.ferramentas.manifestos) if self.ferramentas is not None else frozenset()
        )

    def _pode(self, tool_id: str) -> bool:
        """A ferramenta existe nesta sessão e o método do pedido não a tirou (ADR-0035)."""
        executor = self.ferramentas
        if executor is None or not executor.disponivel(tool_id):
            return False
        return executor.metodo is None or tool_id not in executor.metodo.evitar

    def _atalho(self, texto_do_dono: str) -> Atalho | None:
        if not self.caminho_rapido or self.ferramentas is None:
            return None
        return self.ferramentas.atalho(texto_do_dono)

    def _delegavel(self, pedido: PedidoDeTool) -> bool:
        """A proposta pode ir para a tarefa do pedido? `tarefa.*` e `acao.desfazer` não rodam em
        tarefa (profundidade 1) e são rápidas; a ferramenta que não existe aqui, a malformada e a
        que o método do pedido tirou são recusadas na hora, no turno, para o motor se corrigir."""
        executor = self.ferramentas
        if not self.delegar_em_tarefa or executor is None or executor.tarefas is None:
            return False
        if pedido.tool_id.startswith(FORA_DA_ALLOWLIST) or not executor.disponivel(pedido.tool_id):
            return False
        return executor.metodo is None or pedido.tool_id not in executor.metodo.evitar

    def _vai_para_tarefa(self, pedido: PedidoDeTool, resposta: Resposta, comeco: float) -> bool:
        """A proposta vai para a tarefa, ou roda no turno? (dono, 2026-10-25; ADR-0046)

        A primeira ferramenta do pedido é sempre do turno: o pedido de um passo — abrir, fechar,
        focar, uma pergunta, uma ferramenta — responde aqui, uma vez. Vira tarefa o trabalho longo:
        o motor pediu mais ferramentas do que `passos_no_turno`, ou o laço passou de
        `segundos_no_turno`. O objetivo que precisa conferir passa à tarefa logo depois do primeiro
        passo (`_continua_na_tarefa`)."""
        if not self._delegavel(pedido):
            return False
        feitas = len(resposta.ferramentas)
        if feitas == 0:
            return False
        return (
            feitas >= self.passos_no_turno or _ms_desde(comeco) >= 1000.0 * self.segundos_no_turno
        )

    def _continua_na_tarefa(self, resposta: Resposta) -> bool:
        """Depois do primeiro passo de um objetivo que precisa conferir (agir e depois ler: o
        navegador, a entrada virtual), o resto — inclusive a resposta — vai para a tarefa, que cobra
        a leitura antes de deixar dizer «abri». A pergunta ao dono continua no turno."""
        executor = self.ferramentas
        if not self.delegar_em_tarefa or executor is None or executor.tarefas is None:
            return False
        objetivo = executor.objetivo
        if objetivo is None or not objetivo.pede_conferencia or not resposta.ferramentas:
            return False
        return resposta.ferramentas[-1].status != "pendente"

    def _frase_da_acao(
        self, pedido: PedidoDeTool, resultado: ResultadoDeFerramenta, resposta: Resposta
    ) -> str:
        """A frase do código para a ação de um passo que o motor propôs e deu certo («Abrindo o
        Discord.»), se o dono ainda não ouviu isso neste turno — o "vou abrir o Discord" do motor
        já disse. O app que já estava aberto é sempre novidade."""
        if resultado.status != "ok":
            return ""
        objetivo = self.ferramentas.objetivo if self.ferramentas is not None else None
        if objetivo is not None and objetivo.pede_conferencia:
            return ""  # no navegador, "abri" só depois de ler e conferir (ADR-0038)
        if pedido.tool_id not in ACOES_DE_UM_PASSO and len(resposta.ferramentas) > 1:
            return ""  # no meio de uma cadeia (abrir o site achado), quem conta é a resposta final
        frase = frase_da_ferramenta(pedido.tool_id, pedido.args, resultado.dados)
        if not frase:
            return ""
        dito = _dito_no_turno(resposta)
        if not dito or resultado.dados.get("ja_aberto") or traz_algo_novo(frase, [dito]):
            return frase
        return ""

    def _cumpriu_no_turno(
        self,
        pedido: PedidoDeTool,
        resultado: ResultadoDeFerramenta,
        resposta: Resposta,
        texto_do_dono: str,
    ) -> bool:
        """O pedido simples acabou nesta ação: deu certo, foi a única do turno, é uma ação de um
        passo, a fala pedia só ela e o dono já ouviu o resultado (o aviso, a frase do código ou a
        do motor). Outra rodada do motor só diria "pronto" de novo — e custaria segundos."""
        return (
            resultado.status == "ok"
            and len(resposta.ferramentas) == 1
            and pedido.tool_id in ACOES_DE_UM_PASSO
            and fala_simples(texto_do_dono)
            and bool(_dito_no_turno(resposta).strip())
        )

    def _delegar(
        self,
        pedido: PedidoDeTool | None,
        contexto: Contexto,
        texto_do_dono: str,
        resposta: Resposta,
        fatiador: FatiadorDeFala,
        publicar: Publicar,
        comeco: float,
        crescer: Callable[[], None],
    ) -> None:
        """Cria a tarefa do pedido e diz a frase curta. O que a tarefa leva é do **turno em que o
        pedido chegou**: o objetivo, o método, a contaminação, a autorização explícita (a fala
        dele, com o mesmo prazo), a conversa e a proveniência — o turno seguinte não mexe nela."""
        executor = self.ferramentas
        assert executor is not None and executor.tarefas is not None
        marca = Contaminacao(executor.turno.valor, executor.objetivo, executor.metodo)
        autorizacoes = AutorizacoesExplicitas(
            prazo_s=self.autorizacoes.prazo_s, relogio=self.autorizacoes.relogio
        )
        autorizacoes.novo_turno(texto_do_dono)
        # A frase curta é a do motor, se ele disse uma antes da ferramenta (os avisos que foram
        # junto com a mensagem do dono não contam: são de outra coisa).
        motor_falou = any(p["text"] and not p.get("notif_ids") for p in resposta.publicados)
        frase = "" if motor_falou else FRASE_AO_DELEGAR
        motor = MotorDoObjetivo(
            motor=self.motor,
            contexto=contexto,
            catalogo=executor.catalogo_para_o_modelo,
            primeiro=pedido,
            feitos_antes=tuple(resposta.ferramentas),
            raciocinio=resposta.raciocinio,
            ja_dito=f"{resposta.gerado} {frase}".strip()[-LIMITE_DO_JA_DITO:],
            ids=frozenset(executor.manifestos),
            limite_do_raciocinio=LIMITE_DO_RACIOCINIO,
        )
        try:
            tarefa = executor.tarefas.iniciar_objetivo(
                marca.objetivo.pedido if marca.objetivo is not None else texto_do_dono,
                motor,
                contaminacao=marca,
                chamar=self._chamada_da_tarefa(
                    marca, autorizacoes, texto_do_dono, tuple(self.conversa.turnos)
                ),
                prazo_s=self.prazo_do_laco_de_ferramentas_s,
                maximo_de_passos=max(1, self.maximo_de_passos - len(resposta.ferramentas)),
                # O que o dono já ouviu deste pedido (dono, 2026-10-25): o fim da tarefa não repete.
                ja_dito=f"{_dito_no_turno(resposta)} {frase}".strip(),
                turno=resposta.turn_id,
            )
        except TarefaRecusada as erro:
            frase = f"Agora não dá para começar isso: {erro}."
        else:
            resposta.tarefa_id = tarefa.id
        if frase:
            resposta.gerado += frase + " "
            crescer()
            for pedaco in fatiador.alimentar(frase + " ") + fatiador.descarregar():
                self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)

    def _chamada_da_tarefa(
        self,
        marca: Contaminacao,
        autorizacoes: AutorizacoesExplicitas,
        texto_do_dono: str,
        mensagens: Sequence[Mensagem],
    ) -> ChamarNaTarefa:
        """Como cada passo da tarefa do pedido chega ao executor: pelo portão do turno quando ele
        existe (PDP → Jev → objetivo → autorização → pergunta ao dono), senão só pelo PDP — com a
        pergunta e o aviso de uma moderada indo à voz pela fila de avisos."""
        executor = self.ferramentas
        assert executor is not None and executor.tarefas is not None
        gestor = executor.tarefas
        fluxo = self.fluxo
        proveniencia = self.proveniencia
        session_id = self.session_id

        pendencias = self.pendencias

        def chamar(
            tarefa: Tarefa,
            pedido: PedidoDeTool,
            call_id: str,
            confirmar: Callable[[Confirmacao], bool],
        ) -> ResultadoDeFerramenta:
            del (
                confirmar
            )  # a pergunta da tarefa do pedido não prende a linha na janela: é pendência
            anunciadas: list[str] = []

            def anunciar(pergunta: Confirmacao, frase: str) -> None:
                gestor.esperando_o_dono(tarefa, True)
                anunciadas.append(f"pergunta-{pergunta.id}")
                gestor.avisar(tarefa, anunciadas[-1], "precisa_decisao", frase)

            def na_voz(pergunta: Confirmacao) -> None:
                anunciar(pergunta, pergunta.pergunta_falada)

            def confirmar_na_janela(pergunta: Confirmacao) -> bool:
                # A pergunta por ação (o que está sob o clique) e a que nasce sem o portão: dita em
                # voz, e respondida por voz ou pelo clique (dono, 2026-10-29: «o Jarvis pergunta
                # falando e eu respondo "sim, pode seguir"; vale sem clique»). O "sim" falado passa
                # pela leitura sem rede (ou o Jev) e pelos sinais de fala real (ADR-0043).
                resposta = pendencias.esperar(
                    pergunta,
                    contaminado=marca.valor,
                    cancelado=tarefa.cancelada.is_set,
                    anunciar=na_voz,
                    espera=Espera(),
                )
                return bool(resposta) and not tarefa.cancelada.is_set()

            extras = 0

            def passo(chamada: PedidoDeTool, *, sem_metodo: bool = False) -> ResultadoDeFerramenta:
                nonlocal extras
                identificador = (
                    call_id if chamada is pedido and not extras else f"{call_id}-{extras}"
                )
                extras += 1
                # A abertura do navegador fechado é do código: sem o método do pedido (ADR-0046).
                quem = Contaminacao(marca.valor, marca.objetivo, None) if sem_metodo else marca
                if fluxo is not None:
                    return fluxo.chamar_na_tarefa(
                        executor,
                        chamada,
                        contaminacao=quem,
                        autorizacoes=autorizacoes,
                        pedido_do_dono=texto_do_dono,
                        mensagens=mensagens,
                        cancelado=tarefa.cancelada.is_set,
                        confirmar=confirmar_na_janela,
                        anunciar=na_voz,
                        session_id=session_id,
                        proveniencia=proveniencia,
                    )
                return executor.executar(
                    chamada.tool_id,
                    chamada.args,
                    cancelado=tarefa.cancelada.is_set,
                    confirmar=confirmar_na_janela,
                    session_id=session_id,
                    call_id=identificador,
                    proveniencia=proveniencia,
                    contaminacao=quem,
                )

            try:
                resultado = passo(pedido)
                # O navegador fechado: a tarefa o abre e segue, como o turno (ADR-0046).
                abertos = self._abrir_o_navegador(
                    pedido, resultado, passo, lambda p: passo(p, sem_metodo=True)
                )
                resultado = abertos[-1] if abertos else resultado
            finally:
                gestor.esperando_o_dono(tarefa, False)
                for identificador in anunciadas:
                    # Respondida (ou vencida): a pergunta que ainda não tocou não vai mais à voz.
                    gestor.retirar_aviso(tarefa, identificador)
            if resultado.aviso:
                # Tool moderada: o aviso é do código e vai à voz já (dono, 2026-10-18), pela fila.
                gestor.avisar(tarefa, f"aviso-{call_id}", "evento", resultado.aviso)
            return resultado

        return chamar

    def _so_dizer(
        self,
        frase: str,
        *,
        epoch: int,
        turn_id: str,
        publicar: Publicar,
        cancelado: Cancelado,
        comeco: float,
        ferramentas: list[ResultadoDeFerramenta],
        mostrar: Mostrar | None = None,
    ) -> Resposta:
        """Um turno sem motor: a frase é do código (a resposta do dono a uma pendência)."""
        resposta = Resposta(
            response_id=f"r-{uuid7()}",
            turn_id=turn_id or f"t-{uuid7()}",
            epoch=epoch,
            motor="portao",
            gerado=frase,
            ferramentas=ferramentas,
            ms_ate_contexto=_ms_desde(comeco),
        )
        _tela(resposta, mostrar)()
        fatiador = FatiadorDeFala()
        for pedaco in fatiador.alimentar(frase):
            if cancelado():
                resposta.fim = MotivoDoFim.CANCELADO
                break
            self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
        else:
            for pedaco in fatiador.fechar():
                self._publicar(resposta, pedaco, publicar, comeco, ultimo=pedaco.corte is Corte.FIM)
        self._pendentes[resposta.response_id] = resposta
        return resposta

    def _rodada(
        self,
        contexto: Contexto,
        modo: Modo,
        cancelado: Cancelado,
        fatiador: FatiadorDeFala,
        resposta: Resposta,
        publicar: Publicar,
        comeco: float,
        crescer: Callable[[], None],
        *,
        segurar: bool = False,
        orcamento: OrcamentoDaFala | None = None,
        filtro: FiltroDoJaDito | None = None,
    ) -> tuple[list[PedidoDeTool], float | None]:
        """Uma chamada ao motor: publica o texto em pedaços e junta os pedidos de ferramenta.

        Pensar não é falar (ADR-0031): o `Raciocinio` fica com o turno; o texto que vem **depois**
        de uma proposta é palpite (o resultado ainda não voltou) e também. Com `segurar` (as
        rodadas depois de uma ferramenta), o texto espera até ter o tamanho de um lote: se uma
        proposta chega antes, era narração de passo e vai para o raciocínio; senão, é a resposta.
        O lote de fala só fecha com 14 palavras, então segurar não atrasa a voz — só a tela,
        nessas rodadas, espera o primeiro lote. Com `filtro`, a frase que só repete o que o dono já
        ouviu neste turno vai à tela e não à voz (`jarvis.s2.entrega`)."""
        pedidos: list[PedidoDeTool] = []
        visto_cancelamento: float | None = None
        retido = ""
        palpite = False
        pensando = False  # o delta anterior era raciocínio: o próximo continua o mesmo trecho
        # Todo texto de **qualquer** motor passa por um leitor do protocolo (ADR-0038): o motor
        # que esqueceu de separar a proposta (ou um JSON solto) não a faz chegar à voz.
        leitor = LeitorDoProtocolo()
        deltas = self.motor.gerar(contexto, modo, cancelado)

        def falar(texto: str) -> bool:
            """Tela e fala; devolve se o cancelamento chegou no meio. A tela recebe tudo; a voz, o
            que traz algo novo e cabe no orçamento."""
            resposta.gerado += texto
            crescer()  # a tela, já: o lote de fala pode levar 14 palavras para fechar
            return dizer(filtro.passar(texto) if filtro is not None else texto)

        def dizer(texto: str) -> bool:
            falado = orcamento.passar(texto) if orcamento is not None else texto
            for pedaco in fatiador.alimentar(falado):
                if cancelado():
                    return True
                self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
            return cancelado()

        def tratar(delta: Delta) -> bool:
            """Um delta já separado do protocolo; devolve se o cancelamento chegou."""
            nonlocal retido, palpite, pensando, segurar
            if isinstance(delta, Pensar):
                # Regra 4: quem refaz no modo `pensar` (com a ponte) é o chamador.
                resposta.pediu_pensar = True
                return False
            if isinstance(delta, Raciocinio):
                _guardar_raciocinio(resposta, delta.texto, separado=not pensando)
                pensando = True
                return False
            pensando = False
            if isinstance(delta, PedidoDeTool):
                pedidos.append(delta)  # o modelo propõe; quem dispõe é o código (P1)
                if retido.strip():
                    resposta.narracao_retida += 1
                    _guardar_raciocinio(resposta, retido, separado=True)
                retido = ""
                return False
            if not isinstance(delta, Texto):
                return False
            if resposta.ms_ate_primeiro_token is None and delta.texto.strip():
                resposta.ms_ate_primeiro_token = _ms_desde(comeco)
            if pedidos:
                novo = not palpite and bool(delta.texto.strip())
                if novo:
                    palpite = True
                    resposta.narracao_retida += 1
                _guardar_raciocinio(resposta, delta.texto, separado=novo)
                return False
            texto = delta.texto
            if segurar:
                retido += texto
                if len(retido.split()) < PALAVRAS_MINIMAS_POR_PEDACO:
                    return False
                texto, retido, segurar = retido, "", False
            return falar(texto)

        try:
            for delta in deltas:
                if isinstance(delta, Fim):
                    resposta.fim, resposta.detalhe = delta.motivo, delta.detalhe
                    if delta.motivo is MotivoDoFim.CANCELADO:
                        visto_cancelamento = time.monotonic()
                    break
                partes = leitor.alimentar(delta.texto) if isinstance(delta, Texto) else [delta]
                if any(tratar(parte) for parte in partes):
                    visto_cancelamento = time.monotonic()
                    break
        finally:
            # Fechar o iterador é o que faz o motor parar de gerar (o `finally` dele).
            deltas.close()
        # O que o leitor ainda segurava (um `<` ou `{` no fim que não era protocolo).
        if (
            visto_cancelamento is None
            and not cancelado()
            and any(tratar(parte) for parte in leitor.fechar())
        ):
            visto_cancelamento = time.monotonic()
        # A rodada acabou sem proposta: o que estava seguro era a resposta.
        if retido.strip() and visto_cancelamento is None and not cancelado() and falar(retido):
            visto_cancelamento = time.monotonic()
        if filtro is not None:
            # A última frase, sem ponto no fim, também passa pelo crivo do já dito — e o que ele
            # calou fica registrado (a trilha conta; a tela já mostrou).
            if not pedidos and visto_cancelamento is None and not cancelado():
                resto = filtro.fechar()
                if resto and dizer(resto):
                    visto_cancelamento = time.monotonic()
            resposta.caladas.extend(filtro.caladas)
        return pedidos, visto_cancelamento

    def _chamar(
        self,
        pedido: PedidoDeTool,
        cancelado: Cancelado,
        texto_do_dono: str = "",
        contaminacao: Contaminacao | None = None,
    ) -> ResultadoDeFerramenta:
        """Uma chamada do turno pelo caminho de sempre (PDP, Jev, objetivo, pergunta).
        `contaminacao` só vem do código (a abertura do navegador fechado, sem o método)."""
        if self.ferramentas is None:
            return ResultadoDeFerramenta(
                pedido.tool_id, "negado", motivo="nenhuma ferramenta está ligada nesta sessão"
            )
        fluxo = self.fluxo
        if fluxo is not None:
            return fluxo.chamar(
                self.ferramentas,
                pedido,
                pedido_do_dono=texto_do_dono,
                mensagens=self.conversa.turnos,
                cancelado=cancelado,
                confirmar=self.confirmar,
                session_id=self.session_id,
                proveniencia=self.proveniencia,
                contaminacao=contaminacao,
            )
        return self.ferramentas.executar(
            pedido.tool_id,
            pedido.args,
            cancelado=cancelado,
            confirmar=self.confirmar,
            session_id=self.session_id,
            proveniencia=self.proveniencia,
            contaminacao=contaminacao,
        )

    def _status(self, texto: str) -> None:
        """Entrega progresso à fila sem deixar uma falha dela derrubar o turno."""
        if self.ao_status is None:
            return
        try:
            self.ao_status(texto)
        except Exception:
            return

    def avisar(
        self,
        avisos: Sequence[AvisoLiberado],
        *,
        epoch: int,
        publicar: Publicar,
        cancelado: Cancelado = nunca_cancelado,
    ) -> Resposta:
        """Piso livre, sem mensagem do dono: só os avisos, sem chamar o motor (regra 12)."""
        comeco = time.monotonic()
        self._pendentes.clear()
        resposta = Resposta(
            response_id=f"r-{uuid7()}", turn_id=f"t-{uuid7()}", epoch=epoch, motor="avisos"
        )
        fatiador = FatiadorDeFala()
        if self._falar_avisos(avisos, resposta, publicar, comeco, cancelado) is None:
            for pedaco in fatiador.fechar():
                self._publicar(resposta, pedaco, publicar, comeco, ultimo=pedaco.corte is Corte.FIM)
        else:
            resposta.fim = MotivoDoFim.CANCELADO
        self._pendentes[resposta.response_id] = resposta
        return resposta

    def _falar_avisos(
        self,
        avisos: Sequence[AvisoLiberado],
        resposta: Resposta,
        publicar: Publicar,
        comeco: float,
        cancelado: Cancelado,
        crescer: Callable[[], None] = lambda: None,
    ) -> float | None:
        """Publica a frase de cada aviso; devolve o instante do cancelamento, se houve."""
        for aviso in avisos:
            if cancelado():
                return time.monotonic()
            frase = frase_do_aviso(aviso)
            resposta.gerado += frase + " "
            crescer()
            # Cada aviso é uma fala completa: seu residual pode ser curto, mas precisa sair
            # com o próprio notif_id antes do próximo aviso ou da resposta. Compartilhar o
            # buffer perderia a identidade de avisos menores que o piso normal de 14 palavras.
            fatiador = FatiadorDeFala()
            for pedaco in fatiador.alimentar(frase) + fatiador.fechar():
                if not pedaco.texto:
                    continue
                if cancelado():
                    return time.monotonic()
                self._publicar(
                    resposta, pedaco, publicar, comeco, ultimo=False, notif_ids=[aviso.notif_id]
                )
        return time.monotonic() if cancelado() else None

    def ouvido(
        self,
        response_id: str,
        texto_tocado: str,
        *,
        interrompida: bool,
        played_ms: int | None = None,
    ) -> None:
        """O que de fato tocou da resposta — só isso entra na conversa (regra 3, P4).

        Com histórico, o turno vai para o livro com o `played_ms` real: sem ele, o livro recusa.
        """
        resposta = self._pendentes.pop(response_id, None)
        if resposta is None:
            return  # resposta velha, já substituída por um turno novo do dono
        if interrompida:
            self._esquecer_pergunta_nao_ouvida(resposta, texto_tocado)
        if not (texto_tocado or interrompida):
            return
        lembrado = texto_tocado
        if resposta.so_na_tela and not interrompida:
            # O que passou do orçamento da fala o dono viu na tela e não ouviu: o modelo fica
            # sabendo, para não repetir nem achar que ficou por dizer.
            lembrado = f"{texto_tocado} [só na tela, não falado: {resposta.so_na_tela}]"
        self.conversa.turnos.append(Mensagem("jarvis", lembrado, interrompida))
        if self.livro is not None:
            self.livro.gravar_turno(
                session_id=self.id_da_conversa or self.session_id,
                papel="jarvis",
                texto=texto_tocado,
                trust="system",
                played_ms=played_ms,
                interrompida=interrompida,
            )

    def _esquecer_pergunta_nao_ouvida(self, resposta: Resposta, texto_tocado: str) -> None:
        """O dono cortou a fala antes do fim da pergunta: ela não foi feita, e um "sim" dito por
        cima não pode autorizar o que ele não ouviu. A pendência cai."""
        aberta = self.pendencias.valida()
        if aberta is None or self.pendencias.foi_ouvida(aberta.id):
            return  # respondida por cima (ADR-0048): o corte foi a resposta, não o descaso
        for resultado in resposta.ferramentas:
            if resultado.call_id == aberta.id and resultado.aviso not in texto_tocado:
                self.pendencias.cancelar()
                return

    def _publicar(
        self,
        resposta: Resposta,
        pedaco: PedacoDeFala,
        publicar: Publicar,
        comeco: float,
        *,
        ultimo: bool,
        notif_ids: Sequence[str] = (),
    ) -> None:
        payload: dict[str, Any] = {
            "response_id": resposta.response_id,
            "turn_id": resposta.turn_id,
            "epoch": resposta.epoch,
            "seq": len(resposta.publicados),
            "text": pedaco.texto,
            "boundary": str(pedaco.corte),
            "last": ultimo,
        }
        if notif_ids:
            payload["notif_ids"] = list(notif_ids)
        if ultimo:
            # Nunca `cancelado`: resposta cancelada não publica o último pedaço (regra 9).
            payload["end_reason"] = str(resposta.fim)
        if resposta.ms_ate_primeiro_pedaco is None and pedaco.texto:
            resposta.ms_ate_primeiro_pedaco = _ms_desde(comeco)
        resposta.publicados.append(payload)
        publicar(payload)


def _sem_navegador_aberto(pedido: PedidoDeTool, resultado: ResultadoDeFerramenta) -> bool:
    """A `browser.*` falhou porque nenhum navegador com a extensão do Jarvis está aberto."""
    return (
        pedido.tool_id.startswith("browser.")
        and resultado.status == "erro"
        and SEM_NAVEGADOR_ABERTO in resultado.motivo
    )


def _marcar_a_primeira_ferramenta(resposta: Resposta, comeco: float) -> None:
    if resposta.ms_ate_primeira_ferramenta is None:
        resposta.ms_ate_primeira_ferramenta = _ms_desde(comeco)


def _estado_final(resposta: Resposta) -> EstadoDoObjetivo:
    if resposta.fim is MotivoDoFim.CANCELADO:
        return EstadoDoObjetivo.CANCELADO
    if resposta.fim is not MotivoDoFim.CONCLUIDO or resposta.detalhe.startswith(
        "o motor pediu ferramenta"
    ):
        return EstadoDoObjetivo.FALHOU
    return EstadoDoObjetivo.CONCLUIDO


def _guardar_raciocinio(resposta: Resposta, texto: str, *, separado: bool = False) -> None:
    """Junta ao raciocínio do turno até o teto; o que passa é só contado. `separado` é um trecho
    novo (a narração retida), e não a continuação do stream de um bloco."""
    if separado and resposta.raciocinio and not resposta.raciocinio[-1].isspace():
        texto = " " + texto
    cabe = max(0, LIMITE_DO_RACIOCINIO - len(resposta.raciocinio))
    resposta.raciocinio += texto[:cabe]
    resposta.raciocinio_descartado += max(0, len(texto) - cabe)


def _dito_no_turno(resposta: Resposta) -> str:
    """Tudo o que já foi para a fala neste turno, sem os avisos da fila."""
    return " ".join(
        str(p["text"]) for p in resposta.publicados if p["text"] and not p.get("notif_ids")
    )


def _ja_dito(resposta: Resposta) -> str:
    """O que já foi para a fala neste turno, sem os avisos da fila (esses o prompt já conta)."""
    dito = _dito_no_turno(resposta)
    return dito if len(dito) <= LIMITE_DO_JA_DITO else "…" + dito[-LIMITE_DO_JA_DITO:]


def _tela(resposta: Resposta, mostrar: Mostrar | None) -> Callable[[], None]:
    """O que a tela mostra quando o texto da resposta cresce: tudo até agora, com espaço
    normalizado, e só quando mudou (delta só de espaço não redesenha a tela)."""
    visto = [""]

    def crescer() -> None:
        texto = " ".join(resposta.gerado.split())
        if mostrar is not None and texto and texto != visto[0]:
            visto[0] = texto
            mostrar(texto)

    return crescer


def envelope_do_pedaco(session_id: str, payload: dict[str, Any]) -> Envelope:
    """O `ResponseChunk` no envelope da §3.1, validado na borda como qualquer evento."""
    return validar(
        Envelope(
            session_id=session_id,
            epoch=int(payload["epoch"]),
            source="s2",
            trust=Trust.SYSTEM,
            priority=prioridade_canonica(Tipo.RESPONSE_CHUNK, payload),
            type=Tipo.RESPONSE_CHUNK,
            payload=payload,
        )
    )


def _ms_desde(comeco: float) -> float:
    return (time.monotonic() - comeco) * 1000.0
