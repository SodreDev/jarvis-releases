"""WER e CER: as métricas de transcrição, com a normalização escrita (cartão F1-06).

Número de WER só se compara com outro WER se a **normalização** for a mesma. Então ela está
aqui, explícita e testada: minúsculas, acentos preservados (é pt-BR: "pais" e "país" são
palavras diferentes), pontuação removida, espaços colapsados. Nada de remover acento "para
facilitar" — isso inflaria o acerto de um ASR que erra acento.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

PONTUACAO: Final = re.compile(r"[^\w\s]", re.UNICODE)
ESPACOS: Final = re.compile(r"\s+")


def normalizar(texto: str) -> str:
    """Minúsculas, sem pontuação, espaços colapsados — acentos **preservados**."""
    semi = unicodedata.normalize("NFC", texto).lower()
    return ESPACOS.sub(" ", PONTUACAO.sub(" ", semi)).strip()


def palavras(texto: str) -> list[str]:
    normalizado = normalizar(texto)
    return normalizado.split(" ") if normalizado else []


@dataclass(frozen=True, slots=True)
class Distancia:
    """Edições que levam a referência à hipótese, separadas por tipo."""

    substituicoes: int
    insercoes: int
    remocoes: int
    referencia: int

    @property
    def erros(self) -> int:
        return self.substituicoes + self.insercoes + self.remocoes

    @property
    def taxa(self) -> float:
        """Erros sobre o tamanho da **referência** (pode passar de 1,0, e isso é correto)."""
        return self.erros / self.referencia if self.referencia else 0.0


def alinhar(referencia: Sequence[str], hipotese: Sequence[str]) -> Distancia:
    """Levenshtein com rastro dos tipos de erro (programação dinâmica, O(n·m))."""
    n, m = len(referencia), len(hipotese)
    # custo[i][j] = (erros, subs, ins, rem) para referencia[:i] → hipotese[:j]
    custo: list[list[tuple[int, int, int, int]]] = [[(0, 0, 0, 0)] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        custo[i][0] = (i, 0, 0, i)
    for j in range(1, m + 1):
        custo[0][j] = (j, 0, j, 0)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if referencia[i - 1] == hipotese[j - 1]:
                custo[i][j] = custo[i - 1][j - 1]
                continue
            substituir = custo[i - 1][j - 1]
            inserir = custo[i][j - 1]
            remover = custo[i - 1][j]
            melhor = min(substituir[0], inserir[0], remover[0])
            if substituir[0] == melhor:
                custo[i][j] = (melhor + 1, substituir[1] + 1, substituir[2], substituir[3])
            elif inserir[0] == melhor:
                custo[i][j] = (melhor + 1, inserir[1], inserir[2] + 1, inserir[3])
            else:
                custo[i][j] = (melhor + 1, remover[1], remover[2], remover[3] + 1)
    _, subs, ins, rem = custo[n][m]
    return Distancia(substituicoes=subs, insercoes=ins, remocoes=rem, referencia=n)


def wer(referencia: str, hipotese: str) -> Distancia:
    """*Word Error Rate*: erros de palavra sobre palavras da referência."""
    return alinhar(palavras(referencia), palavras(hipotese))


def cer(referencia: str, hipotese: str) -> Distancia:
    """*Character Error Rate*: o mesmo em caracteres (espaço conta, acento conta)."""
    return alinhar(list(normalizar(referencia)), list(normalizar(hipotese)))


def acordo_de_prefixo(anterior: str, atual: str) -> float:
    """Fração do texto atual que o passo anterior já dizia, em palavras.

    É a estabilidade de um parcial: ASR por janela crescente muda o fim da hipótese a cada
    passo, e o que já não muda é o que dá para usar. 1,0 quando o atual é continuação exata do
    anterior; 0,0 quando a primeira palavra já mudou.
    """
    a, b = palavras(anterior), palavras(atual)
    if not b:
        return 0.0
    comuns = 0
    for esquerda, direita in zip(a, b, strict=False):
        if esquerda != direita:
            break
        comuns += 1
    return comuns / len(b)
