"""O painel do microfone da `ui`: PTT, indicador que não mente e *kill switch* (F1-13).

Três regras que estão na **estrutura**, não na disciplina de quem escreve a tela:

1. **`ouvindo` é derivado.** É `ler_estado(raiz).aberta` — o que o `audio-io` relatou da fonte —
   e nada mais. O painel não tem campo booleano "ouvindo" para alguém escrever por engano.
2. **Estado velho não acende o indicador.** O `audio-io` reescreve o arquivo de estado a cada
   250 ms; se o arquivo está parado há mais que `tolerancia_s`, o processo do áudio não está
   ticando, logo **não há amostra saindo**, e o painel mostra apagado dizendo que perdeu
   contato. Indicador que fica aceso porque o processo morreu é a pior mentira possível.
3. **O *kill switch* é do dono.** Enquanto ele está ligado, o `tick` escreve `DESLIGADO` todo
   tick: nem a tecla apertada nem o modo anterior reabrem a fonte.

A frase da tela é **uma** frase por estado, de propósito: é o que o cartão cobra, e é o que
cabe num canto de tela sem o dono ter de interpretar ícone.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from jarvis.microfone import (
    ARQUIVO_ESTADO,
    EstadoDaFonte,
    Modo,
    Pedido,
    escrever_pedido,
    ler_estado,
)
from jarvis.rede import Degradacao, ler_degradacao
from jarvis.ui.atalhos import AtalhoIndisponivel, BackendDeAtalho, SemAtalho

ARQUIVO_TELA: Final = "ui-microfone.txt"
TOLERANCIA_PADRAO_S: Final = 2.0
"""Oito vezes o período de reescrita do `audio-io` (250 ms): folga para escalonador, não para
processo morto."""


@dataclass(slots=True)
class PainelDoMicrofone:
    """O que a `ui` mostra e o que ela pede. Não toca em dispositivo: pede e observa."""

    raiz: Path
    atalho: BackendDeAtalho = field(default_factory=SemAtalho)
    modo: Modo = Modo.PTT
    aviso: str | None = None
    """Degradação declarada (cartão F1-14): uma frase sobre o que deixou de funcionar."""
    sem_atalho: str | None = None
    """Motivo de não haver atalho global nesta máquina. A tela cai no botão."""
    tolerancia_s: float = TOLERANCIA_PADRAO_S
    agora: Callable[[], float] = time.time
    degradado: bool = False
    """Cartão F1-14: a rede caiu e a escuta contínua está desligada por causa disso."""
    _modo_antes_de_desligar: Modo = Modo.PTT
    _modo_antes_da_degradacao: Modo | None = None

    def abrir(self) -> None:
        """Registra o atalho; recusa do sistema **não** derruba a `ui`, vira aviso na tela.

        O aviso é linha separada da frase do microfone de propósito: "não consegui registrar o
        atalho" é degradação do **caminho de entrada**, não estado da fonte. Misturar as duas
        numa frase só obrigaria a escolher qual delas o dono não lê.
        """
        try:
            self.atalho.abrir()
        except AtalhoIndisponivel as erro:
            self.sem_atalho = str(erro)
            self.aviso = (
                f"Não consegui registrar {self.atalho.combinacao} nesta sessão gráfica, "
                "então use o botão da tela para falar."
            )

    def fechar(self) -> None:
        self.atalho.fechar()

    def desligar(self) -> None:
        """*Kill switch*. Guarda o modo anterior para o religar não inventar comportamento."""
        if self.modo is not Modo.DESLIGADO:
            self._modo_antes_de_desligar = self.modo
            self.modo = Modo.DESLIGADO

    def ligar(self) -> None:
        if self.modo is Modo.DESLIGADO:
            self.modo = self._modo_antes_de_desligar

    @property
    def desligado(self) -> bool:
        return self.modo is Modo.DESLIGADO

    def aplicar_degradacao(self, degradacao: Degradacao | None = None) -> Degradacao:
        """Cai para PTT e mostra a frase enquanto o serviço estiver fora (cartão F1-14).

        O *kill switch* **vence**: se o dono desligou o microfone, a degradação não o religa em
        PTT. E a volta restaura o modo que existia antes, em vez de inventar escuta contínua
        que o dono não pediu.
        """
        degradacao = ler_degradacao(self.raiz) if degradacao is None else degradacao
        if degradacao.ativa:
            if not self.degradado and self.modo is not Modo.DESLIGADO:
                self._modo_antes_da_degradacao = self.modo
            if self.modo is Modo.ESCUTA:
                self.modo = Modo.PTT
            self.degradado = True
            self.aviso = degradacao.frase or None
            return degradacao
        if self.degradado:
            self.degradado = False
            if self.modo is not Modo.DESLIGADO and self._modo_antes_da_degradacao is not None:
                self.modo = self._modo_antes_da_degradacao
            self._modo_antes_da_degradacao = None
            self.aviso = degradacao.frase or None
        return degradacao

    def tick(self) -> Pedido:
        """Lê a tecla e escreve o pedido. É a única coisa que o painel escreve."""
        pressionado = self.modo is Modo.PTT and self.atalho.pressionado()
        pedido = Pedido(modo=self.modo, pressionado=pressionado)
        escrever_pedido(self.raiz, pedido)
        return pedido

    @property
    def estado(self) -> EstadoDaFonte:
        """O estado **relatado pela fonte**; fresco, ou apagado por falta de contato."""
        if not self.em_contato:
            return EstadoDaFonte(modo=self.modo)
        return ler_estado(self.raiz)

    @property
    def nunca_relatou(self) -> bool:
        """O `audio-io` ainda não escreveu estado nenhum. Diferente de ter perdido contato."""
        return not (self.raiz / ARQUIVO_ESTADO).exists()

    @property
    def em_contato(self) -> bool:
        """O `audio-io` reescreveu o estado há pouco? Sem contato, não há amostra saindo."""
        caminho = self.raiz / ARQUIVO_ESTADO
        try:
            idade = self.agora() - caminho.stat().st_mtime
        except OSError:
            return False
        return idade <= self.tolerancia_s

    @property
    def ouvindo(self) -> bool:
        """**Derivado da fonte.** Não existe caminho para a `ui` acender isto por conta."""
        return self.estado.aberta

    def frase(self) -> str:
        """Uma frase, para este estado. A ordem é a da urgência do que o dono precisa saber."""
        estado = self.estado
        if estado.aberta:
            if estado.modo is Modo.PTT:
                return f"Ouvindo enquanto você segura {self.atalho.combinacao}."
            return "Ouvindo: o microfone está aberto e o Jarvis decide sozinho quando responder."
        if self.desligado or estado.modo is Modo.DESLIGADO:
            return (
                "Microfone desligado no botão: nenhuma amostra sai da fonte e nada é tocado "
                "até você ligar de novo."
            )
        if self.nunca_relatou:
            return (
                "Ainda não recebi notícia do processo de áudio, então o microfone conta como "
                "fechado até ele falar."
            )
        if not self.em_contato:
            return (
                "Perdi contato com o processo de áudio, então não sei dizer se o microfone "
                "está aberto — e enquanto for assim ele conta como fechado."
            )
        if estado.indisponivel is not None:
            return (
                "Não encontrei microfone neste computador, então dá para falar por um arquivo "
                "de áudio no modo de teste até você plugar um."
            )
        if self.modo is Modo.PTT:
            return f"Microfone fechado: segure {self.atalho.combinacao} para falar."
        return "Microfone fechado."

    def escrever_tela(self) -> str:
        """Grava o que a tela diz, para quem olha de fora do processo (teste e supervisor)."""
        linhas = [self.frase()]
        if self.aviso is not None:
            linhas.append(self.aviso)
        texto = "\n".join(linhas)
        caminho = self.raiz / ARQUIVO_TELA
        temporario = caminho.with_name(caminho.name + ".tmp")
        temporario.write_text(texto + "\n", encoding="utf-8")
        temporario.replace(caminho)
        return texto
