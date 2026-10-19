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

from jarvis.executor.ferramentas import Confirmacao

Agendar = Callable[[float, Callable[[], None]], None]
"""Chama a função depois de tantos segundos (na janela, um `threading.Timer`)."""


@dataclass(frozen=True, slots=True)
class Pendencia:
    pergunta: Confirmacao
    """A ação exata: ferramenta, argumentos normalizados, o que a janela mostra."""
    expira_em: float
    contaminado: bool = False

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

    def abrir(self, pergunta: Confirmacao, *, contaminado: bool = False) -> Pendencia:
        with self._trava:
            if self.valida() is not None:
                raise PendenciaOcupada("já há uma confirmação pendente com o dono")
            pendencia = Pendencia(pergunta, self.relogio() + pergunta.prazo_s, contaminado)
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

    def tomar(self, pendencia_id: str) -> Pendencia | None:
        """Retira a pendência **deste id**, se ainda vale. Uma vez só."""
        with self._trava:
            aberta = self.valida()
            if aberta is None or aberta.id != pendencia_id:
                return None
            self._aberta = None
        self._avisar_fim(aberta.id)
        return aberta

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
