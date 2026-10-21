"""Ruído do microfone não vira pedido (dono, 2026-10-21; ADR-0043).

**A causa, medida, e não suposta.** Estalos, teclado, respiração e ventilador viravam palavras
porque o laço mandava ao ASR qualquer trecho que o VAD abrisse — bastava uma janela de 32 ms —,
com 400 ms de antes e mais de um segundo de silêncio depois, e o whisper local recebia como dica
uma lista de 480 caracteres com os nomes de todos os apps instalados. Com áudio sintético
(`tools/harness_ruido.py`, `docs/medicoes/ruido-e-dica.md`): **sem** a dica, nenhum ruído forçado
no whisper virou texto; **com** a lista de apps, todos viraram — "Bazaar, Bazaar, Borderlands 2,
Brave Web Browser", "Clique no clipe para ver o que está acontecendo" —, e o `no_speech_prob`
desses textos ficou entre 0,39 e 0,64, quando na fala sintética ficou em 0,14 ou menos. A regra
padrão do Whisper (`no_speech_prob` > 0,6 **e** `avg_logprob` < −1) deixava quase todos passarem.

**Defesa em camadas, cada uma barata e com padrão seguro:**

1. **O portão do trecho, antes do ASR** (`medir_trecho` + `julgar_audio`): energia por quadro de
   20 ms, o fundo (percentil 20 do próprio trecho, que traz os 400 ms de antes e o silêncio do
   fim) e o pico (percentil 95). Fala é pelo menos `fala_minima_ms` **seguidos** acima do fundo
   mais `margem_db` (`IMPULSO`: estalo, tecla, clique duram 20 a 60 ms); e o trecho tem de ter
   algo acima do fundo (`FUNDO`: ventilador e chiado não têm contraste). Recusado aqui, o ASR nem
   roda — o que **economiza** latência, CPU e, na Groq, uma cobrança de 10 s.
2. **O filtro da transcrição** (`julgar_texto`): só símbolos (`SO_SIMBOLOS`); frase de legenda e
   de fim de vídeo que o ASR inventa no silêncio (`ALUCINACAO`, sempre — "Legendas pela comunidade
   Amara.org", "Obrigado por assistir", "Inscreva-se no canal"); o modelo em laço (`REPETICAO`);
   o próprio modelo dizendo que não era fala (`SEM_FALA`: `no_speech_prob` alto **e** logprob
   baixo); e, quando os sinais não são fortes, a cortesia solta ("Obrigado.", "Tchau.") e o eco
   da dica (o texto só com os termos que foram de dica — "Jarvis." no meio da respiração) e o
   texto curto de confiança baixa (`INCERTO_CURTO`).
3. **No laço** (`jarvis.voz.app`): um "sim" falado só responde a uma pergunta pendente com sinais
   fortes; "Jarvis. Obrigado." é o dono chamando (a cortesia depois do nome é o que o ASR inventa no
   silêncio do fim), não um pedido.

**Fala curta passa.** "Sim", "não" e "para" têm 220 ms ou mais seguidos acima do fundo na fala
sintética (contra 20–40 ms do estalo e da tecla); o filtro de texto só corta a cortesia e o eco da
dica quando o próprio ASR não teve certeza. Motor que não mede sinais (o oráculo, os falsos de
teste) é julgado só pelas frases inventadas que valem sempre.

**O que não sai daqui:** nada é gravado — nem o áudio, nem o texto. O laço conta os descartes e a
trilha de diagnóstico leva o código do motivo e números (duração, contraste, sinais do ASR).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import numpy as np

from jarvis.audio_io.quadro import (
    AMOSTRAS_POR_QUADRO,
    AMPLITUDE_MAXIMA,
    BYTES_POR_QUADRO,
    MS_POR_QUADRO,
    PISO_DB,
)
from jarvis.voz.interface import Sinais

# --- os padrões (ADR-0043) ---------------------------------------------------------------------
FALA_MINIMA_MS: Final = 100.0
"""Fala é pelo menos isto **seguido** acima do fundo. Estalo, tecla e clique ficam em 20–60 ms;
"sim", "não" e "para" sintéticos, em 220 ms ou mais — a borda fica longe dos dois."""
MARGEM_DB: Final = 6.0
"""Quanto acima do fundo um quadro tem de estar para contar como fala. O ventilador e o chiado
oscilam ±1–3 dB em torno do próprio nível; a vogal fica 15 a 40 dB acima do fundo."""
ENERGIA_MINIMA_DB: Final = -60.0
"""Abaixo disto nenhum quadro é fala, por mais silencioso que seja o fundo (o piso digital)."""
PERCENTIL_DO_FUNDO: Final = 20.0
PERCENTIL_DO_PICO: Final = 95.0
SEM_FALA_MAXIMO: Final = 0.35
"""`no_speech_prob` a partir do qual, com o logprob baixo, o trecho é "não era fala". Medido no
whisper small com áudio sintético: o texto inventado ficou em 0,39–0,64; a fala, em 0,14 ou
menos. Calibrar com a trilha na máquina do dono (a Groq turbo não foi medida)."""
LOGPROB_MINIMO: Final = -0.7
LOGPROB_MINIMO_CURTO: Final = -1.0
"""Texto de até `PALAVRAS_CURTAS` palavras com o logprob abaixo disto é chute do modelo."""
PALAVRAS_CURTAS: Final = 2
FORTE_SEM_FALA: Final = 0.2
FORTE_LOGPROB: Final = -0.8
"""Sinais **fortes** = `no_speech_prob` abaixo de 0,2 e logprob acima de −0,8: o que a fala
sintética teve e o texto inventado não. É o que libera a cortesia, o eco da dica e o "sim"."""
REPETICOES: Final = 4
"""A mesma palavra (ou par, ou trio) quatro vezes seguidas é o modelo em laço. Três não: "não,
não, não" e "para, para, para" são do dono."""
COMPRESSAO_MAXIMA: Final = 2.4
"""O limiar do próprio Whisper para texto repetido (`compression_ratio`)."""
CARACTERES_PARA_COMPRESSAO: Final = 30
"""Texto curto comprime mal por natureza: a compressão só conta a partir deste tamanho."""


