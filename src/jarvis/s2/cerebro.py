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

import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from jarvis.barramento.contrato import prioridade_canonica, validar
from jarvis.barramento.envelope import Envelope, Tipo, Trust, uuid7
from jarvis.decisao.interface import ClassificadorDeDecisao
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
from jarvis.politica.atalho import Atalho
from jarvis.politica.memoria import TRUST_DO_DONO, AlcanceDeMemoria, Proveniencia, TurnoCorrente
from jarvis.politica.metodo import Escolha
from jarvis.politica.objetivo import EstadoDoObjetivo
from jarvis.politica.permissao import ModoDePermissao, comando_de_permissao
from jarvis.s2.avisos import AvisoLiberado, calado, nota_dos_eventos, pede_detalhe
from jarvis.s2.consumo import ConsumoDoTurno, Medicao, campos_da_medicao, medir, precos_do_motor
from jarvis.s2.entrega import FiltroDoJaDito
from jarvis.s2.fluxo_de_acao import FluxoDeAcao, frase_do_feito
from jarvis.s2.leitura_da_pagina import NOTA_DA_LEITURA, leitura_antes
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
from jarvis.s2.pendencias import INTERVALO_DA_ESPERA_S, Espera, RegistroDePendencias
from jarvis.s2.persona import sistema_do_jarvis
from jarvis.s2.portao import AutorizacoesExplicitas, PortaoDeAcao
from jarvis.s2.protocolo import LeitorDoProtocolo
from jarvis.s2.rascunho import textos_no_contexto
from jarvis.s2.receitas import receitas_do_turno
from jarvis.s2.recuperacao import nota_do_turno
from jarvis.s2.roteiro_do_navegador import (
    Contato,
    PedidoDeEnvio,
    pedido_de_envio,
)
from jarvis.s2.tarefa_do_pedido import MotorDoObjetivo, titulo_do_plano
from jarvis.s2.verdade import (
    NOTA_DE_SEGUIR,
    Afirmacao,
    FiltroDaVerdade,
    Relato,
    afirmacoes,
    frase_do_que_falta,
)
from jarvis.tarefas.gestor import (
    FORA_DA_ALLOWLIST,
    ChamarNaTarefa,
    PerguntarNoTeto,
    RespostaAoTeto,
    Tarefa,
    TarefaRecusada,
)
from jarvis.tela.guia import nota_da_tela
from jarvis.voz.interface import Cancelado, nunca_cancelado

MAXIMO_DE_PASSOS: Final = 50
"""Chamadas de ferramenta que um turno pode encadear antes de ter de responder; na tarefa de um
pedido, os passos de um bloco antes de perguntar ao dono se segue (ADR-0059)."""
PRAZO_DA_TAREFA_S: Final = 900.0
"""O tempo de um bloco da tarefa de um pedido. Não é o do turno (90 s): cinquenta passos, cada um
com uma rodada do motor, não cabem nele."""
PRAZO_DO_LACO_DE_FERRAMENTAS_S: Final = 90.0
"""Orçamento total do laço agêntico; inclui pensar e executar as ferramentas."""
# Nome preservado para quem importava o teto antigo. Agora cada rodada tem exatamente um passo:
# o resultado volta ao motor antes de ele poder propor o próximo.
MAXIMO_DE_RODADAS: Final = MAXIMO_DE_PASSOS
TURNOS_NO_CONTEXTO: Final = 12
"""Orçamento fixo de conversa no contexto (regra 5): os últimos turnos estáveis. O resumo do que
ficou para trás é trabalho de segundo plano, fora desta fatia."""
NOTA_DO_NAVEGADOR_FECHADO: Final = (
    "O navegador do dono está fechado (nenhum com a extensão do Jarvis). Você pode abri-lo: "
    "sites.open abre o navegador dele já na página; browser.launch abre o navegador, e o sistema "
    "espera a extensão conectar antes de devolver. Decida você; não mande o dono abrir."
)
NOTA_DO_EVENTO_DO_TURNO: Final = (
    "EVENTO DO SISTEMA (já aconteceu por causa do que o dono acabou de dizer; não é para fazer de "
    "novo): responda ao dono com as suas palavras, curto, sem markdown e sem citar ferramenta. O "
    "que aconteceu:"
)
NOTA_DA_PERGUNTA: Final = (
    "EVENTO DO SISTEMA (já aconteceu por causa do que o dono acabou de dizer; não é para fazer de "
    "novo): uma ação espera o sim do dono antes de rodar. Pergunte a ele, com as suas palavras e "
    "em uma frase, se pode fazer, e diga por quê se houver motivo — sem as palavras sim e não, "
    "sem markdown e sem citar ferramenta. O que aconteceu: a pergunta que o sistema montaria é"
)
NOTA_DO_LIMITE_DO_TURNO: Final = (
    "EVENTO DO SISTEMA (notificação do limite, não é fala do dono): o turno chegou ao teto —"
)
NOTA_DO_LIMITE_COM_SUBAGENTE: Final = (
    "O que já foi feito está nos resultados das ferramentas acima. Decida você: se ainda falta e "
    "vale seguir, diga ao dono em poucas palavras e proponha a próxima ferramenta — ela vai ao "
    "subagente, que continua fora do turno; se precisa do dono, pergunte; se não dá, explique o "
    "que ficou feito e o que não. Com as suas palavras, curto, sem markdown e sem citar ferramenta."
)
NOTA_DO_LIMITE_SEM_SUBAGENTE: Final = (
    "O que já foi feito está nos resultados das ferramentas acima, e não há mais passo neste "
    "turno. Decida você o que dizer ao dono: o que ficou feito, o que falta, ou uma pergunta. Com "
    "as suas palavras, curto, sem markdown e sem citar ferramenta."
)
CHAVE_DA_DELEGACAO: Final = "delegacao-claude-code"
"""A entrada do andamento dos parciais do Claude Code delegado (uma delegação por vez)."""
PASSOS_NO_ANDAMENTO: Final = 4
"""Os últimos passos de cada subagente que o Jarvis vê na nota do andamento (ADR-0070)."""
LIMITE_DO_RACIOCINIO: Final = 2000
"""Caracteres de raciocínio que um turno guarda e devolve ao motor (ADR-0031). O resto é contado
e descartado: o canal interno não pode crescer o prompt de cada rodada sem fim."""
LIMITE_DO_JA_DITO: Final = 300
"""Caracteres do que o dono já ouviu no turno que voltam ao motor (o fim, que é o mais novo)."""
"""O que o dono ouve quando o pedido vira tarefa e o motor não disse nada antes da ferramenta
(ADR-0038): curto, e a resposta de verdade vem quando a tarefa acabar."""


def nota_do_atalho(atalho: Atalho) -> str:
    """A dica do caminho rápido para o motor (ADR-0070): o que a regra acharia, como contexto."""
    argumentos = json.dumps(dict(atalho.args), ensure_ascii=False)
    return (
        f"DICA DO CÓDIGO (a regra «{atalho.regra}» reconheceu a fala; é sugestão, não ordem): este "
        f"pedido parece ser {atalho.tool_id} com {argumentos}. Use se for mesmo o que o dono "
        "pediu; se não, siga o seu caminho."
    )


FICAM_NO_TURNO: Final = frozenset(
    {
        "system.clock.now",
        "system.read.status",
        "system.machine.status",
        "system.volume.get",
        "media.player.status",
        "timer.alarm.list",
        "timer.alarm.set",
        "timer.alarm.cancel",
        "window.list",
        "window.focused",
        "clipboard.text.read",
        "notify.desktop.send",
        "tela.mostrar",
        "tela.ler",
        "tela.fechar",
    }
)
"""Com o subagente ligado (`delegar_em_tarefa`), toda execução — clicar, digitar, abrir app,
enviar, pesquisar, rodar comando — vai para ele desde o primeiro passo (ADR-0070, dono,
2026-11-15); o Jarvis fica livre para conversar e recebe o progresso e o resultado como eventos.
O que o Jarvis faz ele mesmo, no turno: ler o próprio estado (hora, volume, janelas), os
lembretes dele e a tela dele. Não é execução no computador do dono. A memória dele (`memoria.*`)
também fica; `tarefa.*`, `jarvis.*`, `vocabulario.*`, `modelo.*` e `acao.desfazer` nunca vão para
tarefa (`_delegavel`)."""


