"""As ações pedidas numa chamada, à espera da confirmação do dono (ADR-0074).

Decisão do dono (2026-11-17): qualquer ação pedida numa ligação — por quem liga ou pelo dono
reconhecido pelo TOTP — só acontece depois de o dono confirmar **pelo canal dele**: a sessão aberta
no PC e, se ele configurou o chat dele no WhatsApp Web (`contato_do_dono_whatsapp`), uma resposta
nesse chat com o **código** da ação. O que se diz na chamada nunca confirma nada.

Este módulo é a trava, no código, e não decide pelo Jarvis:

- `propor` registra a ação com um código aleatório (6 caracteres de um alfabeto sem letras
  parecidas) e um prazo (`acao_expira_min`, padrão 10 min); o evento vai ao Jarvis e, com o
  canal ligado, ao agente do canal do dono — que redige a mensagem ao dono;
- `confirmar`/`recusar` só aceitam a origem `SESSAO_DO_PC` ou `CANAL_DO_DONO` (um enum que só o
  código passa: o modelo da chamada não tem como escolher a origem). Pelo canal do dono, a
  mensagem do dono tem de trazer o código **desta** ação como palavra inteira; quem decide se a
  mensagem é um «sim» ou um «não» é o agente do canal (julgamento do modelo), não um padrão aqui;
- `expirar` fecha a que passou do prazo e avisa o Jarvis (o código dela não vale mais).

A ação confirmada vira evento ao Jarvis, que a executa com as permissões de sempre — confirmar
aqui não dá poder nenhum além do que o Jarvis já teria com o dono presente. Tudo em memória: o
app fechado perde as pendentes (expiram, de fato)."""

from __future__ import annotations

import secrets
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

ALFABETO: Final = "ACDEFHJKMNPRTUVWXY3479"
"""Sem 0/O, 1/I/L, 2/Z, 5/S, 6/G, 8/B: dá para ler e digitar no celular sem confundir."""
TAMANHO_DO_CODIGO: Final = 6
CARACTERES_DA_ACAO: Final = 300
PENDENTES_NO_MAXIMO: Final = 5
"""Mais que isto numa janela de prazo é abuso: a proposta volta recusada ao agente."""


class Origem(Enum):
    """De onde vem uma confirmação. Só o código monta: nenhuma ferramenta recebe isto do modelo."""

    SESSAO_DO_PC = "sessao_do_pc"
    CANAL_DO_DONO = "whatsapp_do_dono"
    CHAMADA = "chamada"


ORIGENS_QUE_CONFIRMAM: Final = frozenset({Origem.SESSAO_DO_PC, Origem.CANAL_DO_DONO})


@dataclass(slots=True)
class AcaoPendente:
    codigo: str
    acao: str
    detalhes: str
    interlocutor: str
    app: str
    pedida_pelo_dono_reconhecido: bool
    criada: float
    expira: float
    estado: str = "pendente"
    """`pendente`, `confirmada`, `recusada` ou `expirada`."""
    via: str = ""

    def como_dado(self) -> dict[str, Any]:
        return {
            "codigo": self.codigo,
            "acao": self.acao,
            "detalhes": self.detalhes,
            "interlocutor": self.interlocutor,
            "app": self.app,
            "pedida_pelo_dono_reconhecido_por_totp": self.pedida_pelo_dono_reconhecido,
            "estado": self.estado,
            "expira_em_s": max(0, round(self.expira - self.criada)),
        }


@dataclass(frozen=True, slots=True)
class Decisao:
    aceita: bool
    motivo: str
    """`confirmada`, `recusada`, ou o porquê da recusa: `origem`, `canal_desligado`,
    `desconhecida`, `encerrada`, `expirada`, `sem_codigo`."""


def palavras(texto: str) -> set[str]:
    """As palavras do texto, em maiúsculas e sem acento: só para achar o código inteiro."""
    base = unicodedata.normalize("NFKD", texto)
    limpo = "".join(c if c.isalnum() else " " for c in base if not unicodedata.combining(c))
    return set(limpo.upper().split())


def novo_codigo() -> str:
    return "".join(secrets.choice(ALFABETO) for _ in range(TAMANHO_DO_CODIGO))


