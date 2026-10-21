"""Policy Decision Point determinístico (SPEC §5, §5.5; ADR-0003, ADR-0009).

Regras que este módulo materializa:

* **o código autoriza** (P1): a decisão sai de `tool_id` + argumentos normalizados + modo +
  manifesto + lista de negação, sem consultar o LLM e sem ler campo de política vindo de
  conteúdo;
* **a lista de negação vence até no `total`** e é `deny`, nunca `confirm`;
* **mais alcance não é menos rigor** (P13): a matriz de confirmação não afrouxa quando o
  modo cresce — o mesmo pedido que pede confirmação no `jarvis` pede no `total`;
* **nível e elevação só mudam pela UI, com o dono presente** (P12): reduzir vale na hora e
  cancela o que está em voo; ampliar exige confirmação explícita;
* **auditoria antes do efeito**: o grant só existe depois de a decisão estar no log;
* **a raiz é aberta no grant** (§5.5): o grant guarda o descritor e a identidade
  (`device:inode`) do instante da decisão, e o uso acontece sobre esse descritor. Decidir sobre
  o texto do caminho e abrir depois seria autorizar um nome, não um objeto.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from jarvis.barramento.envelope import uuid7
from jarvis.politica.abertura import decidir_abertura
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.canonicalizacao import (
    CaminhoCanonico,
    CaminhoRecusado,
    Sistema,
    canonicalizar,
)
from jarvis.politica.catalogo import RISCOS_QUE_SEMPRE_CONFIRMAM, Capacidade, allowlist_do_turno
from jarvis.politica.descritor import AberturaRecusada, Identidade, RaizAberta, abrir_raiz
from jarvis.politica.memoria import AlcanceDeMemoria, Proveniencia, decidir_memoria
from jarvis.politica.modos import Modo, Raiz, motivo_de_negacao, raizes_do_modo
from jarvis.politica.objetivo import Objetivo
from jarvis.politica.vocabulario import decidir_vocabulario


class Veredito(StrEnum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


TETO_DE_RAIZES_ABERTAS: Final = 128
"""Cada grant com raiz segura um descritor até expirar: o teto é o orçamento de `fd`.