def fica_no_turno(tool_id: str) -> bool:
    """A ferramenta é do próprio Jarvis (consulta, memória, tela) e roda no turno (ADR-0070)."""
    return tool_id in FICAM_NO_TURNO or tool_id.startswith("memoria.")


ESPERA_DA_EXTENSAO_S: Final = 12.0
"""Quanto se espera a extensão conectar depois de o Jarvis abrir o navegador (o Brave frio leva
alguns segundos para carregar a extensão)."""
INTERVALO_DA_EXTENSAO_S: Final = 0.25
COBRANCAS_DO_OBJETIVO: Final = 2
"""Quantas vezes o turno cobra o motor que parou antes do objetivo (ADR-0066)."""
COBRANCAS_DO_PLANO: Final = 1
"""Quantas vezes o turno devolve a primeira ferramenta proposta sem plano (ADR-0071): depois
disso ela segue, e a trilha conta que o plano faltou."""
LIMITE_DO_PLANO: Final = 1200
"""O plano que vai à tarefa como objetivo: o começo do raciocínio antes da 1ª ferramenta."""
NOTA_DO_PLANO: Final = (
    "ENTENDA ANTES DE AGIR: você propôs uma ferramenta sem escrever o plano, e ela não rodou. "
    "Escreva primeiro, entre <<pensar>> e <</pensar>>, o que o dono quer (cada intenção "
    "separada; uma fala pode trazer duas, ou só guardar algo) e, para cada uma, a ferramenta e os "
    "valores que VOCÊ escolheu: o nome, o endereço ou o texto, nunca a frase dele copiada. A fala "
    "vem da voz e pode estar sem pontuação: separe as frases antes. Se ela der para ler de dois "
    "jeitos que levam a ações diferentes, não proponha nada: pergunte ao dono em uma frase. "
    "Depois proponha a ferramenta, se ainda for o caso."
)
"""A notificação ao motor quando a 1ª ferramenta veio sem plano (ADR-0071): ele decide de novo."""

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
    limite_do_turno: str = ""
    """O teto que o turno alcançou (prazo ou passos) e que foi ao motor como notificação, numa
    rodada final (a17, ADR-0070). Vazio = o turno acabou antes de qualquer teto."""
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
    consumo: ConsumoDoTurno = field(default_factory=ConsumoDoTurno)
    """Tokens, custo e chamadas ao motor do turno (ADR-0061): só números, para a trilha."""
    caladas: list[str] = field(default_factory=list)
    """Frases do motor que repetiam o que o dono já tinha ouvido neste turno (o aviso, a frase do
    código): foram à tela e não à voz (`jarvis.s2.entrega`, dono, 2026-10-25)."""
    sem_confirmacao: list[str] = field(default_factory=list)
    """Frases do motor que afirmavam o que nenhuma ferramenta confirmou, ou pediam permissão para o
    que o dono já pediu (`jarvis.s2.verdade`, ADR-0066): nem voz nem tela."""
    calado: bool = False
    """O turno de avisos em que o Jarvis decidiu não falar (ou o motor caiu): nada foi à voz, e
    os avisos ficam no card (ADR-0070)."""
    respondida: bool = False
    """O turno já respondeu ao dono (uma rodada sem ferramenta falou uma resposta): sem ação em
    andamento, nenhuma outra rodada escreve outra resposta ao mesmo pedido (ADR-0062, emenda de
    2026-11-15)."""
    cobrou_redacao: bool = False
    """A mensagem que ia ser digitada era a fala do dono copiada e o motor foi cobrado (ADR-0069
    §3): uma vez por turno."""
    leituras_forcadas: int = 0
    """Quantas vezes o código leu a página no lugar de uma ação proposta sem leitura (ADR-0069)."""
    cobrancas: int = 0
    """Quantas vezes o laço cobrou o motor a seguir até o objetivo, depois de um relato cortado."""
    plano: str = ""
    """O raciocínio do motor antes da 1ª ferramenta do pedido (ADR-0071): as intenções do dono e
    os valores que o Jarvis escolheu. É o objetivo da tarefa. Nunca vai à fala nem à tela."""
    plano_cobrado: int = 0
    """Quantas vezes a 1ª ferramenta veio sem plano e voltou ao motor (`NOTA_DO_PLANO`)."""

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
    prazo_da_tarefa_s: float = PRAZO_DA_TAREFA_S
    """Teto configurável de chamadas no encadeamento de ferramentas deste turno."""
    prazo_do_laco_de_ferramentas_s: float = PRAZO_DO_LACO_DE_FERRAMENTAS_S
    """Teto configurável, em segundos, para o encadeamento inteiro."""
    ao_status: AvisarStatus | None = None
    """Porta para a fila de avisos: status nunca é publicado por cima da fala em curso."""
    memorias_fixas: Callable[[str], str] | None = None
    """As memórias fixas do dono (ADR-0060, fatia C): da fala, o bloco do assunto ou vazio. Só o
    turno de mensagem, rede, contato ou serviço paga o bloco (orçamento da ADR-0047)."""
    classificador_de_receitas: ClassificadorDeDecisao | None = None
    """Quem escolhe a família das receitas quando as regras não reconhecem o assunto e o pedido tem
    verbo de ação (o Jev, ADR-0029; ADR-0047, emenda de 2026-10-30). `None` = só as regras."""
    ao_raciocinio: Callable[[str], None] | None = None
    """O canal de raciocínio na tela (ADR-0031): a linha de cada replanejamento da tarefa quando
    um passo falha (emenda de 2026-10-30 à ADR-0038). Só tela — nunca a voz nem a fila de avisos."""
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
    exigir_plano: bool = False
    """A primeira ferramenta do pedido só roda depois de um plano do motor (`<<pensar>>`, ADR-0071):
    sem ele, a proposta volta como notificação (`NOTA_DO_PLANO`), uma vez. O plano é o objetivo
    que vai à tarefa. O aplicativo liga; desligado, como antes (os testes do laço)."""
    delegar_em_tarefa: bool = False
    """Toda execução de um pedido vira uma **tarefa** do objetivo — o subagente — desde a primeira
    ferramenta (ADR-0038, ADR-0070): o turno acaba sem frase do código — o Jarvis segue ouvindo —,
    e ela itera pelo mesmo PDP, Jev e objetivo até cumprir, precisar do dono, chegar a um limite
    (que vira notificação ao Jarvis) ou ser cancelada. Só as consultas do próprio Jarvis
    (`FICAM_NO_TURNO`) rodam no turno. Precisa do gestor de tarefas no executor; o aplicativo
    liga. Desligado = o laço todo no turno (o que os testes do laço e o harness usam)."""
    caminho_rapido: bool = False
    """O comando simples vai à ferramenta pela regra do código, sem esperar o motor (dono,
    2026-10-21: «precisa ser muito rápido»; `jarvis.politica.atalho`). A chamada passa pelo mesmo
    PDP, Jev, objetivo e pergunta da proposta do modelo; pronta e certa, a frase é do código e o
    motor nem é chamado. O aplicativo liga; desligado, como antes (os testes do laço)."""
    ao_mudar_permissao: Callable[[ModoDePermissao], str] | None = None
    """Troca o modo de permissão (ADR-0066) quando a fala **do dono** manda («ativa o modo
    bypass»): lida pelo código antes do motor, nunca por ferramenta — página ou mensagem que diga
    «modo bypass» não chega aqui. Devolve a frase que o Jarvis diz. `None` = não troca pela voz."""
    contatos: Callable[[], Sequence[Contato]] | None = None
    """Os contatos das memórias fixas do dono, lidos na hora de delegar: o roteiro da tarefa de
    navegador resolve «minha mãe» por eles (ADR-0066). `None` = sem memórias (a suíte)."""
    ao_pedir_estilo: Callable[[str], str] | None = None
    """Troca o estilo do endpoint de voz (ADR-0068) quando a fala **inteira do dono** pede («fala
    mais calmo», «tom urgente»): lida pelo código antes do motor, pelo mesmo caminho do modo de
    permissão. Devolve o que aconteceu, como dado para o Jarvis responder (ADR-0070), ou vazio
    (não era pedido de estilo)."""
    _pendentes: dict[str, Resposta] = field(default_factory=dict)
    andamento: dict[str, tuple[str, list[str]]] = field(default_factory=dict)
    """O progresso de cada subagente no ar (ADR-0070): `tarefa_id → (pedido, últimos passos)`.
    Vai como nota a todo turno do Jarvis, para ele saber o que está acontecendo e decidir."""
    falas_de_aviso: dict[str, str] = field(default_factory=dict)
    """O que o Jarvis disse por cada aviso (ADR-0070): a fala dele é o eco a filtrar quando o
    aviso é uma pergunta que espera o sim do dono."""

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
        # O que aconteceu vai à fila como dado; o turno dos avisos é do Jarvis (ADR-0070).
        if sim and resultado.status == "ok" and aberta is not None and aberta.id == pendencia_id:
            self._status(
                f"(o dono confirmou no clique e «{aberta.pergunta.para_ouvir}» foi feito: "
                f"{frase_do_feito(aberta.pergunta, resultado)})"
            )
        elif sim and resultado.status not in ("ok", "despachado"):
            self._status(f"(o dono confirmou no clique, mas a ação falhou: {resultado.motivo})")
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
        tom: str = "",
    ) -> Resposta:
        """Responde a um turno estável do dono, publicando os pedaços enquanto o motor gera.

        `avisos` são os que a fila liberou junto com esta mensagem e que o `s2` decidiu falar
        (ADR-0025, regra 13, decisão do dono): vão **antes** da resposta, em pedaços marcados
        com `notif_ids`, e o motor fica sabendo que já foram ditos — informa, depois responde.

        `tom` é a linha do tom de voz do turno (`jarvis.voz.tom.Tom.linha`, ADR-0058), vazia no
        neutro: vai no fim do sistema, como as outras notas do turno, e só muda o jeito da
        resposta — nunca é pedido, nem «sim» a uma pergunta pendente (a leitura da resposta,
        abaixo, nem a recebe).
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
            if leitura.evento:
                return self._responder_ao_evento(
                    leitura.evento,
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
        troca = (
            comando_de_permissao(texto_do_dono)
            if self.ao_mudar_permissao is not None and trust in TRUST_DO_DONO
            else None
        )
        if troca is not None and self.ao_mudar_permissao is not None:
            return self._responder_ao_evento(
                self.ao_mudar_permissao(troca),
                epoch=epoch,
                turn_id=turn_id,
                publicar=publicar,
                cancelado=cancelado,
                comeco=comeco,
                ferramentas=[],
                mostrar=mostrar,
            )
        estilo = (
            self.ao_pedir_estilo(texto_do_dono)
            if self.ao_pedir_estilo is not None and trust in TRUST_DO_DONO
            else ""
        )
        if estilo:
            return self._responder_ao_evento(
                estilo,
                epoch=epoch,
                turn_id=turn_id,
                publicar=publicar,
                cancelado=cancelado,
                comeco=comeco,
                ferramentas=[],
                mostrar=mostrar,
            )
        memoria = None
        contexto = self.conversa.contexto()
        metodo = self.ferramentas.metodo if self.ferramentas is not None else None
        if metodo is not None and metodo.nota():
            # O roteador de método (ADR-0035): o caminho direto para este pedido, dito ao modelo.
            contexto = Contexto(
                sistema=f"{contexto.sistema}\n\n{metodo.nota()}", mensagens=contexto.mensagens
            )
        receitas = self._receitas(texto_do_dono, metodo)
        if receitas:
            # Ensinar as ferramentas (ADR-0047, emenda de 2026-10-30): a receita da família do
            # assunto deste pedido, só neste turno — o de conversa custa o mesmo de antes.
            contexto = Contexto(
                sistema=f"{contexto.sistema}\n\n{receitas}", mensagens=contexto.mensagens
            )
        fixas = self._memorias_fixas(texto_do_dono)
        if fixas:
            contexto = Contexto(
                sistema=f"{contexto.sistema}\n\n{fixas}", mensagens=contexto.mensagens
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
        if tom:
            contexto = Contexto(
                sistema=f"{contexto.sistema}\n\n{tom}", mensagens=contexto.mensagens
            )
        andamento = self.nota_do_andamento()
        if andamento:
            contexto = Contexto(
                sistema=f"{contexto.sistema}\n\n{andamento}", mensagens=contexto.mensagens
            )
        if avisos:
            # Os avisos que chegaram com a mensagem são eventos para o Jarvis (ADR-0070): ele decide
            # se e como mencioná-los na resposta; o código não fala nenhum antes dele.
            contexto = Contexto(
                sistema=f"{contexto.sistema}\n\n{nota_dos_eventos(avisos, com_mensagem=True)}",
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
        visto_cancelamento = time.monotonic() if cancelado() else None
        catalogo = self.ferramentas.catalogo_para_o_modelo() if self.ferramentas else ()
        # A tela mais nova que uma ferramenta deste turno capturou (ADR-0032): vai só ao motor que
        # a aceita, e só neste turno.
        imagens: tuple[Imagem, ...] = ()
        limite_do_laco = self.relogio() + self.prazo_do_laco_de_ferramentas_s

        def prazo_esgotado() -> bool:
            return self.relogio() >= limite_do_laco

        def cancelado_no_laco() -> bool:
            return cancelado() or prazo_esgotado()

        def cortar_por_prazo() -> str:
            resposta.fim = MotivoDoFim.PRAZO
            resposta.detalhe = (
                f"o laço de ferramentas passou de {self.prazo_do_laco_de_ferramentas_s:.0f} s"
            )
            return (
                f"o seu turno passou do prazo de {self.prazo_do_laco_de_ferramentas_s:.0f} s "
                "antes de você responder ao dono"
            )

        limite = ""  # a notificação do teto do turno, quando ele chega (a17, ADR-0070)

        # O caminho rápido (dono, 2026-10-21) virou DICA (ADR-0070): a regra do código reconhece o
        # comando simples e diz ao motor qual ferramenta e quais argumentos ela acharia — como
        # contexto. Ela não executa nem fala: quem decide o passo, e o que dizer, é o Jarvis.
        pular_o_motor = False
        atalho = self._atalho(texto_do_dono) if visto_cancelamento is None else None
        if atalho is not None:
            resposta.atalho = str(atalho.regra)
            contexto = Contexto(
                sistema=f"{contexto.sistema}\n\n{nota_do_atalho(atalho)}",
                mensagens=contexto.mensagens,
            )
            if self.ferramentas is not None and self.ferramentas.trilha is not None:
                self.ferramentas.trilha.evento(
                    "atalho",
                    regra=str(atalho.regra),
                    tool_id=atalho.tool_id,
                    status="dica",
                    completo=atalho.completo,
                )
        resposta.motor_chamado = not pular_o_motor
        falta = ""  # o evento do fim quando o motor parou afirmando sem confirmar (ADR-0066/0070)
        passos = range(0) if pular_o_motor else range(1, self.maximo_de_passos + 1)
        for passo in passos:
            if visto_cancelamento is not None:
                break
            if cancelado_no_laco():
                if cancelado():
                    visto_cancelamento = time.monotonic()
                else:
                    limite = cortar_por_prazo()
                break
            # O objetivo que precisa conferir (navegador, entrada virtual): o turno fez o primeiro
            # passo; ler, seguir e conferir antes de dizer «abri» é da tarefa — o turno não afirma
            # o que ninguém conferiu (ADR-0038, ADR-0046).
            if (
                self._continua_na_tarefa(resposta)
                and not cancelado()
                and self._delegar(
                    None, contexto, texto_do_dono, resposta, fatiador, publicar, comeco, crescer
                )
                is None
            ):
                break
            # A memória de trabalho do turno (ADR-0034): o passo mais novo inteiro, os antigos
            # inteiros enquanto couberem no orçamento e, depois, podados.
            textos, podados = textos_no_contexto(resposta.ferramentas)
            resposta.resultados_podados = max(resposta.resultados_podados, podados)
            # O passo do turno que falhou volta ao motor como erro estruturado, com a instrução de
            # replanejar por outro caminho (emenda de 2026-10-30 à ADR-0038).
            replanejar = (
                nota_do_turno(resposta.ferramentas[-1], (str(f["id"]) for f in catalogo))
                if resposta.ferramentas
                else ""
            )
            da_vez = Contexto(
                sistema=f"{contexto.sistema}\n\n{replanejar}" if replanejar else contexto.sistema,
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
                if resposta.ferramentas or resposta.cobrancas or resposta.respondida
                else None
            )
            # O relato verdadeiro (ADR-0066): frase que afirma o que nenhuma ferramenta confirmou,
            # ou que pede permissão para o que o dono já pediu, não sai — nem na narração do
            # primeiro passo, que era onde o «abri o contato» do bug do dono escapava.
            verdade = (
                FiltroDaVerdade(lambda: resposta.ferramentas)
                if self.ferramentas is not None
                else None
            )
            gerado_antes = resposta.gerado
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
                verdade=verdade,
            )
            if prazo_esgotado() and not cancelado():
                visto_cancelamento = None
                limite = cortar_por_prazo()
                break
            if not pedidos and _respondeu(gerado_antes, resposta.gerado):
                # Respondeu ao dono (ADR-0062, emenda de 2026-11-15): sem ação em andamento (nenhuma
                # ferramenta no turno), este estímulo está respondido — nada de outra rodada que
                # escreva outra resposta ao mesmo pedido. Com ação no meio, o objetivo pendente
                # ainda é cobrado (ADR-0066), e o filtro do já dito cala o que repetir.
                resposta.respondida = True
            if (
                not pedidos
                and verdade is not None
                and verdade.cortadas
                and visto_cancelamento is None
                and not (resposta.respondida and not resposta.ferramentas)
                and resposta.fim is MotivoDoFim.CONCLUIDO
                and resposta.cobrancas < COBRANCAS_DO_OBJETIVO
                and passo < self.maximo_de_passos
                and not cancelado_no_laco()
            ):
                # Parou antes do objetivo (afirmou sem confirmar, ou perguntou «quer que eu
                # mande?»): o motor é cobrado e segue (ADR-0038: objetivo pendente não encerra).
                resposta.cobrancas += 1
                contexto = Contexto(
                    sistema=f"{contexto.sistema}\n\n{NOTA_DE_SEGUIR}", mensagens=contexto.mensagens
                )
                continue
            if (
                not pedidos
                and verdade is not None
                and verdade.cortadas
                and visto_cancelamento is None
                and not (
                    resposta.respondida
                    and not resposta.ferramentas
                    and _so_pediu_permissao(verdade.cortadas)
                )
            ):
                # Respondida e só cortou a oferta do fim («quer que eu fale mais?»): não há o que
                # faltar — a frase do código seria outra resposta ao mesmo pedido.
                cortadas = tuple(verdade.cortadas)
                falta = (
                    "estas frases suas não foram ditas, porque nenhuma ferramenta as confirmou: "
                    f"«{' '.join(cortadas)}». Situação: "
                    f"{frase_do_que_falta(Relato('', cortadas, verdade.perguntou))}"
                )
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
            if self._falta_o_plano(resposta):
                # Entender antes de agir (ADR-0071): a 1ª ferramenta sem plano não roda; o motor
                # recebe a notificação e decide de novo — planejar e propor, ou perguntar.
                resposta.plano_cobrado += 1
                contexto = Contexto(
                    sistema=f"{contexto.sistema}\n\n{NOTA_DO_PLANO}", mensagens=contexto.mensagens
                )
                continue
            # Ler a página antes de agir nela, e reler depois do erro (ADR-0069 §2): sem leitura
            # que valha, o passo é a inspeção e o motor decide de novo com o mapa na mão.
            ler_antes = leitura_antes(
                pedido,
                ((r.tool_id, r.status) for r in resposta.ferramentas),
                (str(f["id"]) for f in catalogo),
                forcadas=resposta.leituras_forcadas,
            )
            if ler_antes is not None:
                resposta.leituras_forcadas += 1
                pedido = ler_antes
                if NOTA_DA_LEITURA not in contexto.sistema:
                    contexto = Contexto(
                        sistema=f"{contexto.sistema}\n\n{NOTA_DA_LEITURA}",
                        mensagens=contexto.mensagens,
                    )
            _marcar_a_primeira_ferramenta(resposta, comeco)
            if self._vai_para_tarefa(pedido) and not cancelado():
                # Execução vai ao subagente (ADR-0070): o turno acaba, a conversa segue.
                recusa = self._delegar(
                    pedido, contexto, texto_do_dono, resposta, fatiador, publicar, comeco, crescer
                )
                if recusa is None:
                    break
                resposta.ferramentas.append(recusa)  # o motor decide o que fazer com a recusa
                continue
            if cancelado_no_laco():
                if cancelado():
                    visto_cancelamento = time.monotonic()
                else:
                    limite = cortar_por_prazo()
                break
            resultado = self._chamar(pedido, cancelado_no_laco, texto_do_dono)
            resposta.ferramentas.append(resultado)
            # O navegador fechado (ADR-0070): o código não o abre sozinho — o motor recebe o fato
            # e o caminho, e decide (sites.open já na página, ou browser.launch). Abrir pelo motor
            # espera a extensão conectar, como parte da própria ferramenta.
            self._depois_de_abrir_o_navegador(pedido, resultado)
            if _sem_navegador_aberto(pedido, resultado):
                contexto = Contexto(
                    sistema=f"{contexto.sistema}\n\n{NOTA_DO_NAVEGADOR_FECHADO}",
                    mensagens=contexto.mensagens,
                )
            if resultado.anexos and aceita_imagem(self.motor):
                imagens = resultado.anexos
            # Sem status entre passos (dono, 2026-10-20, ADR-0031): ele não acompanha passo a
            # passo. O aviso de uma moderada é resultado (o que mudou e se desfaz); o passo de
            # navegação vem sem aviso (`aviso_silencioso` no manifesto).
            if resultado.status == "pendente":
                # A ação espera o sim do dono: quem pergunta é o Jarvis, com as palavras dele
                # (ADR-0070); o código guarda a pendência e lê a resposta. É a última coisa do
                # turno: o laço de voz fica livre para o "sim".
                self._perguntar_ao_dono(resultado, resposta, fatiador, publicar, comeco, crescer)
                break
            if resultado.aviso:
                # Tool moderada: o aviso é DADO para o motor (ADR-0070), que conta ao dono com as
                # palavras dele na próxima rodada — o código não o fala.
                contexto = Contexto(
                    sistema=f"{contexto.sistema}\n\nO que a ferramenta registrou (o dono ainda não "
                    f"ouviu): «{resultado.aviso}»",
                    mensagens=contexto.mensagens,
                )
            # Sem frase do código depois da ação e sem o código encerrar o turno (ADR-0070): o
            # motor vê o resultado na próxima rodada e decide se acabou e o que dizer.
            if prazo_esgotado() and not cancelado():
                limite = cortar_por_prazo()
                break
            if cancelado():
                visto_cancelamento = time.monotonic()
        else:
            if not pular_o_motor:
                resposta.detalhe = (
                    f"o motor pediu ferramenta {self.maximo_de_passos} vezes sem responder"
                )
                limite = (
                    f"você pediu {self.maximo_de_passos} ferramentas neste turno, o teto do turno, "
                    "sem responder ao dono"
                )
        if limite and visto_cancelamento is None and not cancelado() and not resposta.tarefa_id:
            # O turno chegou ao teto (prazo ou passos) antes de responder (a17, ADR-0070): o código
            # não o corta calado nem fala por ele — o Jarvis recebe a notificação com o estado e
            # decide numa rodada final: seguir pelo subagente, perguntar ao dono ou explicar.
            visto_cancelamento = self._rodada_do_limite(
                limite,
                contexto,
                texto_do_dono,
                modo,
                cancelado,
                fatiador,
                resposta,
                publicar,
                comeco,
                crescer,
                orcamento,
            )
        if visto_cancelamento is None and cancelado():
            visto_cancelamento = time.monotonic()
        if falta and visto_cancelamento is None and not cancelado():
            # O relato que não se confirmou não foi dito: o motor recebe o fato como evento e diz
            # ao dono o que falta, com as palavras dele (ADR-0070), numa rodada sem ferramentas.
            textos, _podados = textos_no_contexto(resposta.ferramentas)
            final = Contexto(
                sistema=f"{contexto.sistema}\n\n{NOTA_DO_EVENTO_DO_TURNO} {falta}",
                mensagens=(*contexto.mensagens, *(Mensagem("ferramenta", t) for t in textos)),
                raciocinio=resposta.raciocinio,
                ja_dito=_ja_dito(resposta),
            )
            _pedidos, visto_cancelamento = self._rodada(
                final,
                modo,
                cancelado,
                fatiador,
                resposta,
                publicar,
                comeco,
                crescer,
                segurar=True,
                orcamento=orcamento,
                verdade=FiltroDaVerdade(lambda: resposta.ferramentas),
            )
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

    def _rodada_do_limite(
        self,
        limite: str,
        contexto: Contexto,
        texto_do_dono: str,
        modo: Modo,
        cancelado: Cancelado,
        fatiador: FatiadorDeFala,
        resposta: Resposta,
        publicar: Publicar,
        comeco: float,
        crescer: Callable[[], None],
        orcamento: OrcamentoDaFala,
    ) -> float | None:
        """A rodada final do turno que chegou ao teto (a17, ADR-0070). O motor recebe o limite e o
        estado (os resultados do turno) e decide: propor a próxima ferramenta (com o subagente
        ligado, ela vai a ele e o trabalho segue fora do turno), perguntar ao dono ou explicar o
        que ficou feito. Nenhuma frase é do código. Devolve o instante do cancelamento, se houve."""
        continuar = (
            self.ferramentas is not None
            and self.delegar_em_tarefa
            and (self.ferramentas.tarefas is not None)
        )
        textos, _podados = textos_no_contexto(resposta.ferramentas)
        nota = f"{NOTA_DO_LIMITE_DO_TURNO} {limite}. " + (
            NOTA_DO_LIMITE_COM_SUBAGENTE if continuar else NOTA_DO_LIMITE_SEM_SUBAGENTE
        )
        catalogo = (
            self.ferramentas.catalogo_para_o_modelo()
            if continuar and self.ferramentas is not None
            else ()
        )
        final = Contexto(
            sistema=f"{contexto.sistema}\n\n{nota}",
            mensagens=(*contexto.mensagens, *(Mensagem("ferramenta", t) for t in textos)),
            ferramentas=catalogo,
            raciocinio=resposta.raciocinio,
            ja_dito=_ja_dito(resposta),
        )
        gerado_antes = resposta.gerado
        fim_antes, detalhe_antes = resposta.fim, resposta.detalhe
        resposta.fim = MotivoDoFim.CONCLUIDO
        pedidos, visto = self._rodada(
            final,
            modo,
            cancelado,
            fatiador,
            resposta,
            publicar,
            comeco,
            crescer,
            # O que ele diz antes de propor o passo é a fala dele ao dono («continuo em segundo
            # plano»), não narração de passo: não fica retido. O que repete o já dito vai à tela.
            segurar=False,
            orcamento=orcamento,
            filtro=FiltroDoJaDito(
                ditos=[dito] if (dito := _dito_no_turno(resposta)) else [],
                ids=self._ids_das_ferramentas(),
            ),
            verdade=FiltroDaVerdade(lambda: resposta.ferramentas)
            if self.ferramentas is not None
            else None,
        )
        resposta.limite_do_turno = limite
        if visto is not None or resposta.fim is not MotivoDoFim.CONCLUIDO:
            if resposta.fim is MotivoDoFim.CONCLUIDO:
                resposta.fim, resposta.detalhe = fim_antes, detalhe_antes
            return visto
        if pedidos and continuar and self._delegavel(pedidos[0]) and not cancelado():
            # Seguir: a próxima ferramenta que ele escolheu vai ao subagente, com o estado do turno.
            for pedaco in fatiador.descarregar():
                self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
            recusa = self._delegar(
                pedidos[0], contexto, texto_do_dono, resposta, fatiador, publicar, comeco, crescer
            )
            if recusa is None:
                return None
            resposta.ferramentas.append(recusa)
            textos, _podados = textos_no_contexto(resposta.ferramentas)
            sem_saida = Contexto(
                sistema=f"{contexto.sistema}\n\n{NOTA_DO_EVENTO_DO_TURNO} {limite}; e o subagente "
                f"não pôde assumir agora ({recusa.motivo}).",
                mensagens=(*contexto.mensagens, *(Mensagem("ferramenta", t) for t in textos)),
                raciocinio=resposta.raciocinio,
                ja_dito=_ja_dito(resposta),
            )
            _pedidos, visto = self._rodada(
                sem_saida,
                modo,
                cancelado,
                fatiador,
                resposta,
                publicar,
                comeco,
                crescer,
                segurar=True,
                orcamento=orcamento,
            )
            return visto
        if not _respondeu(gerado_antes, resposta.gerado):
            # Nem respondeu nem seguiu: o turno fica como estava (a tela diz o motivo do corte).
            resposta.fim, resposta.detalhe = fim_antes, detalhe_antes
        return None

    def _nota_da_tela(self, texto_do_dono: str, anteriores: Sequence[Mensagem]) -> str:
        """A nota da tela deste turno (`jarvis.tela.guia`), só quando as `tela.*` existem (a
        janela está aberta)."""
        executor = self.ferramentas
        porta = executor.portas().tela if executor is not None else None
        if porta is None:
            return ""
        ultima = next((m.texto for m in reversed(anteriores) if m.papel == "jarvis"), "")
        return nota_da_tela(texto_do_dono, ultima, porta.abertas())

    def _depois_de_abrir_o_navegador(
        self, pedido: PedidoDeTool, resultado: ResultadoDeFerramenta
    ) -> None:
        """O motor abriu o navegador (`browser.launch` ok): a ferramenta só se dá por acabada com a
        extensão conectada (até `ESPERA_DA_EXTENSAO_S`), para o próximo passo dele achar a ponte."""
        if pedido.tool_id == "browser.launch" and resultado.status == "ok":
            self._esperar_a_extensao()

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

    def _memorias_fixas(self, texto_do_dono: str) -> str:
        """O bloco das memórias fixas deste turno. Arquivo quebrado ou ilegível não derruba o
        turno: o turno segue sem o bloco (a aba «redes sociais» diz o erro ao dono)."""
        if self.memorias_fixas is None or not texto_do_dono.strip():
            return ""
        try:
            return self.memorias_fixas(texto_do_dono)
        except Exception:
            return ""

    def _receitas(self, texto_do_dono: str, metodo: Escolha | None) -> str:
        """As receitas do assunto deste pedido, com as ferramentas que estão ligadas agora."""
        executor = self.ferramentas
        if executor is None or not texto_do_dono.strip():
            return ""
        try:
            ligadas = [str(f["id"]) for f in executor.catalogo_para_o_modelo()]
        except Exception:  # sem catálogo, sem receita: o turno segue como antes
            return ""
        return receitas_do_turno(
            texto_do_dono, metodo, ligadas, classificador=self.classificador_de_receitas
        )

    def _ids_das_ferramentas(self) -> frozenset[str]:
        return (
            frozenset(self.ferramentas.manifestos) if self.ferramentas is not None else frozenset()
        )

    def _pode(self, tool_id: str) -> bool:
        """A ferramenta existe nesta sessão (o método do pedido é só dica, ADR-0070)."""
        executor = self.ferramentas
        return executor is not None and executor.disponivel(tool_id)

    def _atalho(self, texto_do_dono: str) -> Atalho | None:
        if not self.caminho_rapido or self.ferramentas is None:
            return None
        return self.ferramentas.atalho(texto_do_dono)

    def _envio_do_pedido(self, texto_do_dono: str) -> PedidoDeEnvio | None:
        """O pedido de envio na fala do dono («manda pra X que …»), com os contatos das memórias."""
        contatos = tuple(self.contatos()) if self.contatos is not None else ()
        return pedido_de_envio(texto_do_dono, contatos)

    def _delegavel(self, pedido: PedidoDeTool) -> bool:
        """A proposta pode ir para a tarefa do pedido? `tarefa.*` e `acao.desfazer` não rodam em
        tarefa (profundidade 1) e são rápidas; a ferramenta que não existe aqui, a malformada e a
        que o método do pedido tirou são recusadas na hora, no turno, para o motor se corrigir."""
        executor = self.ferramentas
        if not self.delegar_em_tarefa or executor is None or executor.tarefas is None:
            return False
        return not pedido.tool_id.startswith(FORA_DA_ALLOWLIST) and executor.disponivel(
            pedido.tool_id
        )

    def _vai_para_tarefa(self, pedido: PedidoDeTool) -> bool:
        """A proposta vai para a tarefa, ou roda no turno? (ADR-0070, dono, 2026-11-15)

        Execução vai ao subagente desde o primeiro passo: o turno do Jarvis só conversa, consulta
        o estado dele (`FICAM_NO_TURNO`) e delega. Não há mais o meio-termo de rodar as primeiras
        ferramentas no turno (`passos_no_turno`, ADR-0046): só existia nos testes."""
        return self._delegavel(pedido) and not fica_no_turno(pedido.tool_id)

    def _lembrancas_do_objetivo(self, plano: str) -> str:
        """O que o dono guardou por voz (o livro) e serve ao objetivo FORMULADO (ADR-0071): a
        busca é pelo plano — «abrir a conversa da mãe» acha «o contato da mãe se chama Mãe» —, com
        a mesma regra da memória do turno (D20). A memória degrada; a delegação não cai junto."""
        if self.livro is None or not plano.strip():
            return ""
        return consultar(
            self.livro,
            plano,
            onde=self.motor.onde,
            motor=self.motor.nome,
            alcance=self.alcance_de_memoria,
        ).bloco()

    def _falta_o_plano(self, resposta: Resposta) -> bool:
        """A 1ª ferramenta do pedido chegou sem plano e ainda cabe devolvê-la (ADR-0071)?"""
        return (
            self.exigir_plano
            and not resposta.ferramentas
            and not resposta.plano.strip()
            and resposta.plano_cobrado < COBRANCAS_DO_PLANO
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
    ) -> ResultadoDeFerramenta | None:
        """Cria a tarefa do pedido (o subagente). O que a tarefa leva é do **turno em que o pedido
        chegou**: o objetivo, o método, a contaminação, a autorização explícita (a fala dele, com o
        mesmo prazo), a conversa e a proveniência — o turno seguinte não mexe nela. O código não
        fala nada ao delegar (ADR-0070): o que o dono ouve é o que o motor disse antes de propor.
        Recusada (o teto de tarefas), devolve o erro, que volta ao motor como resultado."""
        executor = self.ferramentas
        assert executor is not None and executor.tarefas is not None
        marca = Contaminacao(executor.turno.valor, executor.objetivo, executor.metodo)
        autorizacoes = AutorizacoesExplicitas(
            prazo_s=self.autorizacoes.prazo_s, relogio=self.autorizacoes.relogio
        )
        autorizacoes.novo_turno(texto_do_dono)
        motor = MotorDoObjetivo(
            motor=self.motor,
            contexto=contexto,
            catalogo=executor.catalogo_para_o_modelo,
            primeiro=pedido,
            feitos_antes=tuple(resposta.ferramentas),
            raciocinio=resposta.raciocinio,
            ja_dito=resposta.gerado.strip()[-LIMITE_DO_JA_DITO:],
            ids=frozenset(executor.manifestos),
            limite_do_raciocinio=LIMITE_DO_RACIOCINIO,
            na_tela=self.ao_raciocinio,
            ao_medir=lambda medicao: self._anotar_consumo(None, medicao, "tarefa"),
            contatos=tuple(self.contatos()) if self.contatos is not None else (),
            # O objetivo FORMULADO (ADR-0071): o plano do Jarvis, não a fala crua do dono — essa
            # fica na conversa e no objetivo da política (escopo, guarda), como autorização.
            plano=resposta.plano.strip(),
            lembrancas=self._lembrancas_do_objetivo(resposta.plano),
        )
        try:
            tarefa = executor.tarefas.iniciar_objetivo(
                titulo_do_plano(resposta.plano)
                or (marca.objetivo.pedido if marca.objetivo is not None else texto_do_dono),
                motor,
                contaminacao=marca,
                chamar=self._chamada_da_tarefa(
                    marca, autorizacoes, texto_do_dono, tuple(self.conversa.turnos)
                ),
                prazo_s=self.prazo_da_tarefa_s,
                maximo_de_passos=max(1, self.maximo_de_passos - len(resposta.ferramentas)),
                bloco_de_passos=self.maximo_de_passos,
                no_teto=self._pergunta_do_teto(marca),
                feitos_antes=tuple(resposta.ferramentas),
                # O que o dono já ouviu deste pedido (dono, 2026-10-25): o fim da tarefa não repete.
                ja_dito=_dito_no_turno(resposta).strip(),
                turno=resposta.turn_id,
            )
        except TarefaRecusada as erro:
            return ResultadoDeFerramenta(
                pedido.tool_id if pedido is not None else "tarefa.iniciar",
                "erro",
                motivo=f"não deu para passar ao subagente agora: {erro}",
                causa="tarefas_ocupadas",
            )
        resposta.tarefa_id = tarefa.id
        return None

    def _pergunta_do_teto(self, marca: Contaminacao) -> PerguntarNoTeto:
        """A pergunta do teto da tarefa de um pedido (ADR-0059): a mesma pendência das outras
        perguntas da tarefa, dita em voz e na faixa, com a conversa livre."""
        executor = self.ferramentas
        assert executor is not None and executor.tarefas is not None
        gestor = executor.tarefas
        pendencias = self.pendencias

        def perguntar(tarefa: Tarefa, pergunta: Confirmacao) -> RespostaAoTeto:
            identificador = f"pergunta-{pergunta.id}"

            def na_voz(aberta: Confirmacao) -> None:
                gestor.avisar(tarefa, identificador, "precisa_decisao", aberta.pergunta_falada)

            espera = Espera()
            gestor.esperando_o_dono(tarefa, True)
            limite = time.monotonic() + pergunta.prazo_s
            try:
                while True:
                    resposta = pendencias.esperar(
                        pergunta,
                        contaminado=marca.valor,
                        cancelado=tarefa.cancelada.is_set,
                        anunciar=na_voz,
                        espera=espera,
                    )
                    if resposta is not None:
                        break
                    # Outra pergunta está aberta, e nada a substitui: esta espera a vez dela, em
                    # vez de jogar fora o trabalho porque o dono estava respondendo a outra coisa.
                    if tarefa.cancelada.wait(INTERVALO_DA_ESPERA_S) or time.monotonic() > limite:
                        return RespostaAoTeto.PARAR
            finally:
                gestor.esperando_o_dono(tarefa, False)
                gestor.retirar_aviso(tarefa, identificador)
            if not resposta or tarefa.cancelada.is_set():
                return RespostaAoTeto.PARAR
            return (
                RespostaAoTeto.ATE_TERMINAR if espera.ate_terminar else RespostaAoTeto.MAIS_UM_BLOCO
            )

        return perguntar

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
                # O navegador fechado: o motor da tarefa recebe o erro e os caminhos e decide
                # (ADR-0070); o código só espera a extensão quando ele mesmo abriu o navegador.
                self._depois_de_abrir_o_navegador(pedido, resultado)
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

    def _perguntar_ao_dono(
        self,
        resultado: ResultadoDeFerramenta,
        resposta: Resposta,
        fatiador: FatiadorDeFala,
        publicar: Publicar,
        comeco: float,
        crescer: Callable[[], None],
    ) -> None:
        """A pergunta de uma pendência, escrita pelo motor (ADR-0070). A fala dele vira o eco a
        filtrar quando o dono responder (`falas_de_aviso`). Motor que cai: nada na voz — a faixa
        da janela mostra a pergunta e o clique responde."""
        base = self.conversa.contexto()
        contexto = Contexto(
            sistema=f"{base.sistema}\n\n{NOTA_DA_PERGUNTA} «{resultado.aviso}»",
            mensagens=base.mensagens,
        )
        texto = self._texto_sem_ferramentas(contexto, resposta, lambda: False)
        if not texto:
            return
        aberta = self.pendencias.valida()
        if aberta is not None:
            self.falas_de_aviso[f"pergunta-{aberta.id}"] = texto
        resposta.gerado += texto + " "
        crescer()
        for pedaco in fatiador.alimentar(texto + " ") + fatiador.descarregar():
            self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)

    def _responder_ao_evento(
        self,
        evento: str,
        *,
        epoch: int,
        turn_id: str,
        publicar: Publicar,
        cancelado: Cancelado,
        comeco: float,
        ferramentas: list[ResultadoDeFerramenta],
        mostrar: Mostrar | None = None,
    ) -> Resposta:
        """O que a fala do dono já fez (a pendência resolvida, o modo ou o estilo trocado) chega ao
        Jarvis como EVENTO, e a resposta é dele (ADR-0070): uma rodada do motor sem ferramentas — o
        código não escreve a fala, e o motor não tem como propor a mesma ação de novo."""
        resposta = Resposta(
            response_id=f"r-{uuid7()}",
            turn_id=turn_id or f"t-{uuid7()}",
            epoch=epoch,
            motor=self.motor.nome,
            ferramentas=ferramentas,
            ms_ate_contexto=_ms_desde(comeco),
        )
        base = self.conversa.contexto()
        contexto = Contexto(
            sistema=f"{base.sistema}\n\n{NOTA_DO_EVENTO_DO_TURNO} {evento}",
            mensagens=base.mensagens,
        )
        texto = self._texto_sem_ferramentas(contexto, resposta, cancelado)
        if cancelado():
            resposta.fim = MotivoDoFim.CANCELADO
            return resposta
        if not texto:
            return resposta  # o motor caiu: nada na voz (o card e a tela mostram o estado)
        resposta.gerado = texto
        _tela(resposta, mostrar)()
        orcamento = OrcamentoDaFala()
        fatiador = FatiadorDeFala()
        for pedaco in fatiador.alimentar(orcamento.passar(texto) + orcamento.fechar()):
            if cancelado():
                resposta.fim = MotivoDoFim.CANCELADO
                return resposta
            self._publicar(resposta, pedaco, publicar, comeco, ultimo=False)
        resposta.so_na_tela = orcamento.so_na_tela
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
        verdade: FiltroDaVerdade | None = None,
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
        deltas = medir(
            self.motor.gerar(contexto, modo, cancelado),
            caracteres_entrada=lambda: len(contexto.como_texto()),
            precos=lambda: precos_do_motor(self.motor),
            ao_medir=lambda medicao: self._anotar_consumo(resposta.consumo, medicao, "turno"),
        )

        def falar(texto: str) -> bool:
            """Tela e fala; devolve se o cancelamento chegou no meio. A tela recebe tudo já (e
            perde a frase que o relato verdadeiro cortou, ADR-0066); a voz, frase a frase, o que
            não afirma sem confirmação, traz algo novo e cabe no orçamento."""
            resposta.gerado += texto
            crescer()  # a tela, já: o lote de fala pode levar 14 palavras para fechar
            if verdade is not None:
                texto = verdade.passar(texto)
                tirar_da_tela()
                if not texto:
                    return cancelado()
            return falar_na_voz(texto)

        def falar_na_voz(texto: str) -> bool:
            return dizer(filtro.passar(texto) if filtro is not None else texto)

        tiradas = 0

        def tirar_da_tela() -> None:
            """A frase cortada sai também da tela (o relato verdadeiro vale para os dois)."""
            nonlocal tiradas
            if verdade is None:
                return
            for frase in verdade.cortadas[tiradas:]:
                corpo = " ".join(resposta.gerado.split())
                if frase in corpo:
                    resposta.gerado = _sem_a_frase(resposta.gerado, frase)
                    crescer()
            tiradas = len(verdade.cortadas)

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
                if not pedidos and not resposta.ferramentas:
                    # O plano: o que o motor pensou antes da 1ª proposta do pedido (ADR-0071).
                    cabe = max(0, LIMITE_DO_PLANO - len(resposta.plano))
                    resposta.plano += delta.texto[:cabe]
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
        if verdade is not None:
            # A última frase, sem ponto, passa pelo mesmo crivo; com proposta, o pedaço que sobrou
            # era narração do passo (vai ao raciocínio, nunca à voz).
            resto = verdade.fechar()
            tirar_da_tela()
            if (
                resto.strip()
                and visto_cancelamento is None
                and not cancelado()
                and falar_na_voz(resto)
            ):
                visto_cancelamento = time.monotonic()
            resposta.sem_confirmacao.extend(
                c for c in verdade.cortadas if c not in resposta.sem_confirmacao
            )
        if filtro is not None:
            # A última frase, sem ponto no fim, também passa pelo crivo do já dito — e o que ele
            # calou fica registrado (a trilha conta; a tela já mostrou).
            if not pedidos and visto_cancelamento is None and not cancelado():
                resto = filtro.fechar()
                if resto and dizer(resto):
                    visto_cancelamento = time.monotonic()
            resposta.caladas.extend(filtro.caladas)
        return pedidos, visto_cancelamento

    def _anotar_consumo(
        self, consumo: ConsumoDoTurno | None, medicao: Medicao, origem: str
    ) -> None:
        """Uma chamada ao motor: soma no turno (a da tarefa não tem turno) e vai à trilha como
        `motor.chamada` (ADR-0061)."""
        if consumo is not None:
            consumo.somar(medicao)
        trilha = self.ferramentas.trilha if self.ferramentas is not None else None
        if trilha is not None:
            trilha.evento(
                "motor.chamada",
                motor=getattr(self.motor, "codigo", "") or type(self.motor).__name__,
                origem=origem,
                **campos_da_medicao(medicao),
            )

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
        """Piso livre, sem mensagem do dono: os avisos chegam ao Jarvis como **eventos do sistema**
        e um turno do motor decide se fala, o quê e com que palavras (ADR-0070). O código não
        escreve a fala: se o motor responde `[silencio]`, ou cai, nada vai à voz e o card guarda
        (`Resposta.calado`). Os pedaços levam os `notif_ids` de todos os avisos do turno."""
        comeco = time.monotonic()
        self._pendentes.clear()
        resposta = Resposta(
            response_id=f"r-{uuid7()}", turn_id=f"t-{uuid7()}", epoch=epoch, motor=self.motor.nome
        )
        if cancelado():
            resposta.fim = MotivoDoFim.CANCELADO
            resposta.motor_chamado = False
            return resposta
        # O turno é do sistema, não do dono (ADR-0070): os eventos entram como a última mensagem
        # e as regras de decidir, na nota de sistema. Nada disto entra na conversa salva.
        conversa = self.conversa
        mensagens = (
            *conversa.turnos[-conversa.maximo :],
            Mensagem("evento", "Os eventos estão na nota de sistema; decida o que fazer com eles."),
        )
        notas = "\n\n".join(n for n in (self.nota_do_andamento(), nota_dos_eventos(avisos)) if n)
        contexto = Contexto(sistema=f"{conversa.sistema}\n\n{notas}", mensagens=mensagens)
        resposta.ms_ate_contexto = _ms_desde(comeco)
        texto = self._texto_sem_ferramentas(contexto, resposta, cancelado)
        if cancelado():
            resposta.fim = MotivoDoFim.CANCELADO
            return resposta
        if texto is None or calado(texto):
            # O Jarvis decidiu não falar agora (ou o motor caiu): nada na voz, o card guarda.
            resposta.calado = True
            return resposta
        resposta.gerado = texto
        ids = [a.notif_id for a in avisos]
        for identificador in ids:
            self.falas_de_aviso[identificador] = texto
        orcamento = OrcamentoDaFala(livre=pede_detalhe(avisos))
        fatiador = FatiadorDeFala()
        for pedaco in fatiador.alimentar(orcamento.passar(texto) + orcamento.fechar()):
            if cancelado():
                resposta.fim = MotivoDoFim.CANCELADO
                return resposta
            self._publicar(resposta, pedaco, publicar, comeco, ultimo=False, notif_ids=ids)
        resposta.so_na_tela = orcamento.so_na_tela
        for pedaco in fatiador.fechar():
            self._publicar(
                resposta, pedaco, publicar, comeco, ultimo=pedaco.corte is Corte.FIM, notif_ids=ids
            )
        self._pendentes[resposta.response_id] = resposta
        return resposta

    def anotar_progresso(self, tarefa_id: str, pedido: str, passo: str) -> None:
        """Um passo de um subagente: entra no andamento (os últimos `PASSOS_NO_ANDAMENTO`)."""
        _pedido, passos = self.andamento.setdefault(tarefa_id, (pedido, []))
        passos.append(passo)
        del passos[:-PASSOS_NO_ANDAMENTO]

    def anotar_parcial(self, texto: str) -> None:
        """Um parcial do Claude Code delegado (ADR-0070): entra no andamento; vazio = acabou."""
        if not texto:
            self.esquecer_andamento(CHAVE_DA_DELEGACAO)
            return
        self.anotar_progresso(CHAVE_DA_DELEGACAO, "delegação ao Claude Code", texto)

    def esquecer_andamento(self, tarefa_id: str) -> None:
        self.andamento.pop(tarefa_id, None)

    def nota_do_andamento(self) -> str:
        """Os subagentes no ar e o que cada um fez por último: dado, nunca ordem."""
        if not self.andamento:
            return ""
        linhas = [
            "SUBAGENTES EM ANDAMENTO (eventos de progresso, não é o dono falando; o resultado "
            "final chega como evento):"
        ]
        for pedido, passos in list(self.andamento.values()):
            linhas.append(f"- «{pedido}»: " + "; ".join(passos[-PASSOS_NO_ANDAMENTO:]))
        return "\n".join(linhas)

    def _texto_sem_ferramentas(
        self, contexto: Contexto, resposta: Resposta, cancelado: Cancelado
    ) -> str | None:
        """Uma rodada do motor sem ferramentas, inteira, sem o protocolo: o texto que ele escreveu,
        ou `None` se ele caiu. O raciocínio fica com o turno (ADR-0031), nunca na voz."""
        leitor = LeitorDoProtocolo()
        partes: list[str] = []
        deltas = medir(
            self.motor.gerar(contexto, Modo.RAPIDO, cancelado),
            caracteres_entrada=lambda: len(contexto.como_texto()),
            precos=lambda: precos_do_motor(self.motor),
            ao_medir=lambda medicao: self._anotar_consumo(resposta.consumo, medicao, "turno"),
        )

        def juntar(delta: Delta) -> None:
            if isinstance(delta, Raciocinio):
                _guardar_raciocinio(resposta, delta.texto, separado=True)
            elif isinstance(delta, Texto):
                partes.append(delta.texto)

        try:
            for delta in deltas:
                if isinstance(delta, Fim):
                    if delta.motivo in (MotivoDoFim.ERRO, MotivoDoFim.PRAZO):
                        resposta.fim, resposta.detalhe = delta.motivo, delta.detalhe
                        return None
                    break
                if isinstance(delta, Texto):
                    for parte in leitor.alimentar(delta.texto):
                        juntar(parte)
                else:
                    juntar(delta)
        except Exception as erro:  # o motor caiu: o aviso fica no card, a conversa não cai
            resposta.fim, resposta.detalhe = MotivoDoFim.ERRO, f"{type(erro).__name__}: {erro}"
            return None
        finally:
            deltas.close()
        for parte in leitor.fechar():
            juntar(parte)
        return " ".join("".join(partes).split())

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


PALAVRAS_DE_RESPOSTA: Final = 4
"""A partir de quantas palavras novas, ditas numa rodada sem ferramenta, o turno conta como
respondido. «Certo!» sozinho não é resposta: a cobrança do objetivo (ADR-0066) ainda vale."""


def _respondeu(antes: str, depois: str) -> bool:
    """A rodada deixou uma resposta ao dono (o texto que sobrou do relato verdadeiro)?"""
    novo = depois[len(antes) :] if depois.startswith(antes) else depois
    return len(novo.split()) >= PALAVRAS_DE_RESPOSTA


def _so_pediu_permissao(cortadas: Sequence[str]) -> bool:
    """O que o relato verdadeiro cortou era só pergunta de permissão (a oferta do fim), nenhuma
    afirmação de efeito («abri», «mandei»)."""
    return all(afirmacoes(f) == {Afirmacao.PEDE_PERMISSAO} for f in cortadas)


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


def _sem_a_frase(texto: str, frase: str) -> str:
    """O texto sem a última ocorrência da frase (comparada sem espaços repetidos)."""
    palavras = frase.split()
    padrao = r"\s+".join(re.escape(p) for p in palavras)
    achados = list(re.finditer(padrao, texto))
    if not achados:
        return texto
    ultimo = achados[-1]
    return (texto[: ultimo.start()] + texto[ultimo.end() :]).replace("  ", " ")


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