class Motivo(StrEnum):
    """Por que o trecho não virou pedido — o código que vai para a trilha (nunca o texto)."""

    IMPULSO = "impulso"
    """Nada de fala que dure: estalo, tecla, clique do mouse."""
    FUNDO = "fundo"
    """Nada acima do fundo: silêncio, ventilador, chiado."""
    SO_SIMBOLOS = "so_simbolos"
    """O ASR devolveu só pontuação ou anotação ("...", "♪", "[Música]")."""
    ALUCINACAO = "alucinacao"
    """Frase que o ASR inventa no silêncio (legenda, fim de vídeo) ou cortesia solta sem certeza."""
    REPETICAO = "repeticao"
    """O modelo em laço: a mesma coisa várias vezes."""
    SEM_FALA = "sem_fala"
    """O próprio ASR diz que não era fala (`no_speech_prob` alto e logprob baixo)."""
    ECO_DA_DICA = "eco_da_dica"
    """O texto é só o que foi de dica ao ASR, sem certeza de fala."""
    INCERTO_CURTO = "incerto_curto"
    """Uma ou duas palavras com a confiança baixa."""
    SIM_INCERTO = "sim_incerto"
    """Um "sim" para a pergunta pendente, sem sinais fortes: não confirma (`jarvis.voz.app`)."""


@dataclass(frozen=True, slots=True)
class PoliticaDeRuido:
    """Os limiares, com os padrões da ADR-0043. O dono troca quatro deles no `jarvis-voz.toml`."""

    ligada: bool = True
    fala_minima_ms: float = FALA_MINIMA_MS
    margem_db: float = MARGEM_DB
    energia_minima_db: float = ENERGIA_MINIMA_DB
    sem_fala_maximo: float = SEM_FALA_MAXIMO
    logprob_minimo: float = LOGPROB_MINIMO
    logprob_minimo_curto: float = LOGPROB_MINIMO_CURTO
    palavras_curtas: int = PALAVRAS_CURTAS
    forte_sem_fala: float = FORTE_SEM_FALA
    forte_logprob: float = FORTE_LOGPROB
    repeticoes: int = REPETICOES
    compressao_maxima: float = COMPRESSAO_MAXIMA
    ignorar: tuple[str, ...] = ()
    """Frases que o dono mandou ignorar sempre (do vocabulário dele): somam às de legenda."""