Com TTL de 60 s, 128 é mais do que a mão do dono produz num minuto, e bater no teto **nega**
(falha fechada) em vez de vazar descritor em silêncio. A varredura dos vencidos acontece antes,
em toda decisão, então chegar aqui significa 128 grants vivos ao mesmo tempo.
"""


@dataclass(frozen=True, slots=True)
class Pedido:
    """O que o PDP julga. `args` já normalizados — nunca a frase do usuário."""

    tool_id: str
    args: dict[str, Any]
    caminho: str | None = None
    session_id: str = ""
    call_id: str = ""
    proveniencia: Proveniencia | None = None
    """Só para `memoria.*` (ADR-0026): o turno de origem, montado pelo `s2`, nunca pelo modelo."""
    contaminado: bool = False
    """Este turno já leu conteúdo de terceiros (arquivo, página, memória): quem diz é o executor,
    que viu os resultados passarem — nunca o modelo. Aperta o que é livre e sai da máquina."""
    objetivo: Objetivo | None = None
    """O objetivo do turno (`jarvis.politica.objetivo`): nasce da fala do dono e cresce com o que
    as ferramentas do objetivo alcançaram — quem monta é o executor, nunca o modelo. Dentro dele,
    navegar não pergunta mesmo com o turno contaminado; dado do dono para site não citado, sim."""
    exige_o_sim: str = ""
    """Por que **este alvo** pede o sim, dito pelo executor depois de resolvê-lo (ADR-0041,
    ADR-0042): uma tarefa em andamento ao encerrar o Jarvis; trabalho que pode não estar salvo, mais
    de uma instância, o navegador do dono ou coisa do sistema ao encerrar um app. Vazio = o tier
    decide. Não há argumento do modelo que chegue aqui: o campo é do código, como `contaminado`."""


@dataclass(frozen=True, slots=True)
class Grant:
    """Autorização com TTL e escopo, amarrada à raiz aberta e à identidade do arquivo.

    `fd` e `identidade` vêm do instante da decisão. Quem fecha o `fd` é o `Pdp` (expiração,
    redução de modo, ampliação confirmada e mudança de elevação), e o dono do descritor é o
    `Pdp.abrir_para` — não o chamador, que recebe a raiz já aberta e conferida.
    """

    grant_id: str
    tool_id: str
    policy_epoch: int
    modo: Modo
    raiz: str
    identidade: Identidade | None
    expira_em: float
    elevacao: bool = False
    fd: int | None = None

    def valido(self, *, policy_epoch: int, agora: float | None = None) -> bool:
        instante = time.monotonic() if agora is None else agora
        return instante < self.expira_em and policy_epoch == self.policy_epoch


@dataclass(frozen=True, slots=True)
class Decisao:
    veredito: Veredito
    motivo: str
    grant: Grant | None = None
    decision_id: str = ""


@dataclass(slots=True)
class Pdp:
    """Estado de política de uma sessão. Mudança de modo é evento, não ajuste silencioso."""

    catalogo: dict[str, Capacidade]
    lar: Path
    auditoria: LogDeAuditoria
    modo: Modo = Modo.JARVIS
    elevacao_ligada: bool = False
    sistema: Sistema = Sistema.POSIX
    session_id: str = ""
    pasta_do_jarvis: Path | None = None
    concedidas: tuple[Raiz, ...] = ()
    ttl_s: float = 60.0
    policy_epoch: int = 0
    grants: dict[str, Grant] = field(default_factory=dict)
    em_voo: dict[str, Grant] = field(default_factory=dict)
    cancelados: list[str] = field(default_factory=list)
    ampliacao_pendente: Modo | None = None
    alcance_de_memoria: AlcanceDeMemoria = field(default_factory=AlcanceDeMemoria)
    escrita_autonoma_liberada: bool = False
    apps_autorizados: frozenset[str] = frozenset()
    """Nomes normalizados dos apps que o dono pôs no registro: o grant estreito de `apps.launch`."""
    sites_sem_confirmar: frozenset[str] = frozenset()
    """Domínios que o dono liberou para `sites.open` abrir sem perguntar (com subdomínios)."""
    navegadores: frozenset[str] = frozenset()
    """As famílias de navegador que o dono configurou: o grant estreito de `browser.launch`."""
    navegador_principal: str = ""
    """ADR-0026, M4: só vira verdade quando os seis gates da §6.6 passarem (aceite (a) da F3)."""
    _raizes: dict[str, RaizAberta] = field(default_factory=dict, repr=False)
    """Raiz aberta de cada grant vivo, por `grant_id`. É aqui que o descritor tem dono."""
    _trava: threading.RLock = field(default_factory=threading.RLock, repr=False)
    """A conversa e as tarefas em segundo plano decidem ao mesmo tempo: grants e raízes abertas
    são do PDP, e quem os mexe (decidir, abrir, expirar) o faz um de cada vez."""

    # --- catálogo -----------------------------------------------------------------
    def allowlist(self) -> tuple[str, ...]:
        """O que o planejador vê neste turno (filtro de elevação antes do modelo)."""
        return allowlist_do_turno(
            self.catalogo, modo=self.modo, elevacao_ligada=self.elevacao_ligada
        )

    def raizes(self) -> tuple[Raiz, ...]:
        return raizes_do_modo(
            self.modo,
            lar=self.lar,
            pasta_do_jarvis=self.pasta_do_jarvis,
            concedidas=self.concedidas,
            sistema=self.sistema,
        )

    # --- decisão ------------------------------------------------------------------
    def decidir(self, pedido: Pedido, *, confirmado_pelo_dono: bool = False) -> Decisao:
        with self._trava:
            return self._decidir(pedido, confirmado_pelo_dono=confirmado_pelo_dono)

    def _decidir(self, pedido: Pedido, *, confirmado_pelo_dono: bool = False) -> Decisao:
        """`allow | confirm | deny` para o pedido, registrado antes de devolver.

        `confirmado_pelo_dono` só é verdadeiro quando o **dono** respondeu "sim" na janela a uma
        decisão `confirm` desta mesma chamada (ADR-0027). Não existe campo do pedido, argumento
        do modelo ou ação do vocabulário que o liguem: quem o passa é o executor, e só depois da
        resposta da UI. Ele troca `confirm` por `allow` — **nunca** troca `deny` por nada.
        """
        capacidade = self.catalogo.get(pedido.tool_id)
        if capacidade is None:
            return self._registrar(pedido, Veredito.DENY, "tool fora do catálogo", None, None)
        if pedido.tool_id not in self.allowlist():
            motivo = (
                "exige elevação, que está desligada"
                if capacidade.requires_elevation and not self.elevacao_ligada
                else f"exige modo {capacidade.access_level_min} (atual: {self.modo})"
            )
            return self._registrar(pedido, Veredito.DENY, motivo, None, capacidade)

        regra = decidir_memoria(
            pedido.tool_id,
            pedido.args,
            pedido.proveniencia,
            alcance=self.alcance_de_memoria,
            escrita_autonoma_liberada=self.escrita_autonoma_liberada,
        )
        if regra is None:
            regra = decidir_abertura(
                pedido.tool_id,
                pedido.args,
                apps_autorizados=self.apps_autorizados,
                sites_sem_confirmar=self.sites_sem_confirmar,
                navegadores=self.navegadores,
                navegador_principal=self.navegador_principal,
                contaminado=pedido.contaminado,
                objetivo=pedido.objetivo,
            )
        if regra is None:
            # ADR-0044: gravar um nome no vocabulário do dono pede o turno dele como origem, e o
            # sim quando o turno leu conteúdo de fora (a "correção" pode ter vindo de uma página).
            regra = decidir_vocabulario(
                pedido.tool_id, proveniencia=pedido.proveniencia, contaminado=pedido.contaminado
            )
        if regra is not None and regra.veredito == "confirm":
            # A regra apertou o que o tier deixaria livre (ex.: site fora da lista, depois de o
            # turno ler uma página): confirma — e só o "sim" do dono na janela solta.
            if confirmado_pelo_dono:
                return self._registrar(
                    pedido,
                    Veredito.ALLOW,
                    f"confirmado pelo dono na janela — {regra.motivo}",
                    None,
                    capacidade,
                )
            return self._registrar(pedido, Veredito.CONFIRM, regra.motivo, None, capacidade)
        if regra is not None:
            # ADR-0026: a política de memória decide antes da matriz comum — nega o que não tem
            # origem, e o grant de turno libera só o que é fala literal do dono neste turno.
            return self._registrar(pedido, Veredito(regra.veredito), regra.motivo, None, capacidade)
        if pedido.exige_o_sim:
            # O alvo que o executor resolveu aperta o que o tier deixaria passar (ADR-0041/0042):
            # confirma, e só o "sim" do dono solta.
            if confirmado_pelo_dono:
                return self._registrar(
                    pedido,
                    Veredito.ALLOW,
                    f"confirmado pelo dono na janela — {pedido.exige_o_sim}",
                    None,
                    capacidade,
                )
            return self._registrar(pedido, Veredito.CONFIRM, pedido.exige_o_sim, None, capacidade)

        canonico: CaminhoCanonico | None = None
        raiz_escolhida: Raiz | None = None
        if pedido.caminho is not None:
            try:
                canonico = canonicalizar(pedido.caminho, self.sistema)
            except CaminhoRecusado as erro:
                return self._registrar(
                    pedido, Veredito.DENY, f"forma de caminho: {erro}", None, capacidade
                )

            negado = motivo_de_negacao(canonico, self.lar, self.sistema)
            if negado is not None:
                # §5.5: ler cofre de segredo é negado, não confirmável.
                return self._registrar(pedido, Veredito.DENY, negado, canonico, capacidade)

            raiz_escolhida = self._raiz_de(canonico)
            if raiz_escolhida is None:
                return self._registrar(
                    pedido, Veredito.DENY, "caminho fora das raízes do modo", canonico, capacidade
                )
            if capacidade.side_effect != "none" and not raiz_escolhida.pode_escrever:
                return self._registrar(
                    pedido,
                    Veredito.DENY,
                    f"raiz {raiz_escolhida.nome} é só de leitura",
                    canonico,
                    capacidade,
                )

        confirmar: str | None = None
        if capacidade.risk_class in RISCOS_QUE_SEMPRE_CONFIRMAM:
            confirmar = f"risco {capacidade.risk_class} confirma em qualquer modo"
        elif capacidade.tier == "perigoso":
            confirmar = (
                "perigoso: só com a confirmação do dono (irreversível, envia, gasta, instala)"
            )
        elif capacidade.confirmation != "never":
            confirmar = f"manifesto pede confirmação ({capacidade.confirmation})"
        if confirmar is not None:
            if confirmado_pelo_dono:
                return self._registrar(
                    pedido,
                    Veredito.ALLOW,
                    f"confirmado pelo dono na janela — {confirmar}",
                    canonico,
                    capacidade,
                )
            return self._registrar(pedido, Veredito.CONFIRM, confirmar, canonico, capacidade)
        motivo = {
            "livre": "livre: dentro do catálogo e da raiz",
            "moderado": "moderado: sem confirmação; o Jarvis avisa em voz, a auditoria registra",
        }.get(capacidade.tier, "dentro do catálogo e da raiz")
        return self._registrar(pedido, Veredito.ALLOW, motivo, canonico, capacidade)

    def _raiz_de(self, caminho: CaminhoCanonico) -> Raiz | None:
        candidatas = [r for r in self.raizes() if caminho.dentro_de(r.caminho)]
        if not candidatas:
            return None
        return max(candidatas, key=lambda r: len(r.caminho.partes))  # a mais específica

    def _registrar(
        self,
        pedido: Pedido,
        veredito: Veredito,
        motivo: str,
        canonico: CaminhoCanonico | None,
        capacidade: Capacidade | None,
    ) -> Decisao:
        """Escreve a decisão **antes** de devolver o grant (§5.5)."""
        raiz = self._raiz_de(canonico) if canonico is not None else None
        aberta: RaizAberta | None = None
        if veredito is Veredito.ALLOW and raiz is not None:
            # §5.5: a raiz é aberta AQUI, no instante da decisão, e é este descritor que o uso
            # recebe. Abrir só na hora do uso deixaria o grant valendo sobre o texto do caminho:
            # trocar a pasta entre a decisão e o uso passaria sem ninguém notar.
            self.expirar()
            if len(self._raizes) >= TETO_DE_RAIZES_ABERTAS:
                veredito = Veredito.DENY
                motivo = f"teto de {TETO_DE_RAIZES_ABERTAS} raízes abertas ao mesmo tempo"
            else:
                try:
                    aberta = abrir_raiz(Path(raiz.caminho.texto))
                except (AberturaRecusada, OSError) as erro:
                    veredito = Veredito.DENY
                    motivo = f"raiz {raiz.nome} não abriu no grant: {erro}"
        registro = self.auditoria.registrar_decisao(
            session_id=pedido.session_id or self.session_id,
            policy_epoch=self.policy_epoch,
            modo=str(self.modo),
            tool_id=pedido.tool_id,
            raiz=raiz.caminho.texto if raiz else "",
            caminho=canonico.texto if canonico else "",
            identidade=str(aberta.identidade) if aberta is not None else "",
            argv=pedido.args,
            elevacao=bool(capacidade and capacidade.requires_elevation and self.elevacao_ligada),
            grant_id="",
            veredito=str(veredito),
            motivo=motivo,
            sessao_contaminada=pedido.contaminado,
        )
        grant: Grant | None = None
        if veredito is Veredito.ALLOW:
            grant = Grant(
                grant_id=uuid7(),
                tool_id=pedido.tool_id,
                policy_epoch=self.policy_epoch,
                modo=self.modo,
                raiz=raiz.caminho.texto if raiz else "",
                identidade=aberta.identidade if aberta is not None else None,
                expira_em=time.monotonic() + self.ttl_s,
                elevacao=bool(capacidade and capacidade.requires_elevation),
                fd=aberta.fd if aberta is not None else None,
            )
            self.grants[grant.grant_id] = grant
            if aberta is not None:
                self._raizes[grant.grant_id] = aberta
            if pedido.call_id:
                self.em_voo[pedido.call_id] = grant
        elif aberta is not None:  # pragma: no cover — só se o veredito virar DENY depois de abrir
            aberta.fechar()
        return Decisao(
            veredito=veredito, motivo=motivo, grant=grant, decision_id=registro.decision_id
        )

    # --- abertura sob a raiz do grant ---------------------------------------------
    def abrir_para(self, grant: Grant, relativo: str, *, escrever: bool = False) -> RaizAberta:
        with self._trava:
            return self._abrir_para(grant, relativo, escrever=escrever)

    def _abrir_para(self, grant: Grant, relativo: str, *, escrever: bool = False) -> RaizAberta:
        """Devolve a raiz **aberta no grant**, conferida; o alvo abre relativo a ela.

        Nada é reaberto pelo texto do caminho: o descritor é o do instante da decisão, guardado
        em `_raizes`. A conferência de `relativo` e de `escrever` é do `RaizAberta.abrir`, que
        atravessa sob este mesmo descritor (`RESOLVE_BENEATH`).
        """
        if not grant.valido(policy_epoch=self.policy_epoch):
            self._fechar_raiz(grant.grant_id)
            self.grants.pop(grant.grant_id, None)
            raise AberturaRecusada("grant expirado ou de outro policy_epoch")
        aberta = self._raizes.get(grant.grant_id)
        if aberta is None or grant.identidade is None:
            raise AberturaRecusada(
                f"grant {grant.grant_id} não tem raiz aberta: decisão sem caminho, "
                "raiz já fechada ou grant de outra sessão"
            )
        if not aberta.ainda_e_a_mesma():
            # O descritor continua apontando para o que foi autorizado; é o CAMINHO que passou a
            # ser outro objeto. Seguir seria usar o grant sobre conteúdo que a auditoria não viu.
            raise AberturaRecusada(f"raiz {grant.raiz} mudou de identidade depois do grant")
        return aberta

    def expirar(self, *, agora: float | None = None) -> list[str]:
        """Fecha a raiz dos grants vencidos e os esquece. Toda decisão varre antes de conceder."""
        instante = time.monotonic() if agora is None else agora
        mortos = [
            g.grant_id
            for g in self.grants.values()
            if not g.valido(policy_epoch=self.policy_epoch, agora=instante)
        ]
        for grant_id in mortos:
            self._fechar_raiz(grant_id)
            self.grants.pop(grant_id, None)
        return mortos

    def liberar(self, grant_id: str) -> None:
        """O grant não vai ser usado (o portão vetou a chamada ou ela virou pendência): sai já,
        com a raiz fechada, em vez de esperar o TTL."""
        with self._trava:
            self._fechar_raiz(grant_id)
            self.grants.pop(grant_id, None)
            for call_id, grant in list(self.em_voo.items()):
                if grant.grant_id == grant_id:
                    self.em_voo.pop(call_id, None)

    def _fechar_raiz(self, grant_id: str) -> None:
        """Fecha o descritor de um grant **uma vez**: quem sai do dicionário não volta.

        Fechar duas vezes é pior do que não fechar: o número do descritor é reaproveitado pelo
        sistema, e um grant velho passaria a apontar para um objeto novo.
        """
        aberta = self._raizes.pop(grant_id, None)
        if aberta is not None:
            aberta.fechar()

    def _descartar_grants(self) -> None:
        """Mudou o `policy_epoch`: todo grant morreu e nenhum descritor pode sobreviver."""
        for grant_id in list(self._raizes):
            self._fechar_raiz(grant_id)
        self.grants.clear()

    # --- mudança de modo e de elevação (só pela UI, P12) --------------------------
    def reduzir(self, novo: Modo) -> list[str]:
        """Reduzir vale **na hora** e cancela chamadas em voo (§5.5)."""
        if novo.amplitude >= self.modo.amplitude:
            raise ValueError(f"{novo} não é mais estreito que {self.modo}")
        self.modo = novo
        self.policy_epoch += 1
        cancelados = list(self.em_voo)
        self.cancelados += cancelados
        self.em_voo.clear()
        self._descartar_grants()
        return cancelados

    def pedir_ampliacao(self, novo: Modo) -> Modo:
        """Ampliar **não** vale sozinho: fica pendente até a confirmação do dono na UI."""
        if novo.amplitude <= self.modo.amplitude:
            raise ValueError(f"{novo} não amplia {self.modo}")
        self.ampliacao_pendente = novo
        return novo

    def confirmar_ampliacao(self, *, dono_presente: bool) -> Modo:
        if self.ampliacao_pendente is None:
            raise ValueError("não há ampliação pendente")
        if not dono_presente:
            raise PermissionError("ampliar modo exige o dono presente na UI (P12)")
        self.modo = self.ampliacao_pendente
        self.ampliacao_pendente = None
        self.policy_epoch += 1
        self._descartar_grants()
        return self.modo

    def ligar_elevacao(self, *, dono_presente: bool) -> None:
        if not dono_presente:
            raise PermissionError("elevação só liga com o dono presente na UI (P12)")
        self.elevacao_ligada = True
        self.policy_epoch += 1
        self._descartar_grants()

    def desligar_elevacao(self) -> None:
        """Desligar é sempre permitido, e vale na hora."""
        self.elevacao_ligada = False
        self.policy_epoch += 1
        self._descartar_grants()
