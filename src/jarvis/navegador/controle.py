"""O controle das abas e o PARAR do dono (ADR-0027, regra 4).

Enquanto o Jarvis age numa aba (lê, navega, clica, digita) a extensão mostra que ele está **no
controle**: um selo no botão dela na barra e uma faixa no topo da página, desenhada por ela. Cada
objetivo (o pedido do turno, ou o de uma tarefa) recebe uma **concessão** — um id aleatório que vai
em todo pedido dele à extensão; é por ela que a extensão sabe quais abas mostram o indicador e o
que recusar depois de um PARAR.

Quem solta é o código, nunca o modelo nem a página:

- **o objetivo acabou** (o turno respondeu, a tarefa terminou): a vigia vê a fase de concluir e
  pede `controle.soltar` — a faixa some;
- **o dono apertou PARAR** (na faixa, no botão da barra ou na janela do Jarvis): a extensão revoga a
  concessão na hora (recusa o que vier dela depois) e manda o evento; aqui ele vira `ao_parar` —
  o app cancela o turno (epoch) e a tarefa daquele objetivo;
- **o Jarvis sumiu**: sem `controle.manter` a extensão solta sozinha depois de um prazo.

A vigia é uma linha que só existe enquanto há concessão viva.
"""

from __future__ import annotations

import contextlib
import secrets
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from jarvis.navegador.cliente import ClienteDoNavegador, NavegadorFalhou, NavegadorIndisponivel
from jarvis.politica.objetivo import EstadoDoObjetivo, Fase, Objetivo

INTERVALO_DA_VIGIA_S: Final = 0.25
MANTER_A_CADA_S: Final = 10.0
"""A extensão solta sozinha a concessão que ficar 30 s sem pedido (o Jarvis pode ter caído): a
vigia renova antes, enquanto o objetivo não acabou."""
AVULSA_OCIOSA_S: Final = 8.0
"""Chamada sem objetivo (sem fala do dono): a concessão avulsa solta depois deste tempo parada."""
OCIOSA_S: Final = 45.0
"""Objetivo que não mexe no navegador há este tempo (pensando, esperando outra coisa) solta as
abas; o próximo pedido dele as pega de novo, com o indicador junto."""
PARADO_PELO_DONO: Final = "parado_pelo_dono"
"""O código da extensão para pedido de concessão revogada pelo PARAR."""


class Assinatura(Protocol):
    def esperar(self, segundos: float) -> list[dict[str, Any]]:
        """Os eventos que chegaram em até `segundos` (lista vazia = nenhum). Levanta
        `NavegadorIndisponivel` quando o host fecha a conexão."""
        ...

    def fechar(self) -> None: ...


def nova_concessao() -> str:
    return secrets.token_hex(8)


@dataclass(slots=True)
class Concessao:
    id: str
    objetivo: Objetivo | None
    """`None`: chamada sem objetivo (avulsa), que solta por ociosidade."""
    ao_concluir: Callable[[EstadoDoObjetivo], None] | None = None
    """O que fazer quando o objetivo acaba, antes de soltar (pôr a página à vista do dono)."""
    ultimo_uso: float = field(default_factory=time.monotonic)
    ultimo_manter: float = field(default_factory=time.monotonic)
    confirmada: bool = False
    """A extensão já aceitou um pedido desta concessão (a faixa está numa aba): só então a janela
    do Jarvis mostra o PARAR — pedido que nem chegou ao navegador não põe nada no controle."""