PADRAO: Final = PoliticaDeRuido()
SEM_SINAIS: Final = Sinais()
"""O motor não mediu: o filtro usa só as frases que valem sempre."""


# --- 1. o portão do trecho -----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MedidaDoTrecho:
    """O que o portão viu no trecho. Só números: é o que vai para a trilha."""

    duracao_ms: float
    piso_db: float
    pico_db: float
    fala_ms: float
    """Quanto do trecho ficou acima do fundo mais a margem."""
    maior_fala_ms: float
    """A maior corrida desses quadros — é ela que separa a sílaba do estalo."""

    @property
    def contraste_db(self) -> float:
        return self.pico_db - self.piso_db


def _maior_corrida(marcas: np.ndarray) -> int:
    """O maior número de `True` seguidos."""
    if not marcas.any():
        return 0
    bordas = np.diff(np.concatenate(([0], marcas.astype(np.int8), [0])))
    inicios = np.flatnonzero(bordas == 1)
    fins = np.flatnonzero(bordas == -1)
    return int((fins - inicios).max())


def energias_db(amostras: bytes) -> np.ndarray:
    """A energia RMS de cada quadro de 20 ms, em dBFS, com o piso declarado do projeto."""
    quadros = len(amostras) // BYTES_POR_QUADRO
    if quadros == 0:
        return np.zeros(0)
    valores = np.frombuffer(amostras[: quadros * BYTES_POR_QUADRO], dtype="<i2").astype(np.float64)
    rms = np.sqrt(np.mean(np.square(valores.reshape(quadros, AMOSTRAS_POR_QUADRO)), axis=1))
    with np.errstate(divide="ignore"):
        db = 20.0 * np.log10(rms / AMPLITUDE_MAXIMA)
    return np.maximum(np.nan_to_num(db, neginf=PISO_DB), PISO_DB)


def medir_trecho(amostras: bytes, politica: PoliticaDeRuido = PADRAO) -> MedidaDoTrecho:
    """Fundo, pico e quanto do trecho é fala, por energia. Microssegundos para um trecho de
    segundos (numpy): o portão não atrasa o turno."""
    db = energias_db(amostras)
    if db.size == 0:
        return MedidaDoTrecho(0.0, PISO_DB, PISO_DB, 0.0, 0.0)
    piso = float(np.percentile(db, PERCENTIL_DO_FUNDO))
    pico = float(np.percentile(db, PERCENTIL_DO_PICO))
    limiar = max(piso + politica.margem_db, politica.energia_minima_db)
    fala = db >= limiar
    return MedidaDoTrecho(
        duracao_ms=float(db.size * MS_POR_QUADRO),
        piso_db=piso,
        pico_db=pico,
        fala_ms=float(fala.sum() * MS_POR_QUADRO),
        maior_fala_ms=float(_maior_corrida(fala) * MS_POR_QUADRO),
    )


def julgar_audio(medida: MedidaDoTrecho, politica: PoliticaDeRuido = PADRAO) -> Motivo | None:
    """O trecho tem fala que valha um ASR? `None` = tem; senão, o motivo de não ter."""
    if not politica.ligada:
        return None
    if (
        medida.duracao_ms <= 0
        or medida.pico_db < politica.energia_minima_db
        or medida.contraste_db < politica.margem_db
    ):
        return Motivo.FUNDO
    if medida.maior_fala_ms < politica.fala_minima_ms:
        return Motivo.IMPULSO
    return None


