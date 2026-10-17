"""A fila de avisos do `agentd` (ADR-0025, regras 11–15; limiares D22).

Decisão do dono (2026-10-16): o Jarvis recebe a notificação e **decide sozinho** se avisa;
**nunca corta fala** em curso; o aviso espera o TTS parar ou a mensagem do dono e vai junto com
ela; também pode aparecer como card. A fila mora aqui porque só o `agentd` sabe se o piso está
livre — fala do dono (`AudioActivity`) e TTS tocando. Quem decide falar, card ou calar é o `s2`
(`jarvis.s2.avisos`); a fila só **libera** e **registra o que aconteceu**.

O que o código impõe, por cima do julgamento do modelo:

- **nunca por cima da fala**: a liberação espontânea (`piso_livre`) só sai com o dono calado, o
  TTS parado e `PISO_LIVRE_S` de silêncio depois dos dois (D22: 1,5 s);
- **teto de fala espontânea**: no máximo um aviso falado a cada `TETO_DE_FALA_S` (D22: 2 min), e
  um por vez. O teto **não** vale para o aviso que vai junto com a mensagem do dono: ali quem
  abriu a conversa foi ele, e esperar 2 min para contar que a tarefa terminou seria esconder;
- **entregue é o que tocou** (regra 15, P4): o aviso só vira `falado` quando os pedaços que o
  carregam tocaram inteiros; cortado antes disso, volta para a fila;
- **não perturbe** = só card; **privacidade** = nada sai em voz; e nada some: calado e só-card
  continuam no card.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

from jarvis.barramento.contrato import prioridade_canonica, validar
from jarvis.barramento.envelope import Envelope, Tipo, Trust

PISO_LIVRE_S: Final = 1.5
"""D22 (diretor, 2026-10-16): silêncio, depois da fala do dono e do TTS, para o piso estar livre."""
TETO_DE_FALA_S: Final = 120.0
"""D22: no máximo um aviso falado espontaneamente a cada 2 minutos."""
LIMITE_DO_CARD: Final = 24
"""O mesmo `LIMITE_DE_ITENS` do componente: o card mostra os mais recentes."""


class Entrega(StrEnum):
    """O que foi feito do aviso — os valores são os do card `notificacoes`."""

    NA_FILA = "na_fila"
    FALADO = "falado"
    SO_CARD = "so_card"
    CALADO = "calado"


class Motivo(StrEnum):
    PISO_LIVRE = "piso_livre"
    MENSAGEM_DO_DONO = "mensagem_do_dono"


@dataclass(slots=True)
class Aviso:
    notif_id: str
    origem: str
    tipo: str
    resumo: str
    trust: str
    recebido_em: float
    entrega: Entrega = Entrega.NA_FILA
    liberado: bool = False
    """Saiu num `NotificationRelease` e espera o `s2` decidir ou o pedaço tocar."""

    @property
    def pendente(self) -> bool:
        return self.entrega is Entrega.NA_FILA and not self.liberado


@dataclass(slots=True)
class FilaDeAvisos:
    session_id: str
    piso_livre_s: float = PISO_LIVRE_S
    teto_de_fala_s: float = TETO_DE_FALA_S
    nao_perturbe: bool = False
    privacidade: bool = False
    avisos: dict[str, Aviso] = field(default_factory=dict)
    _dono_falando: bool = False
    _tts_tocando: bool = False
    _silencio_desde: float | None = 0.0
    _ultimo_falado: float | None = None

    # --- entrada ----------------------------------------------------------------------
    def receber(self, envelope: Envelope, agora: float) -> Aviso:
        """Um `Notification` entra na fila. Repetido (mesmo `notif_id`) não duplica."""
        if envelope.type is not Tipo.NOTIFICATION:
            raise ValueError(f"a fila recebe Notification, veio {envelope.type}")
        payload = envelope.payload
        identificador = str(payload["notif_id"])
        if identificador in self.avisos:
            return self.avisos[identificador]
        aviso = Aviso(
            notif_id=identificador,
            origem=str(payload["origem"]),
            tipo=str(payload["tipo"]),
            resumo=str(payload["resumo"]),
            trust=str(envelope.trust),
            recebido_em=agora,
        )
        if self.nao_perturbe:
            aviso.entrega = Entrega.SO_CARD
        self.avisos[identificador] = aviso
        return aviso

    # --- o piso -----------------------------------------------------------------------
    def observar(self, envelope: Envelope, agora: float) -> None:
        """`AudioActivity` diz se o dono está falando; o resto não muda o piso."""
        if envelope.type is Tipo.AUDIO_ACTIVITY:
            self._mudar(dono=bool(envelope.payload["speech"]), agora=agora)

    def dono_falando(self, falando: bool, agora: float) -> None:
        self._mudar(dono=falando, agora=agora)

    def tts_tocando(self, tocando: bool, agora: float) -> None:
        self._mudar(tts=tocando, agora=agora)

    def piso_livre(self, agora: float) -> bool:
        return (
            not self._dono_falando
            and not self._tts_tocando
            and self._silencio_desde is not None
            and agora - self._silencio_desde >= self.piso_livre_s
        )

    def _mudar(self, *, agora: float, dono: bool | None = None, tts: bool | None = None) -> None:
        if dono is not None:
            self._dono_falando = dono
        if tts is not None:
            self._tts_tocando = tts
        ocupado = self._dono_falando or self._tts_tocando
        if ocupado:
            self._silencio_desde = None
        elif self._silencio_desde is None:
            self._silencio_desde = agora

    # --- liberação --------------------------------------------------------------------
    def liberar(self, agora: float) -> Envelope | None:
        """Liberação espontânea: **um** aviso, com o piso livre e o teto de fala respeitado."""
        if self.privacidade or self.nao_perturbe or not self.piso_livre(agora):
            return None
        if self._ultimo_falado is not None and agora - self._ultimo_falado < self.teto_de_fala_s:
            return None
        if any(a.liberado for a in self.avisos.values()):
            return None  # um por vez: o liberado ainda não tocou, não foi cortado nem decidido
        pendentes = self._pendentes()
        if not pendentes:
            return None
        # Pedido de decisão primeiro: é o que trava alguma coisa até o dono responder.
        escolhido = sorted(pendentes, key=lambda a: (a.tipo != "precisa_decisao", a.recebido_em))[0]
        return self._liberacao([escolhido], Motivo.PISO_LIVRE)

    def mensagem_do_dono(self, turn_id: str, agora: float) -> Envelope | None:
        """Chegou mensagem do dono: todos os pendentes vão junto com ela (decisão do dono)."""
        del agora
        if self.privacidade or self.nao_perturbe:
            return None
        pendentes = self._pendentes()
        if not pendentes:
            return None
        return self._liberacao(pendentes, Motivo.MENSAGEM_DO_DONO, turn_id=turn_id)

    def _pendentes(self) -> list[Aviso]:
        return [a for a in self.avisos.values() if a.pendente]

    def _liberacao(self, avisos: Sequence[Aviso], motivo: Motivo, *, turn_id: str = "") -> Envelope:
        for aviso in avisos:
            aviso.liberado = True
        payload: dict[str, Any] = {
            "notif_ids": [a.notif_id for a in avisos],
            "motivo": str(motivo),
        }
        if turn_id:
            payload["turn_id"] = turn_id
        return validar(
            Envelope(
                session_id=self.session_id,
                epoch=0,
                source="agentd",
                trust=Trust.SYSTEM,
                priority=prioridade_canonica(Tipo.NOTIFICATION_RELEASE, payload),
                type=Tipo.NOTIFICATION_RELEASE,
                payload=payload,
            )
        )

    # --- o que aconteceu ----------------------------------------------------------------
    def decidido(self, notif_id: str, entrega: Entrega) -> None:
        """O `s2` decidiu: `SO_CARD` e `CALADO` são finais; falar espera `tocou`."""
        aviso = self.avisos[notif_id]
        if entrega in (Entrega.SO_CARD, Entrega.CALADO):
            aviso.entrega = entrega
            aviso.liberado = False

    def tocou(self, notif_ids: Iterable[str], agora: float) -> None:
        """Os pedaços que carregavam estes avisos tocaram inteiros: entregues (regra 15)."""
        for identificador in notif_ids:
            aviso = self.avisos[identificador]
            aviso.entrega = Entrega.FALADO
            aviso.liberado = False
        self._ultimo_falado = agora

    def cortado(self, notif_ids: Iterable[str]) -> None:
        """O dono falou por cima antes do aviso tocar: ele volta para a fila (P4)."""
        for identificador in notif_ids:
            aviso = self.avisos[identificador]
            if aviso.entrega is Entrega.NA_FILA:
                aviso.liberado = False

    # --- o card -------------------------------------------------------------------------
    def dados_do_card(self, agora: float) -> dict[str, list[dict[str, str]]]:
        """Os dados do componente `notificacoes`, no contrato que a janela já valida."""
        recentes = sorted(self.avisos.values(), key=lambda a: -a.recebido_em)[:LIMITE_DO_CARD]
        return {
            "avisos": [
                {
                    "tipo": a.tipo,
                    "origem": a.origem,
                    "resumo": a.resumo,
                    "instante": _ha_quanto(agora - a.recebido_em),
                    "entrega": str(a.entrega),
                    "confianca": "terceiros" if a.trust == str(Trust.THIRD_PARTY) else "propria",
                }
                for a in recentes
            ]
        }


def _ha_quanto(segundos: float) -> str:
    minutos = int(segundos // 60)
    if minutos < 1:
        return "agora"
    if minutos < 60:
        return f"há {minutos} min"
    return f"há {minutos // 60} h"
