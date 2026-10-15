"""As seis regras de epoch da §3.3, em código, com um ponto de decisão só (ADR-0002).

`DonoDoEpoch` é do `agentd` (§2). Nenhum outro processo incrementa epoch, e nenhum decide
por conta própria se descarta um evento velho: todos perguntam a `classificar`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto

from jarvis.barramento.envelope import (
    Envelope,
    Prioridade,
    Tipo,
    Trust,
    uuid7,
)

TIPOS_DE_AUDITORIA: frozenset[Tipo] = frozenset({Tipo.POLICY_DECISION, Tipo.TOOL_RESULT})
"""Exceção da regra 6: decisão de política e resultado de tool sempre chegam à auditoria.

A §5.5 exige decisão registrada antes do efeito e resultado anexado depois. Descartar por
epoch velho abriria um buraco no registro exatamente no caso interessante (o cancelado).
"""

MOTIVOS_DE_CANCELAMENTO: frozenset[str] = frozenset(
    {"barge_in", "stop_word", "privacy", "aec_fail", "timeout"}
)


class Veredito(StrEnum):
    """O que fazer com um evento, dado o epoch atual."""

    ACEITAR = auto()
    ACEITAR_STALE = auto()
    """Regra 3: resultado de tool **de leitura** sobreviveu ao cancelamento. Só entra se o
    `s2` reavaliar que ainda serve; não vira fala nem memória sozinho."""

    SO_AUDITORIA = auto()
    """Regra 6 (exceção): vai para o log, não alimenta raciocínio nem histórico."""

    DESCARTAR = auto()


class EpochMorto(RuntimeError):
    """Tentativa de reativar um epoch já invalidado (§3.3 regra 5)."""


@dataclass(slots=True)
class ChamadaEmVoo:
    call_id: str
    epoch: int
    read_only: bool
    stale: bool = False


@dataclass(slots=True)
class DonoDoEpoch:
    """Dono do epoch de uma sessão: incrementa, cancela e classifica (§2, `agentd`)."""

    session_id: str
    epoch_atual: int = 0
    em_voo: dict[str, ChamadaEmVoo] = field(default_factory=dict)
    _mortos: set[int] = field(default_factory=set)

    # --- regra 1 -------------------------------------------------------------------
    def fala_comecou(self, *, motivo: str = "barge_in") -> Envelope:
        """`speech_started` local: incrementa o epoch e devolve o `Cancel` do anterior.

        Nada de esperar ASR ou S2 (regra 1): o incremento acontece **antes** de qualquer
        transcrição, e o `Cancel` sai em P0. O chamador só precisa publicar o envelope.
        """
        if motivo not in MOTIVOS_DE_CANCELAMENTO:
            raise ValueError(f"motivo de Cancel fora da §3.2: {motivo!r}")
        anterior = self.epoch_atual
        self.epoch_atual = anterior + 1
        self._mortos.add(anterior)
        self._marcar_em_voo_stale(anterior)
        return Envelope(
            session_id=self.session_id,
            epoch=self.epoch_atual,
            source="agentd",
            trust=Trust.SYSTEM,
            priority=Prioridade.P0,
            type=Tipo.CANCEL,
            payload={"epoch_invalidado": anterior, "reason": motivo},
            event_id=uuid7(),
        )

    # --- regra 2 -------------------------------------------------------------------
    def _marcar_em_voo_stale(self, epoch: int) -> None:
        """Chamadas em voo do epoch morto ficam `stale` no mesmo tick (regra 2)."""
        for chamada in self.em_voo.values():
            if chamada.epoch == epoch:
                chamada.stale = True

    def registrar_chamada(self, call_id: str, *, read_only: bool) -> ChamadaEmVoo:
        chamada = ChamadaEmVoo(call_id=call_id, epoch=self.epoch_atual, read_only=read_only)
        self.em_voo[call_id] = chamada
        return chamada

    # --- regras 3 e 6 --------------------------------------------------------------
    def classificar(self, envelope: Envelope) -> Veredito:
        """Veredito sobre um evento recebido, pela regra 6 e suas exceções."""
        if envelope.epoch > self.epoch_atual:
            # Epoch do futuro: ou o emissor está adiantado, ou não é desta sessão.
            return Veredito.DESCARTAR
        if envelope.epoch == self.epoch_atual:
            return Veredito.ACEITAR
        if envelope.type is Tipo.TOOL_RESULT and bool(envelope.payload.get("read_only")):
            return Veredito.ACEITAR_STALE  # regra 3
        if envelope.type in TIPOS_DE_AUDITORIA:
            return Veredito.SO_AUDITORIA
        return Veredito.DESCARTAR

    # --- regra 5 -------------------------------------------------------------------
    def retomar(self, epoch: int) -> None:
        """ "Continua" não ressuscita plano: reativar epoch morto é erro (regra 5)."""
        if epoch != self.epoch_atual:
            raise EpochMorto(
                f"epoch {epoch} está morto; a retomada parte do que foi tocado, "
                f"não do plano antigo (epoch atual {self.epoch_atual})"
            )

    def morto(self, epoch: int) -> bool:
        return epoch in self._mortos


# --- regra 4 -----------------------------------------------------------------------
@dataclass(slots=True)
class TrechoDeFala:
    chunk_id: str
    texto: str
    epoch: int
    played_ms: int = 0

    @property
    def tocado(self) -> bool:
        return self.played_ms > 0


@dataclass(slots=True)
class LivroDeFala:
    """Histórico do que **de fato tocou** (regra 4, P4).

    Áudio enfileirado e não reproduzido não existe para o modelo: `historico()` só devolve
    trecho com `played_ms` real, vindo de `PlaybackProgress`.
    """

    _trechos: dict[str, TrechoDeFala] = field(default_factory=dict)

    def enfileirar(self, chunk_id: str, texto: str, epoch: int) -> None:
        self._trechos[chunk_id] = TrechoDeFala(chunk_id=chunk_id, texto=texto, epoch=epoch)

    def progresso(self, envelope: Envelope) -> None:
        """Registra `played_ms` real a partir de um `PlaybackProgress` do `audio-io`."""
        if envelope.type is not Tipo.PLAYBACK_PROGRESS:
            raise ValueError(f"esperado PlaybackProgress, veio {envelope.type}")
        chunk_id = str(envelope.payload["chunk_id"])
        trecho = self._trechos.get(chunk_id)
        if trecho is None:
            raise KeyError(f"progresso de chunk desconhecido: {chunk_id!r}")
        trecho.played_ms = max(trecho.played_ms, int(envelope.payload["played_ms"]))

    def descartar_nao_tocado(self, epoch: int) -> list[str]:
        """Cancelamento: o que estava na fila e não tocou desaparece (regras 2 e 4)."""
        perdidos = [
            chunk_id
            for chunk_id, trecho in self._trechos.items()
            if trecho.epoch == epoch and not trecho.tocado
        ]
        for chunk_id in perdidos:
            del self._trechos[chunk_id]
        return perdidos

    def historico(self) -> list[TrechoDeFala]:
        return [t for t in self._trechos.values() if t.tocado]

    def audio_tocado_ms(self) -> int:
        return sum(t.played_ms for t in self.historico())

    def texto_tocado(self) -> str:
        return " ".join(t.texto for t in self.historico())
