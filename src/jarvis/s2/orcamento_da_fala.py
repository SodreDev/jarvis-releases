"""Falar menos: o que vai para a voz cabe num orçamento, e o resto fica na tela (dono, 2026-10-21).

Pedido do dono: "resumir a EXECUÇÃO de ações em 3 a 4 frases curtas, a menos que o dono peça
para detalhar o que achou/fez; resposta falada curta por padrão, texto longo vai para a tela (não
para o TTS) quando o dono não pediu detalhe". A persona pede isso ao modelo, e o modelo nem sempre
obedece — por isso o teto é **do código** (emenda de 2026-10-21 à ADR-0031):

- até `FRASES_NA_VOZ` (4) frases e `PALAVRAS_NA_VOZ` (60) palavras vão para o TTS;
- passou disso, a voz diz as três primeiras e o fecho «O resto está na tela.» — **quatro frases no
  total, nunca mais**; a quarta frase da resposta espera para saber se vem uma quinta (o lote de
  fala da terceira ainda está tocando, então a espera não se ouve);
- uma frase só, comprida demais, é cortada na última vírgula (ou palavra) dentro das 60 palavras;
- a tela recebe **tudo**, como antes (`mostrar`); o que ficou só nela vai junto para a conversa,
  marcado, para o modelo saber que o dono já viu;
- com o dono pedindo detalhe ("explica", "detalha", "lê pra mim", "o que você achou/fez", "passo a
  passo"…) não há teto: ele pediu para ouvir.

Pergunta nunca passa por aqui: uma pergunta cortada não pode ser respondida (o "sim" só vale depois
de ela tocar inteira, ADR-0038). Nem as frases que o código monta (o aviso de uma moderada, a frase
ao delegar): já são curtas e são o que permite o "desfaz".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Final

FRASES_NA_VOZ: Final = 4
PALAVRAS_NA_VOZ: Final = 60
FECHO: Final = "O resto está na tela."
FIM_DE_FRASE: Final = (".", "!", "?", "…")
FECHAMENTOS: Final = "\"'”’»)]"
"""O que pode vir depois do ponto e ainda ser o fim da frase ("ele disse «sim».»", "(pronto.)")."""
ABREVIACOES: Final = frozenset(
    {
        "sr.", "sra.", "srta.", "dr.", "dra.", "prof.", "profa.", "etc.", "ex.", "pág.", "pag.",
        "av.", "obs.", "vs.", "nº.", "no.", "tel.", "cel.", "aprox.", "máx.", "mín.", "min.",
    }
)  # fmt: skip
"""Ponto que não fecha frase: "o Sr. Silva" é uma frase só."""
VIRGULAS: Final = (",", ";", ":")
PEDE_DETALHE: Final[tuple[str, ...]] = (
    "detalha", "detalhe", "detalhes", "detalhado", "detalhada", "detalhadamente",
    "explica", "explique", "explicar", "explicacao", "me conta tudo", "conta tudo",
    "fala tudo", "diz tudo", "diga tudo", "le pra mim", "le para mim", "leia", "le o texto",
    "le a", "le o", "o que voce achou", "o que achou", "o que voce fez", "o que fez",
    "passo a passo", "por extenso", "fala mais", "me fala mais", "mais detalhes",
    "com detalhes", "em detalhes", "tudo o que", "lista tudo", "todos os", "todas as",
    "me conta", "me conte", "conta uma", "conte uma", "historia", "historinha",
)  # fmt: skip
"""O dono quer ouvir mais: estas falas tiram o teto da voz (palavra inteira, sem acento). Quem pede
uma história ("me conta uma história") quer ouvi-la inteira."""


def _dobrar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    palavras = re.sub(r"[^\w\s]", " ", sem_acento.casefold()).split()
    return " " + " ".join(palavras) + " "


def quer_detalhe(fala: str) -> bool:
    """O pedido do dono pede a resposta inteira na voz (explicar, detalhar, ler, o que achou)."""
    texto = _dobrar(fala)
    return any(f" {p} " in texto for p in PEDE_DETALHE)


def _fecha_frase(palavra: str) -> bool:
    nua = palavra.rstrip(FECHAMENTOS)
    if not nua.endswith(FIM_DE_FRASE):
        return False
    if nua.casefold() in ABREVIACOES:
        return False
    # Inicial de nome ("J. R. R. Tolkien"): letra sozinha com ponto não fecha frase.
    return not (len(nua) == 2 and nua[0].isalpha() and nua[1] == ".")


@dataclass(slots=True)
class OrcamentoDaFala:
    """Filtro do texto que vai para o TTS, em stream: devolve o que pode ser falado agora."""

    frases: int = FRASES_NA_VOZ
    palavras: int = PALAVRAS_NA_VOZ
    livre: bool = False
    """O dono pediu detalhe: tudo vai para a voz."""
    cortou: bool = False
    """Algo da resposta ficou só na tela."""
    frases_faladas: int = 0
    _texto: str = ""
    _lido: int = 0
    """Até onde o texto já foi varrido em busca de palavra completa."""
    _inicio_da_frase: int = 0
    """Onde começa (no texto recebido) a frase que ainda não fechou."""
    _palavras_da_frase: list[tuple[int, int]] = field(default_factory=list)
    """(início, fim) de cada palavra completa da frase em curso."""
    _palavras_faladas: int = 0
    _guardada: tuple[int, int] | None = None
    """A quarta frase: espera para saber se vem uma quinta (então ela não é dita)."""
    _corte: int = -1
    """Do corte em diante, o texto é só da tela."""
    _fechado: bool = False

    @property
    def so_na_tela(self) -> str:
        """O que a voz não disse (vazio se nada foi cortado)."""
        return " ".join(self._texto[self._corte :].split()) if self.cortou else ""

    def passar(self, delta: str) -> str:
        """Acrescenta texto do motor e devolve o pedaço que pode ir para a voz agora."""
        if self._fechado:
            raise RuntimeError("orçamento fechado: a resposta acabou")
        self._texto += delta
        if self.livre:
            return delta
        return self._varrer(final=False)

    def fechar(self) -> str:
        """Fim da resposta: o que ainda cabe (a quarta frase guardada, a última sem ponto) ou o
        fecho, se algo ficou de fora."""
        if self._fechado:
            return ""
        self._fechado = True
        if self.livre:
            return ""
        return self._varrer(final=True)

    # --- por dentro ------------------------------------------------------------------------
    def _varrer(self, *, final: bool) -> str:
        saida: list[str] = []
        if self.cortou:
            return ""
        for inicio, fim, separador in self._palavras_novas(final=final):
            self._palavras_da_frase.append((inicio, fim))
            palavra = self._texto[inicio:fim]
            fecha = _fecha_frase(palavra) or "\n" in separador
            if fecha:
                saida.append(self._frase_completa(fim))
            elif self._estourou_na_frase():
                saida.append(self._cortar_frase_comprida())
            if self._ja_cortou():
                return "".join(saida)
        if final:
            if self._palavras_da_frase:  # a última frase, sem pontuação no fim
                saida.append(self._frase_completa(len(self._texto)))
            if not self._ja_cortou() and self._guardada is not None:
                saida.append(self._soltar_a_guardada())
        return "".join(saida)

    def _ja_cortou(self) -> bool:
        """Lido por método: cada frase pode cortar no meio da varredura."""
        return self.cortou

    def _palavras_novas(self, *, final: bool) -> list[tuple[int, int, str]]:
        """Palavras completas desde a última varredura: (início, fim, o espaço que veio depois)."""
        achadas: list[tuple[int, int, str]] = []
        for achado in re.finditer(r"\S+(\s+)", self._texto[self._lido :]):
            inicio = self._lido + achado.start()
            fim = self._lido + achado.start(1)
            achadas.append((inicio, fim, achado.group(1)))
        if achadas:
            ultimo = achadas[-1]
            self._lido = ultimo[1] + len(ultimo[2])
        if final:
            resto = self._texto[self._lido :]
            if resto.strip():
                inicio = self._lido + (len(resto) - len(resto.lstrip()))
                achadas.append((inicio, len(self._texto.rstrip()), ""))
                self._lido = len(self._texto)
        return achadas

    def _frase_completa(self, fim: int) -> str:
        """Uma frase fechou: fala, guarda (a quarta) ou corta (a quinta, ou a que passa do teto de
        palavras)."""
        n = len(self._palavras_da_frase)
        inicio = self._inicio_da_frase
        if n == 0:
            self._inicio_da_frase = fim
            return ""
        if self._guardada is not None:
            # Uma quinta frase: a resposta passa do orçamento. A quarta fica na tela.
            self._reiniciar_frase(fim)
            return self._cortar(self._guardada[0])
        if self._palavras_faladas + n > self.palavras:
            dito = self._cortar_frase_comprida()
            self._reiniciar_frase(fim)
            return dito
        self._reiniciar_frase(fim)
        if self.frases_faladas + 1 >= self.frases:
            self._guardada = (inicio, fim)
            return ""
        self.frases_faladas += 1
        self._palavras_faladas += n
        return self._texto[inicio:fim]

    def _reiniciar_frase(self, fim: int) -> None:
        self._palavras_da_frase = []
        self._inicio_da_frase = fim

    def _estourou_na_frase(self) -> bool:
        return self._palavras_faladas + len(self._palavras_da_frase) > self.palavras

    def _cortar_frase_comprida(self) -> str:
        """A frase em curso passou do teto de palavras antes de fechar: se nada foi dito, diz o
        começo dela (até a última vírgula, ou a última palavra que cabe) e corta; senão, corta."""
        if self.frases_faladas or self._guardada is not None:
            return self._cortar(self._guardada[0] if self._guardada else self._inicio_da_frase)
        cabem = self._palavras_da_frase[: self.palavras - self._palavras_faladas]
        fim = cabem[-1][1]
        for _inicio, fim_da_palavra in reversed(cabem[len(cabem) // 2 :]):
            if self._texto[:fim_da_palavra].endswith(VIRGULAS):
                fim = fim_da_palavra
                break
        dito = self._texto[self._inicio_da_frase : fim].rstrip(", ;:")
        self.frases_faladas += 1
        self._palavras_faladas += len(cabem)
        return dito + "… " + self._cortar(fim)

    def _soltar_a_guardada(self) -> str:
        assert self._guardada is not None
        inicio, fim = self._guardada
        self._guardada = None
        self.frases_faladas += 1
        return self._texto[inicio:fim]

    def _cortar(self, desde: int) -> str:
        self.cortou = True
        self._corte = desde
        self._guardada = None
        self.frases_faladas += 1
        return f" {FECHO}"


def orcar(texto: str, *, livre: bool = False) -> tuple[str, str]:
    """O mesmo, para um texto inteiro: (o que a voz diz, o que fica só na tela)."""
    orcamento = OrcamentoDaFala(livre=livre)
    falado = orcamento.passar(texto) + orcamento.fechar()
    return " ".join(falado.split()), orcamento.so_na_tela


__all__ = [
    "FECHO",
    "FRASES_NA_VOZ",
    "PALAVRAS_NA_VOZ",
    "OrcamentoDaFala",
    "orcar",
    "quer_detalhe",
]
