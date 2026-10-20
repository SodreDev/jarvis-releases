"""Onde a fala pode ser cortada: a regra única de fronteira para o TTS (ADR-0025, regra 7).

O TTS sintetiza por lotes com contexto suficiente para não soar palavra por palavra. Até a
ADR-0025 essa regra morava só no `fatiar()` do `agentd/tts.py`, que recebe o **texto inteiro**.
Com o cérebro respondendo em stream, o `s2` precisa cortar o texto **enquanto ele chega**, e
duas regras de corte (uma em cada processo) seriam dois lugares para divergir. Por isso a regra
mora aqui, incremental, e o `fatiar()` é este mesmo fatiador alimentado de uma vez.

A regra: um lote normal só sai depois de 14 palavras. A partir daí, a primeira pontuação útil
fecha o lote; sem pontuação, 18 palavras são o teto que impede buffer sem limite. Lote menor
só sai quando o texto acaba — no fim do stream, ou numa pausa dele (`descarregar`: o motor parou
para uma ferramenta, e "Deixa eu ver." não pode esperar a ferramenta voltar). Uma palavra só conta quando está **completa** — seguida de espaço,
ou no fim do texto —, porque o stream entrega pedaço de palavra: "3," pode virar "3,5" no delta
seguinte, e cortar ali partiria o número. Palavra é todo token sem espaço: hífen e token
excepcionalmente longo continuam atômicos, sem corte por caractere.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

PALAVRAS_MINIMAS_POR_PEDACO: Final = 14
"""Fora do último residual, nenhum lote sacrifica contexto abaixo deste piso."""
PALAVRAS_DO_PRIMEIRO_PEDACO: Final = 18
"""Teto do primeiro lote; mantido como nome público para os consumidores existentes."""
PALAVRAS_POR_PEDACO: Final = 18
PONTUACAO_DE_FRASE: Final = (".", "!", "?")
PONTUACAO_DE_VIRGULA: Final = (",", ";", ":")
PONTUACAO_DE_CORTE: Final = PONTUACAO_DE_VIRGULA + PONTUACAO_DE_FRASE


class Corte(StrEnum):
    """Por que o pedaço acabou ali. É o `boundary` do `ResponseChunk`."""

    FRASE = "frase"
    VIRGULA = "virgula"
    LIMITE = "limite"
    PAUSA = "pausa"
    """O texto parou antes de completar o lote: o motor pediu uma ferramenta, ou o código disse
    um aviso, e não há mais texto até ela voltar. O residual sai agora, mesmo abaixo do piso."""
    FIM = "fim"
    """O texto acabou. Pode vir **vazio**: quando o último pedaço já saiu numa pontuação, só o
    fim do stream diz que ele era o último, e esperar para saber atrasaria a primeira palavra."""


@dataclass(frozen=True, slots=True)
class PedacoDeFala:
    """Um trecho pronto para sintetizar, com a posição dele no texto recebido."""

    texto: str
    inicio: int
    corte: Corte


@dataclass(slots=True)
class FatiadorDeFala:
    """Recebe o texto aos poucos e devolve pedaços assim que uma fronteira é certa."""

    minimo: int = PALAVRAS_MINIMAS_POR_PEDACO
    primeiro: int = PALAVRAS_DO_PRIMEIRO_PEDACO
    seguintes: int = PALAVRAS_POR_PEDACO
    _texto: str = ""
    _varrido: int = 0
    """Até onde o texto já foi lido em busca de palavra completa."""
    _palavras: list[tuple[int, str]] = field(default_factory=list)
    _emitidos: int = 0
    _fechado: bool = False

    @property
    def texto(self) -> str:
        """Tudo o que chegou até agora, sem normalizar espaço."""
        return self._texto

    def alimentar(self, delta: str) -> list[PedacoDeFala]:
        """Acrescenta texto e devolve os pedaços que ficaram certos com ele."""
        if self._fechado:
            raise RuntimeError("fatiador já fechado: a resposta acabou")
        self._texto += delta
        return self._consumir(final=False)

    def fechar(self) -> list[PedacoDeFala]:
        """O stream acabou: o que sobrou vira pedaço, e o último sai com corte `FIM`.

        Sempre devolve pelo menos um pedaço — o último —, mesmo vazio, para quem consome saber
        que a resposta terminou sem precisar de outro sinal.
        """
        if self._fechado:
            return []
        self._fechado = True
        pedacos = self._consumir(final=True)
        if self._palavras:
            pedacos.append(self._emitir(Corte.FIM))
        else:
            pedacos.append(PedacoDeFala(texto="", inicio=len(self._texto), corte=Corte.FIM))
        return pedacos

    def descarregar(self) -> list[PedacoDeFala]:
        """Uma pausa do texto (a vez do motor acabou e uma ferramenta vai rodar): o que já chegou
        sai agora. Os lotes normais saem pela regra de sempre; o residual sai com corte `PAUSA`,
        mesmo abaixo de 14 palavras — é o "só menor no fim, se não houver texto suficiente" da
        regra do dono, porque até a ferramenta voltar não há. A última palavra conta como
        completa (a vez acabou: ela não continua). O fatiador segue aberto para o resto."""
        if self._fechado:
            return []
        pedacos = self._consumir(final=True)
        if self._palavras:
            pedacos.append(self._emitir(Corte.PAUSA))
        return pedacos

    def _consumir(self, *, final: bool) -> list[PedacoDeFala]:
        pedacos: list[PedacoDeFala] = []
        texto = self._texto
        i = self._varrido
        while i < len(texto):
            while i < len(texto) and texto[i].isspace():
                i += 1
            inicio = i
            while i < len(texto) and not texto[i].isspace():
                i += 1
            if inicio == i:
                break
            if i == len(texto) and not final:
                # Palavra que encosta no fim pode continuar no próximo delta.
                i = inicio
                break
            palavra = texto[inicio:i]
            self._palavras.append((inicio, palavra))
            corte = _corte_de(palavra)
            limite = self.primeiro if self._emitidos == 0 else self.seguintes
            if len(self._palavras) < self.minimo:
                continue
            if corte is not None:
                pedacos.append(self._emitir(corte))
            elif len(self._palavras) >= limite:
                pedacos.append(self._emitir(Corte.LIMITE))
        self._varrido = i
        return pedacos

    def _emitir(self, corte: Corte) -> PedacoDeFala:
        inicio = self._palavras[0][0]
        texto = " ".join(palavra for _, palavra in self._palavras)
        self._palavras.clear()
        self._emitidos += 1
        return PedacoDeFala(texto=texto, inicio=inicio, corte=corte)


def _corte_de(palavra: str) -> Corte | None:
    if palavra.endswith(PONTUACAO_DE_FRASE):
        return Corte.FRASE
    if palavra.endswith(PONTUACAO_DE_VIRGULA):
        return Corte.VIRGULA
    return None


def fatiar_tudo(texto: str) -> list[PedacoDeFala]:
    """O texto inteiro de uma vez — sem o pedaço vazio do fim."""
    fatiador = FatiadorDeFala()
    pedacos = fatiador.alimentar(texto) + fatiador.fechar()
    return [p for p in pedacos if p.texto]


def fatiar_em_deltas(deltas: Iterable[str]) -> list[PedacoDeFala]:
    """O mesmo texto chegando aos poucos. Tem de dar os mesmos pedaços que `fatiar_tudo`."""
    fatiador = FatiadorDeFala()
    pedacos: list[PedacoDeFala] = []
    for delta in deltas:
        pedacos += fatiador.alimentar(delta)
    return [p for p in pedacos + fatiador.fechar() if p.texto]