# --- 2. o filtro da transcrição ------------------------------------------------------------------
def normalizar(texto: str) -> str:
    """Sem acento, sem caixa, sem pontuação: só letras e números separados por espaço."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if unicodedata.category(c) != "Mn"
    ).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", sem_acento))


_ANOTACAO: Final = re.compile(r"\[[^\]]*\]|\([^)]*\)|♪[^♪]*♪?|\*[^*]*\*|[♪♫]")
"""Anotação de legenda (`[Música]`, `(risos)`, `♪ … ♪`): não é fala."""
_FRASES: Final = re.compile(r"(?<=[.!?…])\s+|\n+")

_SEMPRE: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(padrao)
    for padrao in (
        r"\bamara\s?org\b",
        r"^legendas? (pela|por|da|de|em|feitas?|criadas?|automaticas?)\b",
        r"^legendado\b",
        r"^legendagem\b",
        r"\badriana zanotto\b",
        r"^(transcricao|traducao) e legendas?\b",
        r"^subtitles? (by|made|created)\b",
        r"^sous titres\b",
        r"^untertitel\b",
        r"\bobrigad[oa]s? (por|pela?) (assistir|assistirem|terem assistido|acompanhar)\b",
        r"\b(inscreva|inscrevam) se\b|\bse (inscreva|inscrevam)\b",
        r"\bthanks? (you )?(so much )?for watching\b",
        r"\b(please|don t forget to) subscribe\b",
    )
)
"""Frases que o ASR inventa no silêncio — crédito de legenda e fim de vídeo, o que havia no treino
dele — e que o dono não diz ao Jarvis. Valem sempre, com ou sem sinais: saem do texto, e o resto
segue. O que pode ser pedido de verdade ("me inscreve no canal", "abre o link na descrição", "pula
até o próximo vídeo") **não** está aqui: está entre as fracas, que só caem sem certeza de fala."""

CORTESIAS: Final[frozenset[str]] = frozenset(
    {
        "obrigado",
        "obrigada",
        "obrigadao",
        "muito obrigado",
        "muito obrigada",
        "obrigado a todos",
        "valeu",
        "tchau",
        "tchau tchau",
        "ate mais",
        "ate logo",
        "ate breve",
        "ate a proxima",
        "falou",
        "thank you",
        "thanks",
        "bye",
        "bye bye",
    }
)
"""A cortesia solta: o que o Whisper mais inventa no fim de um trecho com silêncio."""

_FRACAS: Final[frozenset[str]] = CORTESIAS | frozenset(
    {"e ai", "musica", "aplausos", "risos", "silencio", "hum", "hmm", "humm", "ah", "eh", "uh"}
    | {"oh", "you"}
)
"""Texto inteiro que, sem sinais fortes, é mais provável invenção do que fala."""
_FRACAS_PADROES: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(padrao)
    for padrao in (
        r"clique (no|na|aqui)\b.*\bpara (ver|assistir|saber)\b.*",
        r"(deixe|deixem) (o )?(seu )?like( no video)?",
        r"(ative|ativem) o sininho",
        r"(o )?link (esta )?na descricao",
        r"(ate|nos vemos|vejo voces) no proximo video",
    )
)
"""Fim de vídeo que **também** poderia ser pedido: só cai quando é o texto inteiro (`fullmatch`) e
o ASR não teve certeza de que era fala."""

_SEM_PESO: Final[frozenset[str]] = frozenset(
    {"o", "a", "os", "as", "e", "de", "do", "da", "dos", "das", "um", "uma", "no", "na", "em"}
)
"""Palavras que não decidem se o texto é só a dica. "para" e "pra" ficam de fora de propósito:
"Jarvis, para" é uma ordem de parar, não o eco do nome."""


@dataclass(frozen=True, slots=True)
class Veredito:
    """O que sobra da transcrição para o laço, ou por que nada sobra."""

    texto: str
    """O texto sem as anotações e sem as frases inventadas (vazio quando descartado)."""
    motivo: Motivo | None = None
    aparado: bool = False
    """Tirou uma frase inventada (a legenda no fim) e o resto passou."""

    @property
    def descartado(self) -> bool:
        return self.motivo is not None


def sinais_fortes(sinais: Sinais, politica: PoliticaDeRuido = PADRAO) -> bool:
    """O ASR teve certeza de que ouviu fala? Sem sinal nenhum (motor que não mede), sim: a regra
    é não piorar o que já funcionava — e a ausência de medida não é evidência de ruído."""
    if sinais.sem_fala is None and sinais.logprob is None:
        return True
    if sinais.sem_fala is not None and sinais.sem_fala >= politica.forte_sem_fala:
        return False
    return not (sinais.logprob is not None and sinais.logprob <= politica.forte_logprob)


