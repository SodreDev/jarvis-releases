"""Uma chamada de ferramenta, do pedido do modelo ao resultado devolvido ao cérebro (ADR-0028).

O modelo **propõe** (`tool_id` + argumentos nomeados); daqui para baixo, só código decide:

1. a tool tem de estar no catálogo **ligado** (manifesto + corpo aqui) e na allowlist do modo;
2. os argumentos passam pelo `input_schema` inteiro do manifesto — campo a mais é recusa;
3. o **PDP** decide (`allow | confirm | deny`), com o caminho resolvido pelo código;
4. `confirm` vira um pedido à janela (`Confirmar`), que **bloqueia** até o dono responder ou o
   prazo acabar — e prazo vencido **nega**. Só um "sim" do dono faz o PDP decidir de novo com
   `confirmado_pelo_dono=True`; nada que o modelo escreva chega a esse parâmetro;
5. o corpo roda sobre a raiz aberta no grant, consultando o cancelamento;
6. o resultado vai para a auditoria e volta ao cérebro como **dado de terceiros**, truncado.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import jsonschema

from jarvis.barramento.envelope import uuid7
from jarvis.entrada.controle import FERRAMENTA_DE_CONFIRMACAO as CONFIRMACAO_DE_ENTRADA
from jarvis.entrada.controle import FERRAMENTAS_DE_ENTRADA, ControleDeEntrada
from jarvis.executor import arquivos, desktop
from jarvis.executor.comandos import ComandoIndisponivel
from jarvis.executor.desfazer import LIXEIRA, Contaminacao, RegistroDeDesfazeres, aviso_falado
from jarvis.executor.janelas import PRAZO_DO_FOCO_S, PistaDoApp
from jarvis.executor.lancador import App, AppRecusado, RegistroDeApps, lancar
from jarvis.executor.nativas import CORPOS, DE_ARQUIVOS, PRECISAM_DE_AGENDA, Nativas
from jarvis.executor.navegadores import AbridorDeNavegador
from jarvis.executor.organizar import OrganizacaoRecusada, Organizador
from jarvis.executor.sites import Abridor, UrlRecusada, abrir_pelo_portal, dominio, validar_url
from jarvis.imagem import CHAVE_DOS_ANEXOS, Imagem
from jarvis.manifesto.validador import carregar_catalogo
from jarvis.memoryd.ferramentas import Chamada, FerramentasDeMemoria, NaoAutorizado
from jarvis.memoryd.livro import AlvoInexistente
from jarvis.navegador.busca import BuscaNoNavegador
from jarvis.navegador.estado import EstadoDaPonte
from jarvis.navegador.ferramentas import (
    FERRAMENTA_DE_CONFIRMACAO as CONFIRMACAO_DO_NAVEGADOR,
)
from jarvis.navegador.ferramentas import (
    FERRAMENTA_DE_ESTADO,
    FERRAMENTAS_DO_NAVEGADOR,
    AcaoRecusada,
    CorposDoNavegador,
)
from jarvis.politica.abertura import nome_de_app
from jarvis.politica.canonicalizacao import CaminhoRecusado, Sistema, canonicalizar
from jarvis.politica.descritor import AberturaRecusada, RaizAberta, abrir_raiz
from jarvis.politica.memoria import Proveniencia
from jarvis.politica.metodo import ContextoDoMetodo, Escolha, escolher_metodo
from jarvis.politica.objetivo import Objetivo, enderecos_do_resultado
from jarvis.politica.pdp import Decisao, Grant, Pdp, Pedido, Veredito
from jarvis.trilha import SEM_CAUSA, TrilhaDeDiagnostico, chaves, codigo_do_motivo
from jarvis.voz.interface import Onde

if TYPE_CHECKING:
    from jarvis.tarefas.gestor import GestorDeTarefas

PRAZO_DE_CONFIRMACAO_S: Final = 30.0
LIMITE_PARA_O_MODELO: Final = 6000
"""Caracteres do resultado que voltam ao contexto do motor: o resto fica na auditoria."""
LIMITE_DO_RESUMO: Final = 600
"""O resultado podado de um passo antigo (`resumo_para_o_modelo`) cabe nisto."""
CURTO_NO_RESUMO: Final = 160
"""Texto até este tamanho fica no resumo como está (endereço, título, nome); maior vira tamanho."""


def _podado(valor: object) -> object:
    """Um valor do resultado no resumo: o pequeno fica, o volume vira só a medida dele."""
    if isinstance(valor, bool | int | float) or valor is None:
        return valor
    if isinstance(valor, str):
        return valor if len(valor) <= CURTO_NO_RESUMO else f"[podado: {len(valor)} caracteres]"
    if isinstance(valor, list | tuple):
        return f"[podado: {len(valor)} itens]"
    if isinstance(valor, Mapping):
        pequenos = {
            str(k): v
            for k, v in valor.items()
            if isinstance(v, bool | int | float) or (isinstance(v, str) and len(v) <= 80)
        }
        return pequenos if len(pequenos) <= 6 else f"[podado: {len(valor)} campos]"
    return "[podado]"


FERRAMENTAS_LIGADAS: Final = frozenset(
    {
        "files.list_dir",
        "files.read_text",
        "files.search_in_roots",
        "files.write_draft",
        "calendar.create_draft_event",
        "apps.launch",
        "sites.open",
        "browser.launch",
        "acao.desfazer",
    }
)
"""As que têm corpo aqui. Manifesto sem corpo (lixeira, instalar) não aparece para o modelo."""
FERRAMENTAS_DE_TAREFA: Final = frozenset({"tarefa.iniciar", "tarefa.cancelar", "tarefa.estado"})
"""As `tarefa.*` (ADR-0022): o corpo é do gestor de tarefas, e só existem para o modelo quando o
laço montou um — sem ele, não se promete tarefa em segundo plano."""
FERRAMENTAS_DE_MEMORIA: Final = frozenset(
    {
        "memoria.buscar",
        "memoria.buscar_historico",
        "memoria.ler_mensagem",
        "memoria.lembrar",
        "memoria.atualizar",
        "memoria.criar_no",
        "memoria.criar_aresta",
        "memoria.retratar",
        "memoria.apagar",
    }
)
"""As `memoria.*` (ADR-0026): o corpo é do `FerramentasDeMemoria`, e só existem para o modelo
quando há livro aberto (o histórico persistente) — sem ele, a persona não promete o que não há."""

FERRAMENTA_DA_TELA: Final = "browser.tela"
"""Só existe quando o motor do chat recebe imagem (`motor_ve_imagem`): sem isso a captura não
teria como chegar ao modelo, e a tool fica desligada com o motivo dito em `browser.estado`."""
SEM_IMAGEM: Final = (
    "o motor deste chat não recebe imagem: a tela da aba não tem como chegar a ele — use "
    "browser.inspecionar (o mapa da página) ou browser.read (o texto)"
)

FONTES_DE_TERCEIROS: Final = frozenset(
    {
        "files.list_dir",
        "files.read_text",
        "files.search_in_roots",
        "memoria.buscar_historico",
        "web.buscar",
        "web.canal_videos",
        "web.ler",
        "clipboard.text.read",
        "browser.tabs",
        "browser.read",
        "browser.inspecionar",
        "browser.tela",
    }
)
"""Tools cujo resultado é texto que **outra pessoa** escreveu (nome de arquivo, conteúdo, conversa
antiga). Depois de uma delas, o turno é `contaminado`: o que o PDP deixaria livre e que leva
dado para fora (abrir site) passa a pedir o "sim" do dono — injeção não escolhe o destino."""

Cancelado = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class Confirmacao:
    """O que a janela mostra ao dono. Texto puro, montado pelo código a partir dos argumentos."""

    id: str
    tool_id: str
    titulo: str
    detalhe: str
    motivo: str
    prazo_s: float
    argumentos: Mapping[str, Any] = field(default_factory=dict)
    """Os argumentos exatos da chamada: é contra eles que um "sim" já dado é conferido."""
    por_acao: bool = False
    """Pergunta do risco dinâmico (`_exigir_do_dono`: o que está sob o clique, a janela em foco).
    Nenhum "sim" dado antes responde a ela: o dono ainda não viu o que ela mostra."""
    causa: str = ""
    """O código do motivo (`jarvis.trilha.CAUSAS`): é ele que a trilha grava, nunca o `motivo`, que
    pode citar o rótulo que a página dá ao elemento."""
    falado: str = ""
    """O que a **voz** diz da ação (ADR-0038): sem id de ferramenta nem argumento em JSON, que ficam
    no `detalhe`, para a janela. Vazio = o `detalhe` já é frase de gente."""

    @property
    def para_ouvir(self) -> str:
        return self.falado or self.detalhe


Confirmar = Callable[[Confirmacao], bool]
"""Bloqueia até o dono responder na janela. `False` também quando o prazo vence."""


def negar_sempre(_confirmacao: Confirmacao) -> bool:
    """Sem janela para perguntar, a resposta é não (P9: degradar, não improvisar)."""
    return False


@dataclass(frozen=True, slots=True)
class ResultadoDeFerramenta:
    tool_id: str
    status: str
    """`ok`, `negado`, `erro` ou `cancelado`."""
    dados: Mapping[str, Any] = field(default_factory=dict)
    motivo: str = ""
    call_id: str = ""
    aviso: str = ""
    """O aviso falado de uma tool `moderado`: o cérebro o **fala** na hora (o dono ouve o que foi
    feito sem ter sido consultado) e o modelo é avisado de que o dono já ouviu."""
    aviso_silencioso: str = ""
    """O aviso de um passo de navegação (`aviso_silencioso: true` no manifesto): **não** é falado
    nem dito ao modelo como falado; fica na auditoria, e quem conta o resultado ao dono é a
    resposta final (dono, 2026-10-20, ADR-0031)."""
    acao_id: str = ""
    """Se a ação dá para desfazer, o id que `acao.desfazer` aceita."""
    anexos: tuple[Imagem, ...] = ()
    """Imagens do resultado (a tela da aba): vão ao motor à parte, pelo cérebro, e **nunca** entram
    em `para_o_modelo`, na auditoria nem na trilha."""
    causa: str = ""
    """Por que não foi ok, em código (`jarvis.trilha.CAUSAS`): o que a trilha grava no lugar do
    `motivo`, que pode trazer texto da página ou dos argumentos."""

    @property
    def detalhe_de_auditoria(self) -> str:
        if self.motivo or not (self.aviso or self.aviso_silencioso):
            return self.motivo
        if self.aviso_silencioso:
            return f"moderado: passo sem aviso falado «{self.aviso_silencioso}»"
        desfazer = f" — desfazer: {self.acao_id}" if self.acao_id else ""
        return f"moderado: avisado «{self.aviso}»{desfazer}"

    def para_o_modelo(self) -> str:
        corpo: dict[str, Any] = {"tool_id": self.tool_id, "status": self.status}
        if self.motivo:
            corpo["motivo"] = self.motivo
        if self.aviso:
            corpo["aviso_ao_dono"] = f"já dito em voz ao dono: «{self.aviso}» — não repita"
        if self.acao_id:
            corpo["acao_id"] = self.acao_id
        if self.dados:
            corpo["dados"] = self.dados
        texto = json.dumps(corpo, ensure_ascii=False)
        if len(texto) > LIMITE_PARA_O_MODELO:
            texto = texto[:LIMITE_PARA_O_MODELO] + " …[truncado]"
        return texto

    def resumo_para_o_modelo(self) -> str:
        """O resultado podado (memória de trabalho do turno, ADR-0034): o que identifica o passo —
        ferramenta, status, motivo, aviso, endereço, título, números — e, no lugar do volume (texto
        de página, mapa, links, scripts), só o tamanho do que saiu. É o que um passo antigo vira
        quando o contexto do turno passa do orçamento."""
        corpo: dict[str, Any] = {"tool_id": self.tool_id, "status": self.status, "podado": True}
        if self.motivo:
            corpo["motivo"] = self.motivo[:200]
        if self.aviso:
            corpo["aviso_ao_dono"] = f"já dito em voz ao dono: «{self.aviso}» — não repita"
        if self.acao_id:
            corpo["acao_id"] = self.acao_id
        if self.dados:
            corpo["dados"] = {chave: _podado(valor) for chave, valor in self.dados.items()}
        return json.dumps(corpo, ensure_ascii=False)[:LIMITE_DO_RESUMO]


@dataclass(frozen=True, slots=True)
class Avaliacao:
    """Uma chamada validada e julgada pelo PDP, ainda sem efeito (o que `avaliar` devolve)."""

    tool_id: str
    argumentos: dict[str, Any]
    """Normalizados pelo código (nome de app resolvido, família do navegador)."""
    caminho: str | None
    pedido: Pedido
    decisao: Decisao


@dataclass(slots=True)
class ExecutorDeFerramentas:
    pdp: Pdp
    lar: Path
    registro_de_apps: RegistroDeApps = field(
        default_factory=lambda: RegistroDeApps(autorizados={}, instalados=frozenset())
    )
    abrir_site: Abridor = abrir_pelo_portal
    navegadores: AbridorDeNavegador | None = None
    """Os navegadores que o dono configurou. Sem principal (ou sem esta peça), o site abre pelo
    portal, no padrão do desktop — como antes."""
    lancar_app: Callable[[App], int] = lancar
    prazo_do_foco_s: float = PRAZO_DO_FOCO_S
    """Quanto o Jarvis espera a janela de um app aberto para pô-la em foco (`prazo_do_foco_s` na
    configuração; ADR-0037)."""
    sistema: Sistema = Sistema.POSIX
    prazo_de_confirmacao_s: float = PRAZO_DE_CONFIRMACAO_S
    manifestos: dict[str, dict[str, Any]] = field(default_factory=carregar_catalogo)
    memoria: FerramentasDeMemoria | None = None
    tarefas: GestorDeTarefas | None = None
    nativas: Nativas | None = None
    """As portas das ferramentas nativas (desktop, relógio, agenda, web). `None` = as de verdade."""
    """Quem roda as tarefas em segundo plano. Liga as `tarefa.*` ao modelo."""
    """O livro do dono, quando há (a conversa persistente). Liga as `memoria.*` ao modelo."""
    navegador: CorposDoNavegador | None = None
    """O cliente da extensão do navegador (ADR-0027). Sem ele, as `browser.*` não existem."""
    estado_do_navegador: Callable[[], EstadoDaPonte] | None = None
    """Quem diz o estado da ponte (`browser.estado`): existe **ligado ou desligado** o controle,
    para o modelo dizer a verdade em vez de negar a extensão. Sem ele, a tool não aparece."""
    entrada: ControleDeEntrada | None = None
    """Mouse e teclado virtuais (ADR-0027, fatia 4). Sem ele, as `input.*` não existem."""
    motor_ve_imagem: Callable[[], bool] = field(default=lambda: False)
    """Se o motor do chat de agora recebe imagem (`jarvis.s2.motor.aceita_imagem`): é o que liga a
    `browser.tela`. Perguntado na hora, porque o motor muda com o chat e o provedor."""
    objetivo: Objetivo | None = None
    """O objetivo do turno (`jarvis.politica.objetivo`): nasce da fala do dono em `novo_turno` e
    cresce com os endereços que as ferramentas devolvem. Sem ele, as regras de antes."""
    metodo: Escolha | None = None
    """O método do pedido de agora (`jarvis.politica.metodo`, ADR-0035): o que fica de fora do
    turno. Sem ele (sem `novo_turno` com fala), nada fica de fora."""
    trilha: TrilhaDeDiagnostico | None = None
    """Onde cada chamada, veredito e pedido de permissão deixa os seus metadados (`jarvis.trilha`).
    Sem ela, nada é registrado — como antes."""
    destino_onde: Onde = Onde.LOCAL
    destino_motor: str = ""
    """Quem vai ler o resultado: o D20 filtra o que da memória pode ir para este motor."""
    desfazeres: RegistroDeDesfazeres = field(default_factory=RegistroDeDesfazeres)
    turno: Contaminacao = field(default_factory=Contaminacao)
    """O turno em curso já leu conteúdo de terceiros (`FONTES_DE_TERCEIROS`)."""

    @property
    def contaminado(self) -> bool:
        return self.turno.valor

    @contaminado.setter
    def contaminado(self, valor: bool) -> None:
        self.turno.valor = valor

    def novo_turno(self, pedido_do_dono: str = "") -> None:
        """Turno novo do dono: o que se leu de terceiros no anterior não contamina este, o
        objetivo é o que ele pediu agora (sem pedido, não há objetivo — as regras de antes), e o
        método é o que o roteador escolheu para esse pedido com o que está ligado (ADR-0035)."""
        self.turno.valor = False
        self.objetivo = None
        self.metodo = None
        if pedido_do_dono.strip():
            self.metodo = escolher_metodo(
                pedido_do_dono,
                ContextoDoMetodo(
                    navegador=self.navegador is not None,
                    entrada=self.entrada is not None,
                    apps=frozenset(
                        nome_de_app(nome)
                        for app in self.registro_de_apps.autorizados.values()
                        for nome in app.nomes
                    ),
                ),
            )
            # O objetivo do pedido, com o critério de pronto do método escolhido (C2).
            self.objetivo = Objetivo.do_pedido(pedido_do_dono, str(self.metodo.metodo))
            if self.trilha is not None:
                self.trilha.evento(
                    "metodo",
                    metodo=str(self.metodo.metodo),
                    motivo=self.metodo.motivo,
                    de_fora=len(self.metodo.evitar),
                )

    @property
    def pasta_do_jarvis(self) -> Path:
        if self.pdp.pasta_do_jarvis is None:
            raise AberturaRecusada("o PDP não tem pasta do Jarvis configurada")
        return self.pdp.pasta_do_jarvis

    def preparar(self) -> None:
        """Cria as pastas de rascunho **antes** de qualquer pedido: é configuração, não efeito."""
        (self.pasta_do_jarvis / arquivos.PASTA_DE_AGENDA).mkdir(parents=True, exist_ok=True)

    def aprender_correcao_de_app(self, fala: str, app_id: str) -> None:
        """Registra o alias que o dono confirmou; não abre aplicativo nem altera permissões."""
        self.registro_de_apps = self.registro_de_apps.com_correcao(fala, app_id)

    def catalogo_para_o_modelo(self) -> tuple[dict[str, Any], ...]:
        """O catálogo pequeno e fixo do modo (braço C0 da ADR-0024): o que o motor pode propor."""
        return tuple(
            {
                "id": tool_id,
                "titulo": str(self.manifestos[tool_id]["title"]),
                "descricao": self._descricao(tool_id),
                "argumentos": self.manifestos[tool_id]["input_schema"].get("properties", {}),
                "obrigatorios": self.manifestos[tool_id]["input_schema"].get("required", []),
            }
            for tool_id in self.pdp.allowlist()
            if self._ligada(tool_id)
        )

    def objetivo_de(self, marca: Contaminacao | None) -> Objetivo | None:
        """O objetivo de quem chama (C2): o da tarefa, quando ela traz o dela; senão, o do turno."""
        if marca is not None and marca is not self.turno and marca.objetivo is not None:
            return marca.objetivo
        return self.objetivo

    def portas(self) -> Nativas:
        if self.nativas is None:
            self.nativas = Nativas(lar=self.lar)
        # A busca sem chave vai pelo navegador do dono (ADR-0033) — o deste executor, agora: o
        # app troca de executor quando o dono muda o acesso, e as portas passam de um ao outro.
        self.nativas.busca_no_navegador = (
            BuscaNoNavegador(self.navegador.cliente) if self.navegador is not None else None
        )
        return self.nativas

    def disponivel(self, tool_id: str) -> bool:
        """Existe nesta sessão **e** o modo de acesso a permite: o que uma tarefa pode rodar."""
        return self._ligada(tool_id) and tool_id in self.pdp.allowlist()

    def _ligada(self, tool_id: str) -> bool:
        """Tem corpo aqui, manifesto no catálogo e (se for de memória) um livro aberto."""
        if tool_id not in self.manifestos:
            return False
        if tool_id in FERRAMENTAS_DE_MEMORIA:
            return self.memoria is not None
        if tool_id in FERRAMENTAS_DE_TAREFA:
            return self.tarefas is not None
        if tool_id == FERRAMENTA_DE_ESTADO:
            return self.estado_do_navegador is not None
        if tool_id == FERRAMENTA_DA_TELA:
            return self.navegador is not None and self.motor_ve_imagem()
        if tool_id in FERRAMENTAS_DO_NAVEGADOR:
            return self.navegador is not None
        if tool_id in FERRAMENTAS_DE_ENTRADA:
            return self.entrada is not None
        if tool_id in PRECISAM_DE_AGENDA:
            return self.portas().agenda is not None
        return tool_id in FERRAMENTAS_LIGADAS or tool_id in CORPOS or tool_id in DE_ARQUIVOS

    def _descricao(self, tool_id: str) -> str:
        texto = " ".join(str(self.manifestos[tool_id]["description"]).split())
        if tool_id == FERRAMENTA_DE_ESTADO:
            # Só o que se sabe sem I/O: a conexão de agora é a tool que lê, quando chamada.
            if self.navegador is None:
                return (
                    f"{texto} Agora o controle está DESLIGADO na configuração: as browser.* não "
                    "existem até o dono ligar."
                )
            ligado = f"{texto} Agora o controle está ligado na configuração"
            if not self.motor_ve_imagem():
                return f"{ligado}; a tela da aba não: {SEM_IMAGEM}."
            return f"{ligado}."
        if tool_id == "browser.launch" and self.navegadores is not None:
            feitos = ", ".join(
                f"{f} (principal)" if f == self.navegadores.principal else f
                for f in self.navegadores.familias()
            )
            return f"{texto} Configurados agora: {feitos or 'nenhum'}."
        if tool_id != "apps.launch":
            return texto
        nomes = ", ".join(a.nome for a in self.registro_de_apps.autorizados.values())
        # O modelo não adivinha o que está instalado: sem a lista, ele chuta "Dolphin".
        return f"{texto} Autorizados agora: {nomes or 'nenhum'}."

    # --- a chamada --------------------------------------------------------------------------
    def executar(
        self,
        tool_id: str,
        args: Mapping[str, Any],
        *,
        cancelado: Cancelado,
        confirmar: Confirmar = negar_sempre,
        session_id: str = "",
        call_id: str = "",
        proveniencia: Proveniencia | None = None,
        contaminacao: Contaminacao | None = None,
    ) -> ResultadoDeFerramenta:
        marca = contaminacao if contaminacao is not None else self.turno
        avaliacao = self.avaliar(
            tool_id,
            args,
            session_id=session_id,
            call_id=call_id,
            proveniencia=proveniencia,
            contaminacao=marca,
        )
        if isinstance(avaliacao, ResultadoDeFerramenta):
            return avaliacao
        return self.concluir(
            avaliacao,
            cancelado=cancelado,
            confirmar=confirmar,
            proveniencia=proveniencia,
            contaminacao=marca,
        )

    def avaliar(
        self,
        tool_id: str,
        args: Mapping[str, Any],
        *,
        session_id: str = "",
        call_id: str = "",
        proveniencia: Proveniencia | None = None,
        contaminacao: Contaminacao | None = None,
    ) -> Avaliacao | ResultadoDeFerramenta:
        """Passos 1 a 3: catálogo, contrato e o veredito do PDP — sem rodar nada.

        Separado de `concluir` para o portão contextual (`jarvis.s2.portao`) olhar o pedido
        **depois** do PDP e só apertar: o que o PDP nega nem chega ao Jev."""
        avaliacao = self._avaliar(
            tool_id,
            args,
            session_id=session_id,
            call_id=call_id,
            proveniencia=proveniencia,
            contaminacao=contaminacao,
        )
        if isinstance(avaliacao, ResultadoDeFerramenta):
            self._trilhar(avaliacao, args.keys(), pdp="não chegou ao PDP")
        return avaliacao

    def _avaliar(
        self,
        tool_id: str,
        args: Mapping[str, Any],
        *,
        session_id: str,
        call_id: str,
        proveniencia: Proveniencia | None,
        contaminacao: Contaminacao | None,
    ) -> Avaliacao | ResultadoDeFerramenta:
        marca = contaminacao if contaminacao is not None else self.turno
        chamada = call_id or f"c-{uuid7()}"
        do_turno = contaminacao is None or contaminacao is self.turno
        # A chamada do turno segue o método do pedido de agora; a tarefa em segundo plano (que traz
        # a contaminação dela) segue o do pedido que ela cumpre, se ele veio junto (ADR-0038) —
        # nunca o do pedido de agora, que pode ser outro.
        metodo = self.metodo if do_turno else marca.metodo
        if metodo is not None and tool_id in metodo.evitar:
            return ResultadoDeFerramenta(
                tool_id,
                "negado",
                motivo=metodo.recusa(tool_id),
                call_id=chamada,
                causa="metodo_de_fora",
            )
        if not self._ligada(tool_id):
            sem_imagem = tool_id == FERRAMENTA_DA_TELA and self.navegador is not None
            return ResultadoDeFerramenta(
                tool_id,
                "negado",
                motivo=SEM_IMAGEM
                if sem_imagem
                else "essa ferramenta não existe no catálogo ligado",
                call_id=chamada,
                causa="ferramenta_desligada",
            )
        argumentos = dict(args)
        try:
            jsonschema.validate(argumentos, self.manifestos[tool_id]["input_schema"])
            caminho = self._caminho_para_o_pdp(tool_id, argumentos)
        except jsonschema.ValidationError as erro:
            return ResultadoDeFerramenta(
                tool_id,
                "erro",
                motivo=f"argumentos fora do contrato: {erro.message}",
                call_id=chamada,
                causa="fora_do_contrato",
            )
        except (ValueError, CaminhoRecusado) as erro:
            return ResultadoDeFerramenta(
                tool_id, "erro", motivo=str(erro), call_id=chamada, causa="argumento_recusado"
            )

        if tool_id == "apps.launch":
            # O PDP compara o nome com o registro do dono; o executor aceita "Brave" para
            # "Brave Web Browser". Sem alinhar, app marcado chamado por nome parcial era negado
            # (com a mensagem errada). Resolvido, o nome que a política vê é o do app marcado.
            # Fora do registro, o nome fica como veio: o PDP nega e a sugestão sai abaixo.
            resolucao = self.registro_de_apps.resolver_detalhado(str(argumentos["nome"]))
            if resolucao.estado == "ambiguo":
                return ResultadoDeFerramenta(
                    tool_id,
                    "negado",
                    motivo=(
                        "não abri por ambiguidade: " + resolucao.pergunta + " Diga o nome completo."
                    ),
                    call_id=chamada,
                    causa="app_ambiguo",
                )
            if resolucao.app is not None:
                argumentos["nome"] = resolucao.app.nome
        if tool_id == "browser.launch" and self.navegadores is not None:
            dito = str(argumentos.get("navegador", "")).strip()
            familia = self.navegadores.resolver(dito) if dito else None
            if familia is not None:  # «Brave» → a família configurada, que é o que o PDP conhece
                argumentos["navegador"] = familia
        pedido = Pedido(
            tool_id=tool_id,
            args=argumentos,
            caminho=caminho,
            session_id=session_id,
            call_id=chamada,
            proveniencia=proveniencia,
            contaminado=marca.valor,
            objetivo=self.objetivo_de(marca),
        )
        return Avaliacao(tool_id, argumentos, caminho, pedido, self.pdp.decidir(pedido))

    def pergunta_de(
        self, avaliacao: Avaliacao, motivo: str = "", causa: str = "confirmacao_do_pdp"
    ) -> Confirmacao:
        """O que a janela (ou a voz) pergunta ao dono sobre esta chamada exata."""
        return Confirmacao(
            id=avaliacao.pedido.call_id,
            tool_id=avaliacao.tool_id,
            titulo=str(self.manifestos[avaliacao.tool_id]["title"]),
            detalhe=self._detalhe(avaliacao.tool_id, avaliacao.argumentos),
            motivo=motivo or avaliacao.decisao.motivo,
            prazo_s=self.prazo_de_confirmacao_s,
            argumentos=dict(avaliacao.argumentos),
            causa=causa,
            falado=self._falado(avaliacao.tool_id, avaliacao.argumentos),
        )

    def descartar(self, avaliacao: Avaliacao, status: str, motivo: str, *, causa: str) -> None:
        """A avaliação não vai rodar (o portão vetou, ou virou pendência): o grant é solto já,
        em vez de segurar a raiz aberta até o TTL, e a auditoria diz por quê (a trilha, a causa)."""
        if avaliacao.decisao.grant is not None:
            self.pdp.liberar(avaliacao.decisao.grant.grant_id)
        self.pdp.auditoria.anexar_resultado(avaliacao.decisao.decision_id, status, motivo)
        self._trilhar(
            ResultadoDeFerramenta(avaliacao.tool_id, status, motivo=motivo, causa=causa),
            avaliacao.argumentos.keys(),
            pdp=str(avaliacao.decisao.veredito),
        )

    def _trilhar(
        self,
        resultado: ResultadoDeFerramenta,
        argumentos: Iterable[str],
        *,
        pdp: str,
        ms: float | None = None,
        fase: str = "",
    ) -> None:
        if self.trilha is None:
            return
        # A causa em código, nunca o motivo: ele pode citar o rótulo que a página dá ao elemento
        # ou um valor de argumento. Sem causa, o código genérico.
        causa = (resultado.causa or SEM_CAUSA) if resultado.status != "ok" else ""
        # Se o aviso da moderada foi falado ou ficou só na auditoria (ADR-0031) — nunca a frase.
        aviso = "silencioso" if resultado.aviso_silencioso else ""
        self.trilha.evento(
            "ferramenta",
            tool_id=resultado.tool_id,
            argumentos=chaves(argumentos),
            status=resultado.status,
            pdp=pdp,
            ms=round(ms, 1) if ms is not None else None,
            motivo=causa,
            codigo=codigo_do_motivo(resultado.motivo) if causa else "",
            aviso="falado" if resultado.aviso else aviso,
            fase=fase,
        )

    def _trilhar_permissao(self, pergunta: Confirmacao, origem: str, sim: bool) -> None:
        if self.trilha is not None:
            self.trilha.evento(
                "permissao",
                tool_id=pergunta.tool_id,
                origem=origem,
                motivo=pergunta.causa or SEM_CAUSA,
                resposta="sim" if sim else "não",
            )

    def concluir(
        self,
        avaliacao: Avaliacao,
        *,
        cancelado: Cancelado,
        confirmar: Confirmar = negar_sempre,
        proveniencia: Proveniencia | None = None,
        contaminacao: Contaminacao | None = None,
    ) -> ResultadoDeFerramenta:
        """Passos 4 a 6: a confirmação que o PDP pediu, o corpo e a auditoria."""
        comeco = time.monotonic()
        veredito = str(avaliacao.decisao.veredito)
        if self.trilha is not None:
            # O início fica registrado antes do corpo: se a chamada travar ou o app sair no meio,
            # a trilha mostra a ferramenta que começou e não terminou (dono, 2026-10-20).
            self.trilha.evento(
                "ferramenta.inicio",
                tool_id=avaliacao.tool_id,
                argumentos=chaves(avaliacao.argumentos.keys()),
                pdp=veredito,
            )
        resultado = self._concluir(
            avaliacao,
            cancelado=cancelado,
            confirmar=confirmar,
            proveniencia=proveniencia,
            contaminacao=contaminacao,
        )
        objetivo = self.objetivo_de(contaminacao if contaminacao is not None else self.turno)
        if objetivo is not None:
            # O passo feito muda a fase (ler depois de um efeito é verificar) — só ferramenta e
            # status, nunca o resultado (C2).
            leitura = self.manifestos[avaliacao.tool_id].get("side_effect") == "none"
            objetivo.registrar(avaliacao.tool_id, resultado.status, leitura=leitura)
        self._trilhar(
            resultado,
            avaliacao.argumentos.keys(),
            pdp=veredito,
            ms=(time.monotonic() - comeco) * 1000.0,
            fase=str(objetivo.fase) if objetivo is not None else "",
        )
        return resultado

    def _concluir(
        self,
        avaliacao: Avaliacao,
        *,
        cancelado: Cancelado,
        confirmar: Confirmar,
        proveniencia: Proveniencia | None,
        contaminacao: Contaminacao | None,
    ) -> ResultadoDeFerramenta:
        marca = contaminacao if contaminacao is not None else self.turno
        tool_id, argumentos, caminho = avaliacao.tool_id, avaliacao.argumentos, avaliacao.caminho
        pedido, decisao = avaliacao.pedido, avaliacao.decisao
        chamada = pedido.call_id
        if decisao.veredito is Veredito.CONFIRM:
            pergunta = self.pergunta_de(avaliacao)
            sim = not cancelado() and confirmar(pergunta)
            self._trilhar_permissao(pergunta, "pdp", sim)
            if not sim:
                self.pdp.auditoria.anexar_resultado(
                    decisao.decision_id, "negado", "dono não confirmou"
                )
                return ResultadoDeFerramenta(
                    tool_id,
                    "negado",
                    motivo="o dono não confirmou (negou, ou o prazo acabou)",
                    call_id=chamada,
                    causa="dono_nao_confirmou",
                )
            decisao = self.pdp.decidir(pedido, confirmado_pelo_dono=True)
        if decisao.veredito is not Veredito.ALLOW or decisao.grant is None:
            motivo = decisao.motivo
            if tool_id == "apps.launch":
                motivo = self._sugestao_de_app(str(argumentos["nome"]), motivo)
            return ResultadoDeFerramenta(
                tool_id, "negado", motivo=motivo, call_id=chamada, causa="pdp_negou"
            )
        resultado = self._rodar(
            tool_id,
            argumentos,
            decisao,
            caminho,
            cancelado,
            chamada,
            proveniencia,
            marca,
            confirmar,
        )
        if resultado.status == "ok":
            resultado = self._depois_do_efeito(tool_id, argumentos, resultado, marca)
        self.pdp.auditoria.anexar_resultado(
            decisao.decision_id, resultado.status, resultado.detalhe_de_auditoria
        )
        return resultado

    def _depois_do_efeito(
        self,
        tool_id: str,
        args: Mapping[str, Any],
        resultado: ResultadoDeFerramenta,
        marca: Contaminacao,
    ) -> ResultadoDeFerramenta:
        """O que o tier pede depois que a tool rodou: contaminar o turno (leitura de terceiros),
        e, na **moderada**, montar o aviso falado e guardar como desfazer."""
        if tool_id in FONTES_DE_TERCEIROS:
            marca.valor = True
        objetivo = self.objetivo_de(marca)
        if objetivo is not None:
            # O caminho do objetivo: o que ele abriu, os links e resultados que trouxe. É daqui
            # que sai o "domínio novo alcançado" que não pergunta (dono, 2026-10-20).
            objetivo.alcancar(enderecos_do_resultado(resultado.dados))
        manifesto = self.manifestos[tool_id]
        if manifesto.get("tier") != "moderado":
            return resultado
        acao = self._registrar_desfazer(tool_id, resultado.dados)
        frase = aviso_falado(manifesto, args, resultado.dados)
        # Passo de navegação (clicar, digitar, rolar, navegar): o dono não acompanha passo a
        # passo (ADR-0031). O validador só aceita isto em efeito passageiro.
        silencioso = manifesto.get("aviso_silencioso") is True
        return ResultadoDeFerramenta(
            tool_id,
            resultado.status,
            dados=resultado.dados,
            call_id=resultado.call_id,
            aviso="" if silencioso else frase,
            aviso_silencioso=frase if silencioso else "",
            acao_id=acao,
            anexos=resultado.anexos,
        )

    def _registrar_desfazer(self, tool_id: str, dados: Mapping[str, Any]) -> str:
        """Como voltar atrás do que acabou de ser feito, se der. `""` = não dá."""
        registro = self.desfazeres
        if tool_id == "tarefa.iniciar":
            return registro.registrar(
                tool_id, "a tarefa em segundo plano", "cancelar_tarefa", str(dados["tarefa_id"])
            ).acao_id
        if tool_id in ("files.write_draft", "calendar.create_draft_event"):
            nome = Path(str(dados["caminho"])).name
            return registro.registrar(
                tool_id, f"o rascunho {nome}", "lixeira", str(dados["caminho"])
            ).acao_id
        if tool_id in ("files.create_dir", "files.copy"):
            quem = "a pasta" if tool_id == "files.create_dir" else "a cópia"
            alvo = str(dados["caminho"])
            return registro.registrar(tool_id, f"{quem} {dados['nome']}", "lixeira", alvo).acao_id
        if tool_id == "files.move":
            return registro.registrar(
                tool_id, f"o que foi movido para {dados['nome']}", "mover", str(dados["de"]),
                str(dados["para"]),
            ).acao_id  # fmt: skip
        if tool_id == "clipboard.text.write":
            return registro.registrar(
                tool_id, "a área de transferência", "area", "", self.portas().anterior_da_area
            ).acao_id
        if tool_id == "timer.alarm.set":
            return registro.registrar(
                tool_id, "o lembrete", "cancelar_alarme", str(dados["alarme_id"])
            ).acao_id
        livro = {
            "memoria.lembrar": ("assertion_id", "a anotação"),
            "memoria.criar_no": ("entity_id", "o registro novo na memória"),
            "memoria.criar_aresta": ("edge_id", "a ligação na memória"),
        }.get(tool_id)
        if livro is not None and self.memoria is not None and not dados.get("existente"):
            return registro.registrar(tool_id, livro[1], "retratar", str(dados[livro[0]])).acao_id
        return ""

    def _rodar(
        self,
        tool_id: str,
        args: dict[str, Any],
        decisao: Decisao,
        caminho: str | None,
        cancelado: Cancelado,
        chamada: str,
        proveniencia: Proveniencia | None = None,
        marca: Contaminacao | None = None,
        confirmar: Confirmar = negar_sempre,
    ) -> ResultadoDeFerramenta:
        if cancelado():
            return ResultadoDeFerramenta(
                tool_id, "cancelado", motivo="interrompido", call_id=chamada, causa="interrompido"
            )
        assert decisao.grant is not None
        try:
            if tool_id in FERRAMENTAS_DE_MEMORIA:
                dados = self._memoria(tool_id, args, decisao, proveniencia)
            elif tool_id in FERRAMENTAS_DO_NAVEGADOR:
                dados = self._navegador(tool_id, args, chamada, cancelado, confirmar, marca)
            elif tool_id in FERRAMENTAS_DE_ENTRADA:
                dados = self._entrada_virtual(tool_id, args, chamada, cancelado, confirmar, marca)
            else:
                dados = self._corpo(
                    tool_id, args, decisao.grant, caminho, cancelado, chamada, marca
                )
        except arquivos.Cancelada as erro:
            return ResultadoDeFerramenta(
                tool_id, "cancelado", motivo=str(erro), call_id=chamada, causa="interrompido"
            )
        except AcaoRecusada as erro:
            return ResultadoDeFerramenta(
                tool_id, "negado", motivo=str(erro), call_id=chamada, causa="acao_recusada"
            )
        except (
            AberturaRecusada,
            AlvoInexistente,
            ComandoIndisponivel,
            NaoAutorizado,
            OSError,
            ValueError,
            AppRecusado,
            UrlRecusada,
        ) as erro:
            return ResultadoDeFerramenta(
                tool_id, "erro", motivo=str(erro), call_id=chamada, causa="erro_da_ferramenta"
            )
        anexos = tuple(dados.pop(CHAVE_DOS_ANEXOS, ()))
        return ResultadoDeFerramenta(tool_id, "ok", dados=dados, call_id=chamada, anexos=anexos)

    def _exigir_do_dono(
        self,
        ferramenta_de_confirmacao: str,
        tool_id: str,
        chamada: str,
        cancelado: Cancelado,
        confirmar: Confirmar,
        contaminado: bool,
    ) -> Callable[[str, str, str], None]:
        """O "sim" por ação das tools cujo risco depende do que está sob o clique (navegador,
        entrada virtual): um segundo pedido ao PDP, de manifesto `perigoso`, que **só** o "sim" do
        dono na janela solta. Cada pergunta é uma linha da auditoria; ninguém passa o parâmetro
        `confirmado_pelo_dono` a não ser esta função, depois da resposta da janela."""
        perguntas = 0

        def exigir(detalhe: str, motivo: str, causa: str) -> None:
            nonlocal perguntas
            perguntas += 1
            id_da_pergunta = f"{chamada}-s{perguntas}"
            pedido = Pedido(
                ferramenta_de_confirmacao,
                {"acao": tool_id, "detalhe": detalhe[:300]},
                call_id=id_da_pergunta,
                contaminado=contaminado,
            )
            decisao = self.pdp.decidir(pedido)
            if decisao.veredito is Veredito.CONFIRM:
                pergunta = Confirmacao(
                    id=id_da_pergunta,
                    tool_id=tool_id,
                    titulo=str(self.manifestos[tool_id]["title"]),
                    detalhe=detalhe,
                    motivo=motivo,
                    prazo_s=self.prazo_de_confirmacao_s,
                    por_acao=True,
                    causa=causa,
                )
                sim = not cancelado() and confirmar(pergunta)
                self._trilhar_permissao(pergunta, "risco_dinamico", sim)
                if not sim:
                    self.pdp.auditoria.anexar_resultado(
                        decisao.decision_id, "negado", "dono não confirmou"
                    )
                    raise AcaoRecusada("o dono não confirmou (negou, ou o prazo acabou)")
                decisao = self.pdp.decidir(pedido, confirmado_pelo_dono=True)
            if decisao.veredito is not Veredito.ALLOW:
                raise AcaoRecusada(decisao.motivo)

        return exigir

    def _navegador(
        self,
        tool_id: str,
        args: Mapping[str, Any],
        chamada: str,
        cancelado: Cancelado,
        confirmar: Confirmar,
        marca: Contaminacao | None,
    ) -> dict[str, Any]:
        """Corpo das `browser.*`: inspeciona o alvo e, se for perigoso (enviar, pagar, banco…),
        volta por `exigir`."""
        assert self.navegador is not None
        contaminado = bool(marca and marca.valor) or self.contaminado
        return self.navegador.executar(
            tool_id,
            args,
            contaminado=contaminado,
            liberados=self.pdp.sites_sem_confirmar,
            exigir=self._exigir_do_dono(
                CONFIRMACAO_DO_NAVEGADOR, tool_id, chamada, cancelado, confirmar, contaminado
            ),
            cancelado=cancelado,
            objetivo=self.objetivo_de(marca),
        )

    def _entrada_virtual(
        self,
        tool_id: str,
        args: Mapping[str, Any],
        chamada: str,
        cancelado: Cancelado,
        confirmar: Confirmar,
        marca: Contaminacao | None,
    ) -> dict[str, Any]:
        """Corpo das `input.*`: lê o foco, recusa ou pergunta, e só então sintetiza o evento."""
        assert self.entrada is not None
        contaminado = bool(marca and marca.valor) or self.contaminado
        return self.entrada.executar(
            tool_id,
            args,
            contaminado=contaminado,
            exigir=self._exigir_do_dono(
                CONFIRMACAO_DE_ENTRADA, tool_id, chamada, cancelado, confirmar, contaminado
            ),
            cancelado=cancelado,
        )

    def _organizar(
        self,
        tool_id: str,
        args: Mapping[str, Any],
        grant: Grant,
        caminho: str | None,
        marca: Contaminacao | None,
        chamada: str,
    ) -> dict[str, Any]:
        """Criar pasta, copiar e mover (moderadas): sob o descritor da raiz do grant."""
        assert caminho is not None
        organizador = Organizador(
            self.pdp,
            self.lar,
            self.sistema,
            session_id=self.pdp.session_id,
            call_id=chamada,
            contaminado=bool(marca and marca.valor) or self.contaminado,
        )
        try:
            if tool_id == "files.create_dir":
                return organizador.criar_pasta(grant, caminho)
            if tool_id == "files.copy":
                return organizador.copiar(grant, str(args["origem"]), caminho)
            return organizador.mover(grant, str(args["origem"]), caminho)
        except OrganizacaoRecusada as erro:
            raise ValueError(str(erro)) from None

    def _tarefa(self, tool_id: str, args: Mapping[str, Any]) -> dict[str, Any]:
        """Corpo das `tarefa.*`. Recusa do gestor (teto, ferramenta fora da allowlist) volta como
        erro com a frase, e o modelo a repassa ao dono."""
        assert self.tarefas is not None
        if tool_id == "tarefa.iniciar":
            tarefa = self.tarefas.iniciar(
                str(args["descricao"]),
                str(args["tool"]),
                dict(args.get("parametros", {})),
                contaminado=self.contaminado,
            )
            return tarefa.para_o_modelo() | {"motor": tarefa.motor}
        if tool_id == "tarefa.cancelar":
            return self.tarefas.cancelar(str(args["tarefa_id"])).para_o_modelo()
        feitas = self.tarefas.estado(str(args.get("tarefa_id", "")))
        return {"tarefas": [t.para_o_modelo() for t in feitas[:8]]}

    def _desfazer(self, acao_id: str, grant: Grant) -> dict[str, Any]:
        """Volta atrás de uma ação moderada. Nada é apagado: o arquivo vai para a lixeira do
        Jarvis, a memória é retratada (ADR-0026: deixa de valer, continua no livro)."""
        desfazer = self.desfazeres.achar(acao_id)
        if desfazer is None:
            raise ValueError(
                "não há ação para desfazer com esse id" if acao_id else "não há nada para desfazer"
            )
        if desfazer.tipo == "lixeira":
            dono, lixeira = self._grant_do_alvo(desfazer.alvo, grant)
            raiz = self.pdp.abrir_para(dono, ".")
            relativo = canonicalizar(desfazer.alvo, self.sistema).texto
            relativo = relativo[len(dono.raiz.rstrip("/")) :].lstrip("/")
            arquivos.recolher_para_a_lixeira(raiz, relativo, lixeira=lixeira)
        elif desfazer.tipo == "mover":
            dono, _ = self._grant_do_alvo(desfazer.alvo, grant)
            try:
                Organizador(self.pdp, self.lar, self.sistema).desfazer_mover(
                    dono, desfazer.alvo, desfazer.extra
                )
            except OrganizacaoRecusada as erro:
                raise ValueError(str(erro)) from None
        elif desfazer.tipo == "area":
            desktop.escrever_area(self.portas().lancar, desfazer.extra, self.portas().ambiente)
        elif desfazer.tipo == "cancelar_alarme":
            agenda = self.portas().agenda
            if agenda is None:
                raise ValueError("a agenda não está ligada")
            agenda.cancelar(desfazer.alvo)
        elif desfazer.tipo == "cancelar_tarefa" and self.tarefas is not None:
            self.tarefas.cancelar(desfazer.alvo)
        elif self.memoria is not None:
            self.memoria.livro.retratar(desfazer.alvo)
        else:
            raise ValueError("a memória não está aberta: não dá para retratar")
        self.desfazeres.retirar(desfazer)
        return {"desfeito": desfazer.descricao}

    def _grant_do_alvo(self, alvo: str, grant_do_jarvis: Grant) -> tuple[Grant, str]:
        """O grant da raiz onde o alvo do desfazer está, e o nome da lixeira dela. Na área do
        Jarvis é o da própria chamada; fora dela, uma decisão nova do PDP (a raiz tem de deixar
        escrever), e a lixeira é uma pasta escondida **dentro** dessa raiz — nada é apagado."""
        if alvo.startswith(str(self.pasta_do_jarvis) + "/"):
            return grant_do_jarvis, LIXEIRA
        decisao = self.pdp.decidir(
            Pedido(
                "files.move", {"origem": alvo, "destino": alvo}, alvo, call_id=f"desfazer-{uuid7()}"
            )
        )
        if decisao.veredito is not Veredito.ALLOW or decisao.grant is None:
            raise ValueError(f"não posso desfazer ali: {decisao.motivo}")
        return decisao.grant, ".lixeira-do-jarvis"

    def _memoria(
        self,
        tool_id: str,
        args: dict[str, Any],
        decisao: Decisao,
        proveniencia: Proveniencia | None,
    ) -> dict[str, Any]:
        """Corpo das `memoria.*`: a decisão já é `allow` (a confirmação, se houve, foi do dono)."""
        assert self.memoria is not None
        return self.memoria.executar(
            Chamada(
                tool_id=tool_id,
                args=args,
                decisao=decisao,
                proveniencia=proveniencia,
                destino_onde=self.destino_onde,
                destino_motor=self.destino_motor,
            )
        )

    def _corpo(
        self,
        tool_id: str,
        args: dict[str, Any],
        grant: Grant,
        caminho: str | None,
        cancelado: Cancelado,
        chamada: str = "",
        marca: Contaminacao | None = None,
    ) -> dict[str, Any]:
        if tool_id == "files.search_in_roots":
            return self._procurar(str(args["consulta"]), cancelado)
        if tool_id == "acao.desfazer":
            return self._desfazer(str(args.get("acao_id", "")), grant)
        if tool_id in FERRAMENTAS_DE_TAREFA:
            return self._tarefa(tool_id, args)
        if tool_id == FERRAMENTA_DE_ESTADO:
            assert self.estado_do_navegador is not None  # _ligada filtra antes
            return self.estado_do_navegador().para_o_modelo()
        if tool_id in CORPOS:
            return CORPOS[tool_id](self.portas(), args)
        if tool_id in DE_ARQUIVOS:
            return self._organizar(tool_id, args, grant, caminho, marca, chamada)
        if tool_id == "apps.launch":
            app = self.registro_de_apps.resolver(str(args["nome"]))
            janelas = self.portas().janelas
            do_turno = marca is None or marca is self.turno
            # As janelas de antes do lançamento: a que aparecer depois é evidência (ADR-0037).
            antes = (
                frozenset(j.id for j in janelas.listar())
                if janelas is not None and do_turno
                else frozenset()
            )
            pid = self.lancar_app(app)
            return {"app": app.nome, "pid": pid} | self._acompanhar_o_foco(
                app, pid, antes, do_turno
            )
        if tool_id == "browser.launch":
            if self.navegadores is None or not self.navegadores.navegadores:
                raise AppRecusado(
                    "nenhum navegador configurado: escolha o principal em Configuração → "
                    "Navegadores"
                )
            familia, pid = self.navegadores.abrir_sozinho(str(args.get("navegador", "")).strip())
            return {"navegador": familia, "pid": pid}
        if tool_id == "sites.open":
            url = validar_url(str(args["url"]))
            pedido = str(args.get("navegador", "")).strip()
            reutilizar_aba = not bool(args.get("nova_aba", False))
            if self.navegadores is not None and (self.navegadores.principal or pedido):
                usado, reutilizou = self.navegadores.abrir(
                    url, pedido, reutilizar_aba=reutilizar_aba
                )
                return {
                    "url": url,
                    "dominio": dominio(url),
                    "navegador": usado,
                    "reutilizou_aba": reutilizou,
                }
            self.abrir_site(url)
            return {"url": url, "dominio": dominio(url), "reutilizou_aba": False}
        assert caminho is not None
        relativo = self._relativo(grant, caminho)
        raiz = self.pdp.abrir_para(grant, relativo)
        if tool_id == "files.list_dir":
            return arquivos.listar(raiz, relativo, lar=self.lar, sistema=self.sistema)
        if tool_id == "files.read_text":
            return arquivos.ler_texto(raiz, relativo)
        if tool_id == "files.write_draft":
            nome = arquivos.nome_de_rascunho(str(args["nome"]))
            return arquivos.gravar_rascunho(raiz, nome, str(args["texto"]), pasta=relativo)
        if tool_id == "calendar.create_draft_event":
            ics = arquivos.evento_ics(
                str(args["titulo"]),
                str(args["inicio"]),
                duracao_min=int(args.get("duracao_min", 60)),
                local=str(args.get("local", "")),
            )
            nome = arquivos.nome_de_rascunho(str(args["titulo"]), extensao_padrao=".md")
            nome = nome.rsplit(".", 1)[0] + ".ics"
            return arquivos.gravar_rascunho(raiz, nome, ics, pasta=relativo)
        raise ValueError(f"{tool_id} sem corpo")  # pragma: no cover — FERRAMENTAS_LIGADAS cobre

    # --- caminhos -----------------------------------------------------------------------------
    def _caminho_para_o_pdp(self, tool_id: str, args: Mapping[str, Any]) -> str | None:
        """O caminho que o PDP julga. Para escrita, quem escolhe é o código — o modelo não passa
        caminho nenhum; para leitura, o do modelo, com `~` resolvido e nada de relativo."""
        if tool_id == "files.write_draft":
            return str(self.pasta_do_jarvis / arquivos.PASTA_DE_RASCUNHOS)
        if tool_id == "calendar.create_draft_event":
            return str(self.pasta_do_jarvis / arquivos.PASTA_DE_AGENDA)
        if tool_id == "acao.desfazer":
            return str(self.pasta_do_jarvis)  # o código escolhe: nunca um caminho do modelo
        if tool_id in ("files.create_dir", "files.copy", "files.move"):
            return Organizador(self.pdp, self.lar, self.sistema).absoluto(
                str(args.get("path") or args["destino"])
            )
        if tool_id in ("files.list_dir", "files.read_text"):
            bruto = str(args["path"]).strip()
            if bruto == "~" or bruto.startswith("~/"):
                bruto = str(self.lar) + bruto[1:]
            if not Path(bruto).is_absolute():
                raise ValueError(
                    f"caminho relativo ({bruto!r}): diga a pasta inteira, por exemplo ~/Documentos"
                )
            return bruto
        return None

    def _relativo(self, grant: Grant, caminho: str) -> str:
        texto = canonicalizar(caminho, self.sistema).texto
        raiz = grant.raiz.rstrip("/")
        return texto[len(raiz) :].lstrip("/") or "."

    def _procurar(self, consulta: str, cancelado: Cancelado) -> dict[str, Any]:
        abertas: list[RaizAberta] = []
        try:
            for raiz in self.pdp.raizes():
                if not Path(raiz.caminho.texto).is_dir():
                    continue
                try:
                    abertas.append(abrir_raiz(Path(raiz.caminho.texto)))
                except AberturaRecusada:
                    continue
            return arquivos.procurar(
                abertas, consulta, lar=self.lar, sistema=self.sistema, cancelado=cancelado
            )
        finally:
            for aberta in abertas:
                aberta.fechar()

    # --- texto para o dono --------------------------------------------------------------------
    def _detalhe(self, tool_id: str, args: Mapping[str, Any]) -> str:
        if tool_id == "files.write_draft":
            palavras = len(str(args["texto"]).split())
            return f"gravar o rascunho «{args['nome']}» na pasta do Jarvis ({palavras} palavras)"
        if tool_id == "calendar.create_draft_event":
            return f"criar o rascunho de evento «{args['titulo']}» em {args['inicio']}, sem convite"
        if tool_id == "sites.open":
            onde = str(args.get("navegador", "")).strip()
            if not onde and self.navegadores is not None and self.navegadores.principal:
                onde = self.navegadores.principal
            return (
                f"abrir {dominio(str(args['url'])) or args['url']} no "
                f"{'navegador ' + onde if onde else 'seu navegador'}"
            )
        if tool_id == "apps.launch":
            return f"abrir o aplicativo «{args['nome']}»"
        if tool_id in FERRAMENTAS_DE_MEMORIA:
            return f"{self.manifestos[tool_id]['title'].lower()} ({_resumo(args)})"
        if tool_id == "browser.launch":
            return f"abrir o navegador «{args.get('navegador') or 'principal'}»"
        return f"{tool_id} com {json.dumps(dict(args), ensure_ascii=False)[:160]}"

    def _falado(self, tool_id: str, args: Mapping[str, Any]) -> str:
        """A ação dita em voz (ADR-0038): o título da ferramenta e, se houver, o site ou o alvo —
        nunca o id nem os argumentos em JSON, que a janela mostra no `detalhe`."""
        if tool_id in FALADO_IGUAL_AO_DETALHE:
            return self._detalhe(tool_id, args)
        titulo = str(self.manifestos[tool_id]["title"]).strip()
        texto = titulo[:1].lower() + titulo[1:]
        url = args.get("url")
        if isinstance(url, str) and dominio(url):
            texto += f" em {dominio(url)}"
        alvo = args.get("alvo") or args.get("nome")
        if isinstance(alvo, str) and alvo.strip():
            texto += f" «{' '.join(alvo.split())[:60]}»"
        return texto

    def _acompanhar_o_foco(
        self, app: App, pid: int, antes: frozenset[str], do_turno: bool
    ) -> dict[str, Any]:
        """O foco vai para o app quando a janela dele abrir (Lote C, C4; ADR-0037): uma tarefa
        acompanha em segundo plano, sem prender a conversa. Só o que a conversa abriu: tarefa não
        cria tarefa. Sem como ver as janelas, nada muda — como antes."""
        janelas = self.portas().janelas
        if janelas is None or self.tarefas is None or not do_turno:
            return {}
        from jarvis.tarefas.foco import MARGEM_DA_TAREFA_S, MotorDeFoco  # tarefas → executor

        pista = PistaDoApp.do_app(
            app.nome, app.nomes, app.argv, pid, arquivo=app.arquivo, id_do_desktop=app.id
        )
        motor = MotorDeFoco(pista, antes, janelas, prazo_s=self.prazo_do_foco_s)
        try:
            tarefa = self.tarefas.iniciar(
                f"pôr {app.nome} em foco quando a janela abrir",
                "window.focus_app",
                {"app": app.nome[:60]},
                contaminado=self.contaminado,
                motor=motor,
                prazo_s=self.prazo_do_foco_s + MARGEM_DA_TAREFA_S,
            )
        except ValueError as erro:  # TarefaRecusada: o teto de tarefas, ou window.* fora do modo
            return {"foco": f"não vou acompanhar a janela: {erro}"}
        return {
            "foco": "acompanhando: a janela vai para a frente sozinha quando abrir",
            "tarefa_do_foco": tarefa.id,
        }

    def _sugestao_de_app(self, nome: str, motivo: str) -> str:
        try:
            self.registro_de_apps.resolver(nome)
        except AppRecusado as erro:
            return str(erro)
        return motivo


FALADO_IGUAL_AO_DETALHE: Final = frozenset(
    {
        "files.write_draft",
        "calendar.create_draft_event",
        "sites.open",
        "apps.launch",
        "browser.launch",
    }
)
"""As ferramentas cujo `detalhe` já é frase de gente, sem JSON: a voz diz o mesmo que a janela."""


def _resumo(args: Mapping[str, Any]) -> str:
    """Os argumentos em uma linha para o dono ler na confirmação (texto puro, truncado)."""
    return json.dumps(dict(args), ensure_ascii=False)[:160]
