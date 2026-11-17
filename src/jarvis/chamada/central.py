"""A central da chamada: o que o app monta para a ADR-0074 (fatia A), sem Qt e testável com fakes.

Junta as peças que já existiam soltas e as liga ao Jarvis:

- **a chave mestra** `chamadas_ativas` (`chamada.toml`, aba «chamadas»): **desligada por padrão**
  (decisão do dono, 2026-11-17: ele liga depois de testar). Desligada, nada roda — nem o tique,
  nem chamada nova, nem o canal; o que estava pendente continua podendo ser confirmado ou
  recusado no PC e expira normalmente;
- **as ações pendentes** (`AcoesPendentes`, uma por app): cada mudança vira **evento ao Jarvis**
  (`ao_evento` → a fila de avisos da ADR-0070, de terceiros) e, a pendente nova, também vai ao
  agente do canal do dono (quando o canal está ligado e há página);
- **o agente do canal do dono** sobre a página (`PaginaPelaPonte`, real, só com a ponte do
  navegador; `None` nos testes sem página — o envio vira evento «sem página» ao Jarvis);
- **o tique** (`tique`, chamado pelo app de tempos em tempos): expira as pendentes e lê a prévia do
  chat do dono (`ObservadorDoChat`). O que chama o modelo roda no `rodar` (uma linha só, fora da
  janela);
- **a confirmação no PC** (`confirmar_no_pc`/`recusar_no_pc`): o clique na aba «chamadas» — a
  origem `SESSAO_DO_PC`. Por clique, e não por voz: a voz de quem liga pode sair no alto-falante e
  chegar ao microfone do Jarvis;
- **a chamada** (`nova_chamada`): o `AgenteDaChamada` com a `Saida` que o app der (a fonte
  virtual, fatia B). Só com a chave ligada.

O Jarvis recebe a ação confirmada como **evento** (ADR-0070): o turno de eventos não tem
ferramentas, então ele conta ao dono e a execução fica com o pedido do dono — executar sozinho uma
ação que veio de terceiro é decisão que o dono ainda não tomou (registrado na ADR-0074)."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from jarvis.chamada.acoes import AcoesPendentes, Decisao, Origem
from jarvis.chamada.agente import AgenteDaChamada, Chamada, Saida
from jarvis.chamada.canal_do_dono import (
    AgenteDoCanalDoDono,
    GuardaDoCanal,
    ObservadorDoChat,
    PaginaDoWhatsapp,
)
from jarvis.chamada.config import WHATSAPP_DO_DONO, ConfiguracaoDaChamada
from jarvis.chamada.memoria import MemoriaDosInterlocutores, Recados
from jarvis.chamada.totp import Verificador
from jarvis.s2.motor import MotorDeConversa

TIQUE_S = 20.0
"""De quanto em quanto o app chama `tique` (a prévia do chat do dono e a expiração)."""


def rodar_ja(tarefa: Callable[[], None]) -> None:
    """O `rodar` dos testes: na hora, na mesma linha."""
    tarefa()


@dataclass(slots=True)
class CentralDaChamada:
    configuracao: Callable[[], ConfiguracaoDaChamada]
    motor: Callable[[], MotorDeConversa | None]
    ao_evento: Callable[[dict[str, Any]], None]
    """Ao Jarvis: a fila de avisos (ADR-0070), como evento de terceiros."""
    guarda: GuardaDoCanal
    verificador: Verificador
    memoria: MemoriaDosInterlocutores
    recados: Recados
    pagina: PaginaDoWhatsapp | None = None
    saida: Saida | None = None
    rodar: Callable[[Callable[[], None]], None] = rodar_ja
    relogio: Callable[[], float] = time.time
    ao_mudar: Callable[[], None] = lambda: None
    """A tela: as pendentes mudaram (a aba redesenha a lista)."""
    acoes: AcoesPendentes = field(init=False)
    canal: AgenteDoCanalDoDono = field(init=False)
    observador: ObservadorDoChat = field(init=False)

    def __post_init__(self) -> None:
        self.acoes = AcoesPendentes(
            prazo_min=lambda: self.configuracao().acao_expira_min,
            canais=lambda: self.configuracao().canais_de_confirmacao,
            ao_mudar=self._mudou_acao,
            relogio=self.relogio,
        )
        self.canal = AgenteDoCanalDoDono(
            motor=self.motor,
            configuracao=self.configuracao,
            pagina=_PaginaAusente() if self.pagina is None else self.pagina,
            guarda=self.guarda,
            acoes=self.acoes,
            ao_avisar_jarvis=self._ao_jarvis,
        )
        self.observador = ObservadorDoChat(self.canal)

    # --- estado ---------------------------------------------------------------------------
    def ativa(self) -> bool:
        return self.configuracao().chamadas_ativas

    def canal_ligado(self) -> bool:
        return self.ativa() and WHATSAPP_DO_DONO in self.configuracao().canais_de_confirmacao

    def ligar_pagina(self, pagina: PaginaDoWhatsapp) -> None:
        """A janela de verdade liga a aba real do WhatsApp quando a ponte do navegador existe."""
        self.pagina = pagina
        self.canal.pagina = pagina

    def pendentes(self) -> list[dict[str, Any]]:
        return [a.como_dado() for a in self.acoes.pendentes()]

    # --- os eventos -----------------------------------------------------------------------
    def _ao_jarvis(self, evento: dict[str, Any]) -> None:
        self.ao_evento({**evento, "origem": "chamada"})

    def _mudou_acao(self, evento: dict[str, Any]) -> None:
        self._ao_jarvis(evento)
        self.ao_mudar()
        if evento.get("tipo") == "acao_da_chamada_pendente":
            self.para_o_canal(evento)

    def para_o_canal(self, evento: Mapping[str, Any]) -> None:
        """Ao chat do dono, pelo agente do canal — só com a chave e o canal ligados."""
        if not self.canal_ligado():
            return
        if self.pagina is None:
            self._ao_jarvis(
                {
                    "tipo": "canal_do_dono_sem_decisao",
                    "de_terceiros": True,
                    "motivo": "sem_pagina",
                    "evento": str(evento.get("tipo", "")),
                }
            )
            return
        copia = dict(evento)
        self.rodar(lambda: self._enviar(copia))

    def _enviar(self, evento: dict[str, Any]) -> None:
        # `rodar` é uma linha só: o envio e a leitura da prévia nunca correm juntos.
        self.canal.enviar(evento)

    # --- o tique --------------------------------------------------------------------------
    def tique(self) -> None:
        """Expira o que venceu e, com o canal ligado, lê a prévia do chat do dono."""
        self.acoes.expirar()
        if self.canal_ligado() and self.pagina is not None:
            self.rodar(self._conferir)

    def _conferir(self) -> None:
        self.observador.conferir()

    # --- a sessão do PC -------------------------------------------------------------------
    def confirmar_no_pc(self, codigo: str) -> Decisao:
        return self.acoes.confirmar(codigo, Origem.SESSAO_DO_PC)

    def recusar_no_pc(self, codigo: str) -> Decisao:
        return self.acoes.recusar(codigo, Origem.SESSAO_DO_PC)

    # --- a chamada ------------------------------------------------------------------------
    def agente_da_chamada(self, saida: Saida) -> AgenteDaChamada:
        agente = AgenteDaChamada(
            motor=self.motor,
            configuracao=self.configuracao,
            verificador=self.verificador,
            memoria=self.memoria,
            recados=self.recados,
            saida=saida,
            ao_avisar=self._ao_jarvis,
            acoes=self.acoes,
        )
        agente.ao_canal_do_dono = lambda evento: self.para_o_canal(evento)
        # O AgenteDaChamada reaponta acoes.ao_mudar para ele; a central fica com o roteamento.
        self.acoes.ao_mudar = self._mudou_acao
        return agente

    def nova_chamada(self, interlocutor: str, app: str = "") -> Chamada | None:
        """Uma chamada nova, só com a chave ligada e uma saída de voz."""
        if not self.ativa() or self.saida is None:
            return None
        return self.agente_da_chamada(self.saida).nova_chamada(interlocutor, app)


@dataclass(slots=True)
class _PaginaAusente:
    """Sem a ponte do navegador: qualquer leitura falha e vira veredito (nunca envia nada)."""

    def conversas(self) -> list[Any]:
        raise LookupError("sem a aba do WhatsApp: a ponte do navegador não está ligada")

    def abrir(self, identificador: str) -> None:
        raise LookupError("sem a aba do WhatsApp")

    def cabecalho(self) -> Any:
        raise LookupError("sem a aba do WhatsApp")

    def enviar(self, texto: str) -> None:
        raise LookupError("sem a aba do WhatsApp")


__all__ = ["TIQUE_S", "CentralDaChamada", "rodar_ja"]