def _maior_repeticao(palavras: Sequence[str]) -> int:
    """Quantas vezes seguidas o mesmo bloco de 1 a 3 palavras aparece, no máximo."""
    melhor = 1
    for tamanho in (1, 2, 3):
        for inicio in range(len(palavras) - tamanho + 1):
            bloco = palavras[inicio : inicio + tamanho]
            vezes, fim = 1, inicio + tamanho
            while palavras[fim : fim + tamanho] == bloco:
                vezes, fim = vezes + 1, fim + tamanho
            melhor = max(melhor, vezes)
    return melhor


def _compressao(texto: str) -> float:
    import zlib

    bruto = texto.encode("utf-8")
    return len(bruto) / len(zlib.compress(bruto)) if bruto else 0.0


def _so_a_dica(palavras: Sequence[str], dica: Collection[str]) -> bool:
    uteis = [p for p in palavras if p not in _SEM_PESO]
    return bool(uteis) and all(p in dica for p in uteis)


def palavras_da_dica(dica: str) -> frozenset[str]:
    """As palavras do texto que foi de dica ao ASR, normalizadas — o que o eco reconhece."""
    return frozenset(normalizar(dica).split())


def so_cortesia(texto: str) -> bool:
    """O texto inteiro é uma cortesia solta ("Obrigado.", "Tchau tchau") ou frase de legenda."""
    normal = normalizar(_ANOTACAO.sub(" ", texto))
    return bool(normal) and (normal in CORTESIAS or any(p.search(normal) for p in _SEMPRE))


def julgar_texto(
    texto: str,
    sinais: Sinais = SEM_SINAIS,
    *,
    politica: PoliticaDeRuido = PADRAO,
    dica: Collection[str] = frozenset(),
) -> Veredito:
    """O que da transcrição é fala do dono. `dica` = as palavras que foram de dica ao ASR."""
    if not politica.ligada:
        return Veredito(texto)
    sem_anotacao = " ".join(_ANOTACAO.sub(" ", texto).split())
    if not normalizar(sem_anotacao):
        return Veredito("", Motivo.SO_SIMBOLOS if texto.strip() else None)
    ignorar = frozenset(normalizar(frase) for frase in politica.ignorar) - {""}
    frases = [f for f in _FRASES.split(sem_anotacao) if f.strip()]
    mantidas = [
        frase
        for frase in frases
        if not any(p.search(normalizar(frase)) for p in _SEMPRE)
        and normalizar(frase) not in ignorar
    ]
    restante = " ".join(mantidas).strip()
    aparado = len(mantidas) < len(frases)
    normal = normalizar(restante)
    if not normal:
        return Veredito("", Motivo.ALUCINACAO if aparado else Motivo.SO_SIMBOLOS)
    palavras = normal.split()
    if _maior_repeticao(palavras) >= politica.repeticoes or (
        len(normal) >= CARACTERES_PARA_COMPRESSAO
        and max(sinais.compressao or 0.0, _compressao(normal)) > politica.compressao_maxima
    ):
        return Veredito("", Motivo.REPETICAO)
    if (
        sinais.sem_fala is not None
        and sinais.sem_fala >= politica.sem_fala_maximo
        and (sinais.logprob is None or sinais.logprob <= politica.logprob_minimo)
    ):
        return Veredito("", Motivo.SEM_FALA)
    forte = sinais_fortes(sinais, politica)
    if not forte and (normal in _FRACAS or any(p.fullmatch(normal) for p in _FRACAS_PADROES)):
        return Veredito("", Motivo.ALUCINACAO)
    if not forte and dica and _so_a_dica(palavras, dica):
        return Veredito("", Motivo.ECO_DA_DICA)
    if (
        len(palavras) <= politica.palavras_curtas
        and sinais.logprob is not None
        and sinais.logprob < politica.logprob_minimo_curto
    ):
        return Veredito("", Motivo.INCERTO_CURTO)
    return Veredito(restante, None, aparado)


__all__ = [
    "CORTESIAS",
    "PADRAO",
    "MedidaDoTrecho",
    "Motivo",
    "PoliticaDeRuido",
    "Veredito",
    "energias_db",
    "julgar_audio",
    "julgar_texto",
    "medir_trecho",
    "normalizar",
    "palavras_da_dica",
    "sinais_fortes",
    "so_cortesia",
]