@dataclass(slots=True)
class AcoesPendentes:
    prazo_min: Callable[[], int]
    canais: Callable[[], tuple[str, ...]]
    """Os canais ligados agora (`ConfiguracaoDaChamada.canais_de_confirmacao`)."""
    ao_mudar: Callable[[dict[str, Any]], None]
    """Cada mudança vira evento: ao Jarvis e, com o canal ligado, ao agente do canal do dono."""
    relogio: Callable[[], float] = time.time
    gerar_codigo: Callable[[], str] = novo_codigo
    _acoes: dict[str, AcaoPendente] = field(default_factory=dict)

    def pendentes(self) -> list[AcaoPendente]:
        self.expirar()
        return [a for a in self._acoes.values() if a.estado == "pendente"]

    def acao(self, codigo: str) -> AcaoPendente | None:
        return self._acoes.get(codigo.strip().upper())

    def propor(
        self,
        acao: str,
        detalhes: str,
        *,
        interlocutor: str,
        app: str,
        dono_reconhecido: bool,
    ) -> AcaoPendente | None:
        """Registra e avisa. `None` se já há pendentes demais (o agente recebe a recusa)."""
        if len(self.pendentes()) >= PENDENTES_NO_MAXIMO:
            return None
        agora = self.relogio()
        codigo = self.gerar_codigo()
        while codigo in self._acoes:
            codigo = self.gerar_codigo()
        pendente = AcaoPendente(
            codigo=codigo,
            acao=" ".join(acao.split())[:CARACTERES_DA_ACAO],
            detalhes=" ".join(detalhes.split())[:CARACTERES_DA_ACAO],
            interlocutor=interlocutor,
            app=app,
            pedida_pelo_dono_reconhecido=dono_reconhecido,
            criada=agora,
            expira=agora + self.prazo_min() * 60.0,
        )
        self._acoes[codigo] = pendente
        self._avisar("acao_da_chamada_pendente", pendente)
        return pendente

    def _avisar(self, tipo: str, pendente: AcaoPendente) -> None:
        self.ao_mudar(
            {
                "tipo": tipo,
                "de_terceiros": True,
                "acao_pendente": pendente.como_dado(),
                "confirmacao_por": list(self.canais()),
                **({"confirmada_pelo_dono_via": pendente.via} if pendente.via else {}),
            }
        )

    def expirar(self) -> list[AcaoPendente]:
        agora = self.relogio()
        vencidas = [a for a in self._acoes.values() if a.estado == "pendente" and agora >= a.expira]
        for pendente in vencidas:
            pendente.estado = "expirada"
            self._avisar("acao_da_chamada_expirou", pendente)
        return vencidas

    def _decidir(self, codigo: str, origem: Origem, evidencia: str, estado: str) -> Decisao:
        if origem not in ORIGENS_QUE_CONFIRMAM:
            return Decisao(False, "origem")
        if origem is Origem.CANAL_DO_DONO and origem.value not in self.canais():
            return Decisao(False, "canal_desligado")
        self.expirar()
        pendente = self.acao(codigo)
        if pendente is None:
            return Decisao(False, "desconhecida")
        if pendente.estado == "expirada":
            return Decisao(False, "expirada")
        if pendente.estado != "pendente":
            return Decisao(False, "encerrada")
        if origem is Origem.CANAL_DO_DONO and pendente.codigo not in palavras(evidencia):
            return Decisao(False, "sem_codigo")
        pendente.estado = estado
        pendente.via = origem.value
        self._avisar(
            "acao_da_chamada_confirmada" if estado == "confirmada" else "acao_da_chamada_recusada",
            pendente,
        )
        return Decisao(True, estado)

    def confirmar(self, codigo: str, origem: Origem, evidencia: str = "") -> Decisao:
        """`evidencia`: pelo canal do dono, o texto da mensagem dele (tem de trazer o código)."""
        return self._decidir(codigo, origem, evidencia, "confirmada")

    def recusar(self, codigo: str, origem: Origem, evidencia: str = "") -> Decisao:
        return self._decidir(codigo, origem, evidencia, "recusada")


__all__ = [
    "ALFABETO",
    "ORIGENS_QUE_CONFIRMAM",
    "PENDENTES_NO_MAXIMO",
    "AcaoPendente",
    "AcoesPendentes",
    "Decisao",
    "Origem",
    "novo_codigo",
    "palavras",
]
