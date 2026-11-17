"""Os delimitadores da fala de quem liga (ADR-0074, a ideia do dono, com o limite dela).

A cada chamada, `secrets` sorteia **dois** marcadores diferentes, cada um com vários tokens
aleatórios (4 tokens × 25 bits = 100 bits cada), sem caractere fixo que os identifique. Toda fala
transcrita de quem liga entra entre eles. Eles nunca são falados, mostrados nem gravados na trilha;
morrem com a chamada — a chamada seguinte sorteia outros.

Antes de envolver, `neutralizar` procura no texto **qualquer** token dos dois marcadores (sem
diferenciar maiúscula, ignorando separadores): achou, troca por `[delimitador removido]` e avisa —
quem liga não tem como saber os tokens, então isso só acontece se alguém tentou forjar. O aviso
vira notificação ao agente (dado), nunca frase pronta. As quebras de linha da transcrição viram
espaço: a fala não consegue «abrir» uma linha que pareça do sistema.

O limite: o delimitador ajuda o modelo a não confundir papéis, mas não torna a injeção impossível.
A primeira linha de defesa é o privilégio mínimo (`jarvis.chamada.agente`)."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Final

TOKENS_POR_MARCADOR: Final = 4
CARACTERES_POR_TOKEN: Final = 5
_ALFABETO: Final = "abcdefghijkmnpqrstuvwxyz23456789"
"""32 símbolos (sem l, o, 0, 1): 5 bits por caractere, 25 por token."""
REMOVIDO: Final = "[delimitador removido]"


def _token() -> str:
    return "".join(secrets.choice(_ALFABETO) for _ in range(CARACTERES_POR_TOKEN))


@dataclass(frozen=True, slots=True)
class Delimitadores:
    abre: str
    fecha: str

    @classmethod
    def sortear(cls) -> Delimitadores:
        while True:
            abre = " ".join(_token() for _ in range(TOKENS_POR_MARCADOR))
            fecha = " ".join(_token() for _ in range(TOKENS_POR_MARCADOR))
            if not set(abre.split()) & set(fecha.split()):
                return cls(abre, fecha)

    @property
    def tokens(self) -> tuple[str, ...]:
        return (*self.abre.split(), *self.fecha.split())

    def neutralizar(self, texto: str) -> tuple[str, bool]:
        """O texto sem nenhum token dos marcadores (e numa linha só), e se havia algum."""
        limpo = " ".join(str(texto).split())
        forjou = False
        for token in self.tokens:
            # Separadores entre as letras não escondem o token («k-7-q-2-m», «K7Q2M»).
            padrao = re.compile(r"[\W_]*".join(re.escape(c) for c in token), re.IGNORECASE)
            limpo, trocas = padrao.subn(REMOVIDO, limpo)
            forjou = forjou or trocas > 0
        return limpo, forjou

    def envolver(self, texto: str) -> str:
        """O texto já neutralizado entre os marcadores, cada um na sua linha."""
        return f"{self.abre}\n{texto}\n{self.fecha}"


__all__ = ["REMOVIDO", "Delimitadores"]
