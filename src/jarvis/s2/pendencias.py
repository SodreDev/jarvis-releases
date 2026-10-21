"""A pendência de confirmação da conversa: uma pergunta ao dono que **não prende** o turno.

Antes, pedir o "sim" bloqueava a linha do cérebro até o clique — e, com o turno preso, o laço de
voz não ouvia nada: "sim" falado era impossível. Agora a pergunta vira uma `Pendencia`, o Jarvis
a diz e o turno acaba; quem resolve é o próximo turno do dono (voz ou texto) ou o clique na
janela. As regras que tornam isso seguro moram aqui:

- **uma por vez**: enquanto há uma aberta, outra não a substitui (`abrir` recusa) — um "sim" não
  pode cair numa pergunta que o dono não ouviu;
- **amarrada ao id**: `tomar(id)` só entrega a pendência daquele id, ainda válida, e uma vez;
- **prazo**: vencida, some (e a janela é avisada); `tomar` de uma vencida devolve `None`;
- **cancelável**: turno do dono que não responde a ela, fim da sessão, "não".
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from jarvis.executor.ferramentas import Cancelado, Confirmacao

Agendar = Callable[[float, Callable[[], None]], None]
"""Chama a função depois de tantos segundos (na janela, um `threading.Timer`)."""
INTERVALO_DA_ESPERA_S = 0.05
"""De quanto em quanto a tarefa parada numa pergunta olha o cancelamento e o prazo."""


@dataclass(slots=True)
class Espera:
    """Uma tarefa parada nesta pergunta (ADR-0038): o "sim" ou o "não" do dono a acorda.

    Pergunta de tarefa chega à voz pela fila de avisos, e não no fim de um turno: até ela tocar
    inteira (`ouvida`), um "sim" falado não a responde — o dono ainda não a ouviu. O clique na
    janela vale desde o começo: a faixa já mostra a pergunta."""

    evento: threading.Event = field(default_factory=threading.Event)
    sim: bool = False
    ouvida: bool = False
    so_clique: bool = False
    """Só o clique responde: a pergunta por ação (o que está sob o clique, ADR-0027) e a que nasce
    sem o portão (sem o Jev, nada interpreta a fala) — como na janela de antes."""

    def responder(self, sim: bool) -> None:
        self.sim = sim
        self.evento.set()


@dataclass(frozen=True, slots=True)
class Pendencia:
    pergunta: Confirmacao
    """A ação exata: ferramenta, argumentos normalizados, o que a janela mostra."""
    expira_em: float
    contaminado: bool = False
    espera: Espera | None = None
    """A tarefa que espera esta resposta; `None` = a pergunta do fim de um turno (a execução
    confirmada vira tarefa nova, `jarvis.s2.fluxo_de_acao`)."""

    @property
    def id(self) -> str:
        return self.pergunta.id


class PendenciaOcupada(RuntimeError):
    """Já há uma pergunta aberta ao dono; a nova não a substitui."""


@dataclass(slots=True)
class RegistroDePendencias:
    relogio: Callable[[], float] = time.monotonic
    ao_abrir: Callable[[Confirmacao], None] | None = None
    """A janela mostra a faixa. Sem janela, o pedido segue valendo pela voz."""
    ao_fechar: Callable[[str], None] | None = None
    """Respondida, vencida ou cancelada: a janela tira a faixa."""
    agendar: Agendar | None = None
    """Sem agenda (testes), a expiração é preguiçosa: vale no próximo olhar."""
    _aberta: Pendencia | None = None
    _trava: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def abrir(
        self, pergunta: Confirmacao, *, contaminado: bool = False, espera: Espera | None = None
    ) -> Pendencia:
        with self._trava:
            if self.valida() is not None:
                raise PendenciaOcupada("já há uma confirmação pendente com o dono")
            pendencia = Pendencia(pergunta, self.relogio() + pergunta.prazo_s, contaminado, espera)
            self._aberta = pendencia
        if self.ao_abrir is not None:
            self.ao_abrir(pergunta)
        if self.agendar is not None:
            self.agendar(pergunta.prazo_s, self.expirar)
        return pendencia

    def valida(self) -> Pendencia | None:
        """A pendência aberta e dentro do prazo; a vencida é fechada aqui."""
        with self._trava:
            aberta = self._aberta
            if aberta is None:
                return None
            if self.relogio() < aberta.expira_em:
                return aberta
            self._aberta = None
        self._avisar_fim(aberta.id)
        return None

    def tomar(self, pendencia_id: str, *, sim: bool | None = None) -> Pendencia | None:
        """Retira a pendência **deste id**, se ainda vale. Uma vez só.

        Com `sim`, a tarefa que espera por ela é acordada com a resposta **dentro** da trava: quem
        espera e vê a pendência fechada já encontra a resposta dada."""
        with self._trava:
            aberta = self.valida()
            if aberta is None or aberta.id != pendencia_id:
                return None
            self._aberta = None
            if sim is not None and aberta.espera is not None:
                aberta.espera.responder(sim)
        self._avisar_fim(aberta.id)
        return aberta

    def marcar_ouvida(self, pendencia_id: str) -> None:
        """A pergunta desta pendência tocou inteira em voz: daqui em diante o "sim" falado vale."""
        with self._trava:
            aberta = self._aberta
            if aberta is not None and aberta.id == pendencia_id and aberta.espera is not None:
                aberta.espera.ouvida = True

    def esperar(
        self,
        pergunta: Confirmacao,
        *,
        contaminado: bool,
        cancelado: Cancelado,
        anunciar: Callable[[Confirmacao], None],
        espera: Espera | None = None,
    ) -> bool | None:
        """Para a tarefa (ADR-0038): abre a pendência, anuncia e espera a resposta do dono — sem
        prender a conversa. `None` = já havia outra pergunta aberta (nada é substituído)."""
        espera = espera if espera is not None else Espera()
        try:
            self.abrir(pergunta, contaminado=contaminado, espera=espera)
        except PendenciaOcupada:
            return None
        anunciar(pergunta)
        while not espera.evento.wait(INTERVALO_DA_ESPERA_S):
            if cancelado():
                self.tomar(pergunta.id, sim=False)  # a faixa sai da janela
                return False
            if not self.aberta_agora(pergunta.id):
                # Vencida, cancelada, ou respondida agora mesmo: quem respondeu acordou a espera
                # dentro da trava, antes de fechar a pendência.
                return espera.evento.is_set() and espera.sim
        return espera.sim

    def interrompida(self) -> None:
        """O dono interrompeu: a pergunta de tarefa que ele ainda não ouviu inteira cai (é não) —
        como a do fim de um turno cortada antes de tocar (`Cerebro.ouvido`)."""
        with self._trava:
            aberta = self._aberta
        if aberta is not None and aberta.espera is not None and not aberta.espera.ouvida:
            self.tomar(aberta.id, sim=False)

    def aberta_agora(self, pendencia_id: str) -> bool:
        """Esta pendência ainda está aberta e no prazo (a tarefa que espera olha aqui)."""
        aberta = self.valida()
        return aberta is not None and aberta.id == pendencia_id

    def cancelar(self) -> Pendencia | None:
        with self._trava:
            aberta, self._aberta = self._aberta, None
        if aberta is not None:
            self._avisar_fim(aberta.id)
        return aberta

    def expirar(self) -> None:
        self.valida()

    def _avisar_fim(self, pendencia_id: str) -> None:
        if self.ao_fechar is not None:
            self.ao_fechar(pendencia_id)
