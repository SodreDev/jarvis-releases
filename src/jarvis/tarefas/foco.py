"""Acompanhar um app até a janela dele abrir, e pô-lo em foco (dono, 2026-10-20, ADR-0037).

Um motor de tarefa (ADR-0022): roda em segundo plano, sem prender a conversa, e acorda em
intervalos que crescem (1, 2, 3, 5, 8 s e depois a cada 10 s) para listar as janelas — a em
primeiro plano e as em segundo. Quando a janela do app aparece **com evidência**
(`jarvis.executor.janelas.avaliar`), ele **propõe** pô-la em foco (`window.focus_app` com o id da
janela: quem executa é o executor, com o PDP) e confere que ela ficou na frente; se ela some logo
depois (a janela de abertura que dá lugar à do app), procura a seguinte. Empate que dura é dúvida:
pergunta ao dono. A janela de entrar na conta do Steam é dele, e o motor espera. Passado o prazo
(configurável), diz com franqueza o que viu.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from jarvis.executor.janelas import (
    PRAZO_DO_FOCO_S,
    JanelaDoSistema,
    Janelas,
    PistaDoApp,
    Processos,
    avaliar,
)
from jarvis.s2.motor import PedidoDeTool
from jarvis.tarefas.gestor import ErroDeTarefa, FimDaTarefa, Passo, Tarefa

if TYPE_CHECKING:
    from jarvis.executor.ferramentas import ResultadoDeFerramenta

INTERVALOS_S: Final = (1.0, 2.0, 3.0, 5.0, 8.0)
INTERVALO_MAXIMO_S: Final = 10.0
MARGEM_DA_TAREFA_S: Final = 60.0
"""O prazo da tarefa passa o do motor: quem diz "não apareceu" é o motor, com o que viu."""
CARENCIA_S: Final = 5.0
"""Nos primeiros segundos só janela nova conta: a que o app já tinha só é a resposta quando ele
reaproveitou a instância aberta (e aí não aparece janela nova)."""
EMPATES_PARA_PERGUNTAR: Final = 3
"""Ciclos seguidos com empate antes de perguntar: a janela de abertura costuma sumir sozinha."""
ASSENTAR_S: Final = 3.0
"""Depois de focar, quanto se espera para ver se a janela fica (a de abertura some)."""
RAPIDO_S: Final = 10.0
"""Terminou antes disto: o dono acabou de ouvir que o app abriu, e o fim não vira aviso."""
FATIA_S: Final = 0.2
"""De quanto em quanto tempo a espera olha o cancelar: o botão de parar não espera o ciclo."""


@dataclass(slots=True)
class MotorDeFoco:
    pista: PistaDoApp
    antes: frozenset[str]
    """As janelas que já existiam antes de abrir o app: uma janela nova é evidência."""
    janelas: Janelas
    prazo_s: float = PRAZO_DO_FOCO_S
    relogio: Callable[[], float] = time.monotonic
    dormir: Callable[[float], None] = time.sleep
    processos: Processos | None = None
    nome: str = "foco"
    na_nuvem: bool = False
    _comeco: float | None = None
    _ciclo: int = 0
    _empates: int = 0
    _alvo: JanelaDoSistema | None = None
    _viu_janelas: bool = False
    _viu_a_conta_do_steam: bool = False
    _fracas: tuple[JanelaDoSistema, ...] = ()

    def proximo(
        self, tarefa: Tarefa, feitos: Sequence[ResultadoDeFerramenta], cancelado: Callable[[], bool]
    ) -> Passo:
        del tarefa
        if self._comeco is None:
            self._comeco = self.relogio()
        if feitos and feitos[-1].tool_id == "window.focus_app":
            conferido = self._conferir(feitos[-1], cancelado)
            if conferido is not None:
                return conferido
        return self._procurar(cancelado)

    def _procurar(self, cancelado: Callable[[], bool]) -> Passo:
        nome = self.pista.nome
        while not cancelado():
            janelas = self.janelas.listar()
            self._viu_janelas |= bool(janelas)
            leitura = avaliar(
                janelas,
                self.pista,
                self.antes,
                processos=self.processos,
                velhas_valem=self._passou(CARENCIA_S),
            )
            self._viu_a_conta_do_steam |= leitura.conta_do_steam
            self._fracas = tuple(e.janela for e in leitura.fracas) or self._fracas
            self._empates = self._empates + 1 if leitura.duvida else 0
            if leitura.alvo is not None:
                alvo = leitura.alvo.janela
                if alvo.ativa:
                    return self._fim(f"{nome} abriu e está em foco")
                self._alvo = alvo
                return PedidoDeTool("window.focus_app", {"app": nome[:60], "janela_id": alvo.id})
            if leitura.duvida and self._empates >= EMPATES_PARA_PERGUNTAR:
                quais = "; ".join(f"«{e.janela.titulo or e.janela.classe}»" for e in leitura.duvida)
                pergunta = (
                    f"{nome} abriu {len(leitura.duvida)} janelas que podem ser ele ({quais[:300]})"
                    " e não ponho nenhuma na frente por palpite: qual delas?"
                )
                return FimDaTarefa(pergunta, aviso=pergunta)
            if self._passou(self.prazo_s):
                raise ErroDeTarefa(self._sem_janela())
            self._esperar(self._intervalo(), cancelado)
        return FimDaTarefa(f"parei de acompanhar {nome}", aviso="")

    def _conferir(
        self, resultado: ResultadoDeFerramenta, cancelado: Callable[[], bool]
    ) -> Passo | None:
        """Depois do foco: a janela ficou na frente? E ficou aberta, ou era a de abertura?"""
        nome = self.pista.nome
        if resultado.status != "ok":
            raise ErroDeTarefa(
                f"a janela de {nome} abriu, mas não deu para pô-la em foco: {resultado.motivo}"
            )
        alvo = self._alvo
        na_frente = False
        for _ in range(5):  # o gerenciador de janelas pode levar um instante
            ativa = next((j for j in self.janelas.listar() if j.ativa), None)
            na_frente = alvo is not None and ativa is not None and ativa.id == alvo.id
            if na_frente or cancelado():
                break
            self._esperar(FATIA_S, cancelado)
        if cancelado():
            return FimDaTarefa(f"parei de acompanhar {nome}", aviso="")
        if not na_frente:
            raise ErroDeTarefa(f"pedi o foco para a janela de {nome}, mas ela não ficou na frente")
        self._esperar(ASSENTAR_S, cancelado)
        if alvo is not None and any(j.id == alvo.id for j in self.janelas.listar()):
            return self._fim(f"{nome} abriu e está em foco")
        return None  # a janela de abertura sumiu: procurar a do app

    def _fim(self, texto: str) -> FimDaTarefa:
        """Fim feliz rápido não vira aviso (o dono acabou de ouvir que abriu); o demorado, sim."""
        return FimDaTarefa(texto, aviso=texto if self._passou(RAPIDO_S) else "")

    def _sem_janela(self) -> str:
        nome = self.pista.nome
        if not self._viu_janelas:
            return (
                f"não consegui ver as janelas do sistema em {self.prazo_s:.0f} s, então não sei "
                f"se {nome} abriu"
            )
        partes = [f"esperei {self.prazo_s:.0f} s e a janela de {nome} não apareceu"]
        if self._viu_a_conta_do_steam:
            partes.append("o Steam ficou esperando você escolher a conta")
        if self._fracas:
            quais = ", ".join(f"«{j.titulo}»" for j in self._fracas[:2])
            partes.append(
                f"vi {quais}, nova e com o nome dele, mas sem ligação com o que eu abri: não pus "
                "na frente por palpite"
            )
        return "; ".join(partes) + "."

    def _passou(self, segundos: float) -> bool:
        return self._comeco is not None and self.relogio() - self._comeco >= segundos

    def _intervalo(self) -> float:
        espera = (
            INTERVALOS_S[self._ciclo] if self._ciclo < len(INTERVALOS_S) else INTERVALO_MAXIMO_S
        )
        self._ciclo += 1
        return espera

    def _esperar(self, segundos: float, cancelado: Callable[[], bool]) -> None:
        fim = self.relogio() + segundos
        while not cancelado():
            restante = fim - self.relogio()
            if restante <= 0:
                return
            self.dormir(min(FATIA_S, restante))