class ControleDoNavegador:
    def __init__(
        self,
        cliente: ClienteDoNavegador,
        *,
        assinar: Callable[[], Assinatura] | None = None,
        intervalo_s: float = INTERVALO_DA_VIGIA_S,
        manter_s: float = MANTER_A_CADA_S,
        avulsa_ociosa_s: float = AVULSA_OCIOSA_S,
        ociosa_s: float = OCIOSA_S,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cliente = cliente
        self._assinar = assinar
        self._intervalo_s = intervalo_s
        self._manter_s = manter_s
        self._avulsa_ociosa_s = avulsa_ociosa_s
        self._ociosa_s = ociosa_s
        self._relogio = relogio
        self._trava = threading.Lock()
        self._vivas: dict[str, Concessao] = {}
        self._revogadas: set[str] = set()
        self._objetivos_parados: list[Objetivo] = []
        """Os últimos objetivos que o dono parou: nada mais deles volta a agir no navegador."""
        self._avulsa: str | None = None
        self._fio: threading.Thread | None = None
        self.ao_parar: Callable[[Sequence[Objetivo]], None] | None = None
        """O dono apertou PARAR: os objetivos que estavam no controle (o app cancela o turno e as
        tarefas deles)."""
        self.ao_mudar: Callable[[bool], None] | None = None
        """Há (ou deixou de haver) aba no controle do Jarvis: a janela mostra o botão de parar."""

    # --- quem age ---------------------------------------------------------------------------
    def concessao(
        self,
        objetivo: Objetivo | None,
        *,
        ao_concluir: Callable[[EstadoDoObjetivo], None] | None = None,
    ) -> str:
        """A concessão do objetivo (criada no primeiro uso, e a vigia junto). `PermissionError` se
        o dono já mandou parar este objetivo: nada mais dele age no navegador."""
        agora = self._relogio()
        with self._trava:
            existente = next(
                (
                    c
                    for c in self._vivas.values()
                    if objetivo is not None and c.objetivo is objetivo
                ),
                None,
            )
            if existente is None and objetivo is None and self._avulsa in self._vivas:
                existente = self._vivas[self._avulsa]
            if existente is None:
                if objetivo is not None and any(o is objetivo for o in self._objetivos_parados):
                    raise PermissionError("o dono apertou parar no navegador")
                existente = Concessao(nova_concessao(), objetivo, ao_concluir)
                existente.ultimo_manter = agora
                self._vivas[existente.id] = existente
                if objetivo is None:
                    self._avulsa = existente.id
            elif ao_concluir is not None:
                existente.ao_concluir = ao_concluir
            existente.ultimo_uso = agora
            self._garantir_a_vigia()
        return existente.id

    def confirmar(self, concessao: str) -> None:
        """A extensão aceitou um pedido desta concessão: há aba no controle, e a janela sabe."""
        with self._trava:
            viva = self._vivas.get(concessao)
            if viva is None or viva.confirmada:
                return
            viva.confirmada = True
            primeira = sum(c.confirmada for c in self._vivas.values()) == 1
        if primeira:
            self._avisar(True)

    @property
    def no_controle(self) -> bool:
        with self._trava:
            return any(c.confirmada for c in self._vivas.values())

    def revogada(self, concessao: str) -> bool:
        with self._trava:
            return concessao in self._revogadas

    # --- quem para --------------------------------------------------------------------------
    def parado_pelo_dono(self, concessoes: Sequence[str]) -> list[Objetivo]:
        """O PARAR chegou (evento da extensão, ou a recusa `parado_pelo_dono`): revoga, esquece e
        chama `ao_parar` com os objetivos que estavam no controle — uma vez por concessão."""
        with self._trava:
            antes = any(c.confirmada for c in self._vivas.values())
            paradas = [self._vivas.pop(c) for c in concessoes if c in self._vivas]
            self._revogadas.update(concessoes)
            objetivos = [c.objetivo for c in paradas if c.objetivo is not None]
            self._objetivos_parados.extend(objetivos)
            del self._objetivos_parados[:-32]
            depois = any(c.confirmada for c in self._vivas.values())
        if paradas and self.ao_parar is not None:
            self.ao_parar(objetivos)
        if antes and not depois:
            self._avisar(False)
        return objetivos

    def parar(self) -> list[Objetivo]:
        """O PARAR da janela do Jarvis: a extensão solta todas as abas e revoga as concessões, e o
        turno e as tarefas que estavam no controle são cancelados."""
        with self._trava:
            vivas = list(self._vivas)
        with contextlib.suppress(Exception):  # a revogação aqui vale mesmo sem a extensão
            self.cliente.chamar("controle.parar")
        return self.parado_pelo_dono(vivas)

    def fechar(self) -> None:
        """Solta tudo (o app fechando, o executor trocado): a vigia termina sozinha em seguida."""
        with self._trava:
            vivas = list(self._vivas)
        for concessao in vivas:
            self.soltar(concessao)

    # --- a vigia ----------------------------------------------------------------------------
    def _garantir_a_vigia(self) -> None:
        if self._fio is None or not self._fio.is_alive():
            self._fio = threading.Thread(target=self._vigiar, name="jarvis-controle", daemon=True)
            self._fio.start()

    def _vigiar(self) -> None:
        assinatura: Assinatura | None = None
        try:
            while True:
                with self._trava:
                    if not self._vivas:
                        self._fio = None
                        return
                assinatura = self._ouvir(assinatura)
                self._soltar_o_que_acabou()
                self._manter()
        finally:
            if assinatura is not None:
                with contextlib.suppress(Exception):
                    assinatura.fechar()

    def _ouvir(self, assinatura: Assinatura | None) -> Assinatura | None:
        """Espera os eventos da extensão um intervalo (ou só dorme, sem assinatura)."""
        if assinatura is None and self._assinar is not None:
            with contextlib.suppress(NavegadorIndisponivel, OSError):
                assinatura = self._assinar()
        if assinatura is None:
            time.sleep(self._intervalo_s)
            return None
        try:
            eventos = assinatura.esperar(self._intervalo_s)
        except (NavegadorIndisponivel, OSError):
            with contextlib.suppress(Exception):
                assinatura.fechar()
            time.sleep(self._intervalo_s)
            return None
        for evento in eventos:
            if evento.get("evento") == "parar":
                self.parado_pelo_dono([str(c) for c in evento.get("concessoes", [])])
        return assinatura

    def _soltar_o_que_acabou(self) -> None:
        agora = self._relogio()
        with self._trava:
            acabadas = [
                c
                for c in self._vivas.values()
                if (c.objetivo is not None and c.objetivo.fase is Fase.CONCLUINDO)
                or agora - c.ultimo_uso
                > (self._avulsa_ociosa_s if c.objetivo is None else self._ociosa_s)
            ]
        for concessao in acabadas:
            concluido = (
                concessao.objetivo is not None and concessao.objetivo.fase is Fase.CONCLUINDO
            )
            if concluido and concessao.ao_concluir is not None and concessao.objetivo is not None:
                with contextlib.suppress(Exception):  # pôr à vista é cortesia: não prende a vigia
                    concessao.ao_concluir(concessao.objetivo.estado)
            self.soltar(concessao.id)

    def soltar(self, concessao: str) -> None:
        """O objetivo acabou: a extensão tira o indicador das abas desta concessão."""
        with self._trava:
            antes = any(c.confirmada for c in self._vivas.values())
            solta = self._vivas.pop(concessao, None)
            if self._avulsa == concessao:
                self._avulsa = None
            depois = any(c.confirmada for c in self._vivas.values())
        if solta is None:
            return
        with contextlib.suppress(Exception):  # sem extensão, ela solta sozinha pelo prazo
            self.cliente.chamar("controle.soltar", controle=concessao)
        if antes and not depois:
            self._avisar(False)

    def _manter(self) -> None:
        agora = self._relogio()
        with self._trava:
            vencendo = [
                c for c in self._vivas.values() if agora - c.ultimo_manter >= self._manter_s
            ]
            for concessao in vencendo:
                concessao.ultimo_manter = agora
        for concessao in vencendo:
            try:
                self.cliente.chamar("controle.manter", controle=concessao.id)
            except NavegadorFalhou as erro:
                if erro.codigo == PARADO_PELO_DONO:
                    self.parado_pelo_dono([concessao.id])
            except Exception:  # noqa: S110 — a vigia não cai: a extensão solta sozinha pelo prazo
                pass

    def _avisar(self, ativo: bool) -> None:
        if self.ao_mudar is not None:
            with contextlib.suppress(Exception):  # a janela não derruba a vigia
                self.ao_mudar(ativo)
