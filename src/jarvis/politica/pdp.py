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
* **auditoria antes do efeito**: o grant só existe depois de a decisão estar no log.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from jarvis.barramento.envelope import uuid7
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.canonicalizacao import (
    CaminhoCanonico,
    CaminhoRecusado,
    Sistema,
    canonicalizar,
)
from jarvis.politica.catalogo import Capacidade, allowlist_do_turno
from jarvis.politica.descritor import AberturaRecusada, Identidade, RaizAberta, abrir_raiz
from jarvis.politica.modos import Modo, Raiz, motivo_de_negacao, raizes_do_modo


class Veredito(StrEnum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


RISCOS_QUE_SEMPRE_CONFIRMAM: Final[frozenset[str]] = frozenset(
    {
        "apagar_permanente",
        "sobrescrita_sem_desfazer",
        "lote_acima_do_teto",
        "renomear_em_massa",
        "egress",
        "representacao_do_dono",
        "instalar_ou_executar_baixado",
        "mudanca_de_sistema",
        "elevacao",
        "fora_do_diretorio_do_dono",
    }
)
"""O que continua exigindo confirmação **mesmo no `total`** (§5.5, P13)."""


@dataclass(frozen=True, slots=True)
class Pedido:
    """O que o PDP julga. `args` já normalizados — nunca a frase do usuário."""

    tool_id: str
    args: dict[str, Any]
    caminho: str | None = None
    session_id: str = ""
    call_id: str = ""


@dataclass(frozen=True, slots=True)
class Grant:
    """Autorização com TTL e escopo, amarrada à raiz aberta e à identidade do arquivo."""

    grant_id: str
    tool_id: str
    policy_epoch: int
    modo: Modo
    raiz: str
    identidade: Identidade | None
    expira_em: float
    elevacao: bool = False

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
    def decidir(self, pedido: Pedido) -> Decisao:
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

        if capacidade.risk_class in RISCOS_QUE_SEMPRE_CONFIRMAM:
            return self._registrar(
                pedido,
                Veredito.CONFIRM,
                f"risco {capacidade.risk_class} confirma em qualquer modo",
                canonico,
                capacidade,
            )
        if capacidade.confirmation != "never":
            return self._registrar(
                pedido,
                Veredito.CONFIRM,
                f"manifesto pede confirmação ({capacidade.confirmation})",
                canonico,
                capacidade,
            )
        return self._registrar(
            pedido, Veredito.ALLOW, "dentro do catálogo e da raiz", canonico, capacidade
        )

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
        registro = self.auditoria.registrar_decisao(
            session_id=pedido.session_id or self.session_id,
            policy_epoch=self.policy_epoch,
            modo=str(self.modo),
            tool_id=pedido.tool_id,
            raiz=raiz.caminho.texto if raiz else "",
            caminho=canonico.texto if canonico else "",
            identidade="",
            argv=pedido.args,
            elevacao=bool(capacidade and capacidade.requires_elevation and self.elevacao_ligada),
            grant_id="",
            veredito=str(veredito),
            motivo=motivo,
        )
        grant: Grant | None = None
        if veredito is Veredito.ALLOW:
            grant = Grant(
                grant_id=uuid7(),
                tool_id=pedido.tool_id,
                policy_epoch=self.policy_epoch,
                modo=self.modo,
                raiz=raiz.caminho.texto if raiz else "",
                identidade=None,
                expira_em=time.monotonic() + self.ttl_s,
                elevacao=bool(capacidade and capacidade.requires_elevation),
            )
            self.grants[grant.grant_id] = grant
            if pedido.call_id:
                self.em_voo[pedido.call_id] = grant
        return Decisao(
            veredito=veredito, motivo=motivo, grant=grant, decision_id=registro.decision_id
        )

    # --- abertura sob a raiz do grant ---------------------------------------------
    def abrir_para(self, grant: Grant, relativo: str, *, escrever: bool = False) -> RaizAberta:
        """Abre a raiz do grant e confere identidade antes de qualquer operação."""
        if not grant.valido(policy_epoch=self.policy_epoch):
            raise AberturaRecusada("grant expirado ou de outro policy_epoch")
        aberta = abrir_raiz(Path(grant.raiz))
        if not aberta.ainda_e_a_mesma():
            aberta.fechar()
            raise AberturaRecusada(f"raiz {grant.raiz} mudou de identidade depois do grant")
        return aberta

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
        self.grants.clear()
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
        self.grants.clear()
        return self.modo

    def ligar_elevacao(self, *, dono_presente: bool) -> None:
        if not dono_presente:
            raise PermissionError("elevação só liga com o dono presente na UI (P12)")
        self.elevacao_ligada = True
        self.policy_epoch += 1

    def desligar_elevacao(self) -> None:
        """Desligar é sempre permitido, e vale na hora."""
        self.elevacao_ligada = False
        self.policy_epoch += 1
