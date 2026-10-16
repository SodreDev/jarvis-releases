"""Em que pé o laço de voz está — a única coisa que a tela precisa saber (ADR-0019).

**Por que o estado mora aqui e não na janela.** Quem sabe se o Jarvis está ouvindo, pensando
ou falando é o laço: ele é o dono do epoch, é ele que chama o ASR, o gerador de resposta e o
TTS. Uma tela que *deduzisse* o estado — pelo texto que apareceu, pelo tempo que passou —
acabaria mostrando "falando" depois de uma interrupção, que é exatamente a mentira que o
indicador de microfone do F1-13 foi desenhado para não contar.

São quatro, e de propósito: cada um é uma frase que cabe num canto de tela e que o dono
entende sem legenda. Mais estados (aquecendo, transcrevendo, sintetizando) seriam detalhe
nosso virando ruído dele.
"""

from __future__ import annotations

from enum import StrEnum


class Estado(StrEnum):
    """O que o laço está fazendo agora."""

    PARADO = "parado"
    """Nada em curso: o laço não está aberto, ou terminou."""

    OUVINDO = "ouvindo"
    """A fonte está aberta e a vez é do dono."""

    PENSANDO = "pensando"
    """Entre o fim da fala dele e o primeiro pedaço de áudio nosso: ASR e resposta."""

    FALANDO = "falando"
    """O Jarvis está entregando áudio. É o estado em que a interrupção importa."""

    @property
    def frase(self) -> str:
        """Uma frase por estado, a mesma no terminal e na janela."""
        return {
            Estado.PARADO: "parado",
            Estado.OUVINDO: "ouvindo você",
            Estado.PENSANDO: "pensando",
            Estado.FALANDO: "falando",
        }[self]
