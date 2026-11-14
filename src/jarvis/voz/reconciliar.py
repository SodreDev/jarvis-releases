"""Reconciliação por som: a palavra que o ASR errou, achada pelo som e pelo contexto (ADR-0067).

O ASR erra de um jeito que se reconhece: «mãe» sai «ma i», «WhatsApp» sai «what's up» ou «note
pad», uma sigla sai soletrada («gepe madi»). O texto que chega é **som parecido** com o que o dono
disse — e o contexto da frase diz que tipo de palavra cabia ali: depois de «abre o» vem um app,
depois de «mensagem no» vem um mensageiro, depois de «minha» vem gente da família.

Aqui o código faz a parte segura disso, antes do cérebro e antes do caminho rápido:

1. **candidatos do contexto do dono** — o léxico base (família, apps e IAs comuns, com a pronúncia
   brasileira), o vocabulário dele (ADR-0044), os apps autorizados e os nomes das memórias fixas;
2. **a vaga da frase** — o que vem antes do trecho decide que tipos cabem nele;
3. **o som** — `som()` reduz a fala a classes de som do pt-BR (`jarvis.voz.palavra`), soletra a
   sigla como se fala («GPT» → «gê pê tê»), lê a grafia inglesa como o brasileiro lê («wh» → «u»)
   e põe o «i» que o brasileiro põe depois da consoante final («pad» → «padi»).

**Só troca com confiança.** Som quase igual (`TROCA_CERTA`) troca; som parecido numa vaga que só
admite aquele tipo (`TROCA_PALPITE`) troca **e** avisa — o cérebro diz o que entendeu; abaixo
disso, nada muda e a nota leva os candidatos (o cérebro decide ou pergunta curto). Fora de vaga, só
trecho de duas ou três palavras (o ASR partiu um nome) e só com som quase igual: palavra comum
solta nunca vira outra.

A nota da voz (`NOTA_DA_VOZ`) vai **no turno**, como a linha do tom (ADR-0058) — não na persona: o
prompt-base tem teto (ADR-0047) e o turno digitado não precisa dela.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

from jarvis.voz.palavra import fonetica_simples, similaridade

TROCA_CERTA: Final = 0.86
"""Som quase igual: troca sem perguntar («ma i» → «mãe», «uotsapi» → «WhatsApp»)."""
TROCA_PALPITE: Final = 0.5
"""Som parecido numa vaga que só admite aquele tipo: troca e o cérebro diz o que entendeu."""
DUVIDA: Final = 0.65
"""Abaixo da troca e acima disto: não muda nada, e a nota leva os candidatos."""
MARGEM: Final = 0.08
"""O melhor candidato tem de ganhar do segundo por isto — empate não é certeza."""
LIMITE_DE_CANDIDATOS: Final = 400
LIMITE_DE_PALAVRAS: Final = 40

NOTA_DA_VOZ: Final = (
    "Este pedido veio do reconhecimento de voz e pode ter palavra trocada por outra de som "
    "parecido («ma i» por «mãe», «note pad» por «WhatsApp»): entenda pelo som e pelo contexto; "
    "se ainda não fizer sentido, pergunte curto."
)


@dataclass(frozen=True, slots=True)
class Candidato:
    """Uma palavra que o dono costuma dizer: como se escreve, de que tipo é, como soa."""

    escrita: str
    tipo: str
    """`pessoa`, `app`, `mensageiro`, `ia` ou `termo` — é o que a vaga da frase confere."""
    fala: str = ""
    """A pronúncia brasileira, quando a grafia engana («uótsápi»); mais de uma, separadas por
    `|`. Vazio = a própria grafia."""


def _c(escrita: str, tipo: str, fala: str = "") -> Candidato:
    return Candidato(escrita, tipo, fala)


LEXICO_BASE: Final[tuple[Candidato, ...]] = (
    # A família: é como o dono fala dos contatos mais comuns («liga pra minha mãe»).
    *(
        _c(p, "pessoa")
        for p in (
            "mãe",
            "pai",
            "mamãe",
            "papai",
            "vó",
            "vô",
            "vovó",
            "vovô",
            "avó",
            "avô",
            "irmão",
            "irmã",
            "tio",
            "tia",
            "esposa",
            "marido",
            "filho",
            "filha",
            "namorada",
            "namorado",
            "sogra",
            "sogro",
            "primo",
            "prima",
        )
    ),
    # Mensageiros: a vaga «mensagem no ___» só admite estes.
    _c("WhatsApp", "mensageiro", "uótsápi|uátsápi"),
    _c("Telegram", "mensageiro", "télegram"),
    _c("Instagram", "mensageiro", "ínstagram"),
    _c("Messenger", "mensageiro", "méssendjer"),
    _c("Discord", "mensageiro", "díscórd"),
    _c("Signal", "mensageiro", "síguinal"),
    # Apps comuns, com a pronúncia que o brasileiro usa.
    _c("YouTube", "app", "iutúbi|iutiúbi"),
    _c("Spotify", "app", "spótifai"),
    _c("Gmail", "app", "djimêiu"),
    _c("Google", "app", "gúgou"),
    _c("Chrome", "app", "crôumi"),
    _c("Firefox", "app", "fáierfóquis"),
    _c("Brave", "app", "brêivi"),
    _c("Steam", "app", "stím"),
    _c("Netflix", "app", "nétiflics"),
    _c("TikTok", "app", "tíquitóqui"),
    _c("Facebook", "app", "feicebúqui"),
    _c("Notion", "app", "nôuxan"),
    _c("Zoom", "app", "zúm"),
    _c("Outlook", "app", "áutluqui"),
    # As IAs que o dono cita: «pergunta pro GPT».
    _c("ChatGPT", "ia", "tchat gê pê tê"),
    _c("GPT", "ia", "gê pê tê"),
    _c("Gemini", "ia", "djêmini"),
    _c("Claude", "ia", "clóudi"),
    _c("Copilot", "ia", "cópailóti"),
    _c("Grok", "ia", "gróqui"),
    _c("DeepSeek", "ia", "dípsíqui"),
    _c("Perplexity", "ia", "perpléxiti"),
)

APPS: Final = frozenset({"app", "mensageiro", "ia", "termo"})
GENTE: Final = frozenset({"pessoa", "termo"})


@dataclass(frozen=True, slots=True)
class Vaga:
    """O que vem antes do trecho, e que tipos cabem depois dele."""

    antes: tuple[str, ...]
    tipos: frozenset[str]
    palpite: float | None = None
    """Parecença mínima para trocar como palpite numa vaga de conjunto fechado (os mensageiros:
    «note pad» depois de «mensagem no» só pode ser um deles). `None` = só troca com som quase
    igual — gente e app são palavras de verdade («minha mana» não vira «mamãe»)."""


VAGAS: Final[tuple[Vaga, ...]] = (
    Vaga(("mensagem", "no"), frozenset({"mensageiro"}), TROCA_PALPITE),
    Vaga(("mensagem", "pelo"), frozenset({"mensageiro"}), TROCA_PALPITE),
    Vaga(("mensagem", "via"), frozenset({"mensageiro"}), TROCA_PALPITE),
    Vaga(("manda", "no"), frozenset({"mensageiro"}), TROCA_PALPITE),
    Vaga(("zap", "da"), frozenset({"pessoa"})),
    Vaga(("contato", "da", "minha"), GENTE),
    Vaga(("contato", "do", "meu"), GENTE),
    Vaga(("minha",), GENTE),
    Vaga(("meu",), GENTE),
    Vaga(("pergunta", "pro"), frozenset({"ia", "pessoa", "termo"})),
    Vaga(("pergunta", "pra"), frozenset({"ia", "pessoa", "termo"})),
    Vaga(("pergunta", "ao"), frozenset({"ia", "termo"})),
    Vaga(("abre", "o"), APPS),
    Vaga(("abre", "a"), APPS),
    Vaga(("abrir", "o"), APPS),
    Vaga(("abra", "o"), APPS),
    Vaga(("fecha", "o"), APPS),
    Vaga(("fechar", "o"), APPS),
    Vaga(("abre",), APPS),
    Vaga(("fecha",), APPS),
    Vaga(("no",), APPS),
    Vaga(("pro",), frozenset({"pessoa", "ia", "termo"})),
    Vaga(("pra",), frozenset({"pessoa", "ia", "termo"})),
    Vaga(("liga", "pro"), GENTE),
    Vaga(("liga", "pra"), GENTE),
)
"""As mais longas primeiro decidem: «mensagem no» antes de «no»."""

PARADAS: Final = frozenset(
    {
        "o",
        "a",
        "os",
        "as",
        "e",
        "de",
        "do",
        "da",
        "dos",
        "das",
        "um",
        "uma",
        "no",
        "na",
        "em",
        "pra",
        "pro",
        "para",
        "com",
        "que",
        "se",
        "por",
        "pelo",
        "pela",
        "ou",
        "mas",
        "meu",
        "minha",
        "seu",
        "sua",
        "ele",
        "ela",
        "eu",
        "voce",
        "jarvis",
        "por favor",
        "agora",
        "ai",
        "aqui",
        "la",
        "isso",
        "esse",
        "essa",
        "este",
        "esta",
    }
)
"""Palavras que fecham o trecho da vaga (não fazem parte do nome)."""

COMUNS: Final = frozenset(
    {
        "navegador",
        "arquivo",
        "arquivos",
        "pasta",
        "site",
        "link",
        "video",
        "musica",
        "terminal",
        "jogo",
        "programa",
        "app",
        "aplicativo",
        "grupo",
        "chat",
        "email",
        "computador",
        "janela",
        "aba",
        "pagina",
        "documento",
        "foto",
        "imagem",
        "tela",
        "som",
        "volume",
        "contato",
        "contatos",
        "mensagem",
        "mensagens",
        "audio",
        "texto",
        "lista",
        "agenda",
        "calendario",
        "relogio",
        "alarme",
        "timer",
        "previsao",
        "tempo",
        "noticia",
        "noticias",
        "celular",
        "telefone",
        "numero",
        "nome",
        "cara",
        "pessoal",
        "gente",
        "galera",
        "amigo",
        "amiga",
        "chefe",
        "trabalho",
        "casa",
        "carro",
        "dinheiro",
        "banco",
        "conta",
        "senha",
    }
)
"""Substantivos que o dono diz de verdade depois de «abre o», «no», «minha»: nunca viram nome."""

_PALAVRA: Final = re.compile(r"[\w']+", re.UNICODE)
_SIGLA: Final = re.compile(r"[A-Z]{2,5}")
_PARTES_DA_GRAFIA: Final = re.compile(r"[A-Z]{2,}(?=[A-Z][a-z]|\b|$)|[A-Z]?[a-z0-9']+|[A-Z]+")
_LETRAS: Final[dict[str, str]] = {
    "a": "á",
    "b": "bê",
    "c": "cê",
    "d": "dê",
    "e": "é",
    "f": "éfe",
    "g": "gê",
    "h": "agá",
    "i": "í",
    "j": "jóta",
    "k": "cá",
    "l": "éle",
    "m": "éme",
    "n": "éne",
    "o": "ó",
    "p": "pê",
    "q": "quê",
    "r": "érre",
    "s": "ésse",
    "t": "tê",
    "u": "ú",
    "v": "vê",
    "w": "dáblio",
    "x": "xis",
    "y": "ípsilon",
    "z": "zê",
}
_INGLES: Final[tuple[tuple[str, str], ...]] = (
    ("wh", "u"),
    ("ee", "i"),
    ("ea", "i"),
    ("oo", "u"),
    ("ou", "au"),
    ("th", "t"),
    ("ck", "k"),
    ("'", ""),
)
_FINAL_QUE_PEDE_I: Final = frozenset("bcdfgkptv")


def dobrar(texto: str) -> str:
    """Sem acento, sem caixa."""
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn").casefold()


def _soletrar(sigla: str) -> str:
    return " ".join(_LETRAS.get(letra, letra) for letra in sigla.lower())


def _pronuncia_da_grafia(escrita: str) -> str:
    """A grafia como o brasileiro lê: a sigla soletrada («GPMad» → «gê pê mad»). Só nome em ASCII
    tem sigla e caixa de camelo; «mãe» e «Kauã» passam como estão."""
    if not escrita.isascii():
        return escrita
    partes = []
    for parte in _PARTES_DA_GRAFIA.findall(escrita):
        partes.append(_soletrar(parte) if _SIGLA.fullmatch(parte) else parte)
    return " ".join(partes) if partes else escrita


def _som_da_palavra(palavra: str) -> str:
    bruto = dobrar(palavra)
    if bruto.startswith("w"):
        bruto = "u" + bruto[1:]
    for de, para in _INGLES:
        bruto = bruto.replace(de, para)
    bruto = bruto.replace("w", "u")
    if bruto and bruto[-1] in _FINAL_QUE_PEDE_I:
        bruto += "i"  # «pad» soa «padi», «app» soa «api»
    return fonetica_simples(bruto)


def som(texto: str) -> str:
    """O texto reduzido ao som: classes de som do pt-BR, sem espaço entre as palavras."""
    sons = [
        _som_da_palavra(parte)
        for palavra in _PALAVRA.findall(texto)
        for parte in _PALAVRA.findall(_pronuncia_da_grafia(palavra))
    ]
    # Átona no pt-BR: «e» e «i», «o» e «u» se confundem («gepetê» e «gê pê tê»).
    simbolos = "".join(sons).replace("e", "i").replace("o", "u")
    return re.sub(r"(.)\1+", r"\1", simbolos)


def sons_do_candidato(candidato: Candidato) -> tuple[str, ...]:
    falas = [f for f in candidato.fala.split("|") if f.strip()]
    return tuple(dict.fromkeys(som(f) for f in falas or [_pronuncia_da_grafia(candidato.escrita)]))


@dataclass(frozen=True, slots=True)
class Troca:
    ouvido: str
    escrita: str
    tipo: str
    parecenca: float
    certa: bool
    """`False` = palpite: o cérebro diz o que entendeu."""


@dataclass(frozen=True, slots=True)
class Duvida:
    ouvido: str
    candidatos: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Reconciliacao:
    bruto: str
    texto: str
    trocas: tuple[Troca, ...] = ()
    duvidas: tuple[Duvida, ...] = ()

    @property
    def mudou(self) -> bool:
        return self.texto != self.bruto

    @property
    def agiu(self) -> bool:
        return bool(self.trocas or self.duvidas)

    def nota(self) -> str:
        """A nota do turno para o cérebro: a regra geral e o que este turno teve de som trocado."""
        linhas = [NOTA_DA_VOZ]
        for troca in self.trocas:
            if troca.certa:
                linhas.append(f"Ouvi «{troca.ouvido}» e corrigi para «{troca.escrita}» pelo som.")
            else:
                linhas.append(
                    f"Ouvi «{troca.ouvido}» e entendi «{troca.escrita}» pelo som e pelo contexto: "
                    "diga em poucas palavras o que entendeu ao responder."
                )
        for duvida in self.duvidas:
            opcoes = " ou ".join(f"«{c}»" for c in duvida.candidatos)
            linhas.append(f"«{duvida.ouvido}» pode ser {opcoes} (som parecido).")
        return " ".join(linhas)


@dataclass(slots=True)
class Reconciliador:
    """Os candidatos do contexto do dono, com o som de cada um já calculado."""

    candidatos: Sequence[Candidato] = LEXICO_BASE
    _indice: list[tuple[Candidato, tuple[str, ...], str]] = field(default_factory=list, repr=False)
    _originais: list[str] = field(default_factory=list, repr=False)
    """As palavras do texto em reconciliação como vieram (a caixa diz o que é sigla)."""

    def __post_init__(self) -> None:
        vistos: set[tuple[str, str]] = set()
        for candidato in list(self.candidatos)[:LIMITE_DE_CANDIDATOS]:
            chave = (dobrar(candidato.escrita), candidato.tipo)
            if not chave[0] or chave in vistos:
                continue
            vistos.add(chave)
            self._indice.append((candidato, sons_do_candidato(candidato), chave[0]))

    @classmethod
    def do_contexto(
        cls,
        *,
        termos: Iterable[Candidato] = (),
        apps: Iterable[str] = (),
        pessoas: Iterable[str] = (),
    ) -> Reconciliador:
        """O léxico base mais o que é do dono: o vocabulário primeiro (é o que ele escolheu)."""
        return cls(
            [
                *termos,
                *(Candidato(nome, "pessoa") for nome in pessoas),
                *(Candidato(nome, "app") for nome in apps),
                *LEXICO_BASE,
            ]
        )

    def conhecido(self, texto: str) -> bool:
        alvo = dobrar(texto)
        return any(chave == alvo for _, _, chave in self._indice)

    def _melhores(self, ouvido: str, tipos: frozenset[str] | None) -> list[tuple[float, Candidato]]:
        alvo = som(ouvido)
        if len(alvo) < 2:
            return []
        notas: dict[str, tuple[float, Candidato]] = {}
        for candidato, sons, chave in self._indice:
            if tipos is not None and candidato.tipo not in tipos:
                continue
            nota = max(similaridade(alvo, som_dele) for som_dele in sons)
            if chave not in notas or nota > notas[chave][0]:
                notas[chave] = (nota, candidato)
        return sorted(notas.values(), key=lambda par: -par[0])

    def reconciliar(self, texto: str) -> Reconciliacao:
        """O texto com os trechos de som trocado corrigidos, e o que foi feito (para a nota)."""
        if not texto.strip() or not self._indice:
            return Reconciliacao(texto, texto)
        tokens = list(_PALAVRA.finditer(texto))[:LIMITE_DE_PALAVRAS]
        palavras = [dobrar(t.group()) for t in tokens]
        self._originais = [t.group() for t in tokens]
        trocas: list[Troca] = []
        duvidas: list[Duvida] = []
        substituicoes: list[tuple[int, int, str]] = []
        i = 0
        while i < len(tokens):
            achado = self._na_vaga(palavras, i) or self._fora_de_vaga(palavras, i)
            if achado is None:
                i += 1
                continue
            tamanho, resultado = achado
            ouvido = texto[tokens[i].start() : tokens[i + tamanho - 1].end()]
            if isinstance(resultado, Troca):
                resultado = Troca(ouvido, *_resto(resultado))
                trocas.append(resultado)
                substituicoes.append(
                    (tokens[i].start(), tokens[i + tamanho - 1].end(), resultado.escrita)
                )
            else:
                duvidas.append(Duvida(ouvido, resultado.candidatos))
            i += tamanho
        corrigido = texto
        for inicio, fim, escrita in reversed(substituicoes):
            if texto[inicio : inicio + 1].isupper() and escrita[:1].islower():
                escrita = escrita[:1].upper() + escrita[1:]  # «Ma i.» → «Mãe.»
            corrigido = corrigido[:inicio] + escrita + corrigido[fim:]
        return Reconciliacao(texto, corrigido, tuple(trocas), tuple(duvidas))

    def _na_vaga(self, palavras: list[str], i: int) -> tuple[int, Troca | Duvida] | None:
        vaga = _vaga_antes(palavras, i)
        if vaga is None or palavras[i] in PARADAS:
            return None
        trecho: list[str] = []
        for palavra in palavras[i : i + 3]:
            if palavra in PARADAS:
                break
            trecho.append(palavra)
        melhor: tuple[float, int, list[tuple[float, Candidato]]] | None = None
        if any(self.conhecido(" ".join(trecho[:n])) for n in range(1, len(trecho) + 1)):
            return None  # o nome já está certo: nada a fazer
        for tamanho in range(len(trecho), 0, -1):
            ouvido = " ".join(trecho[:tamanho])
            if tamanho == 1 and ouvido in COMUNS:
                continue  # «abre o navegador»: substantivo comum sozinho não vira nome
            notas = self._melhores(" ".join(self._originais[i : i + tamanho]), vaga.tipos)
            if notas and (melhor is None or notas[0][0] > melhor[0]):
                melhor = (notas[0][0], tamanho, notas)
        if melhor is None:
            return None
        nota, tamanho, notas = melhor
        segunda = notas[1][0] if len(notas) > 1 else 0.0
        candidato = notas[0][1]
        destacado = nota - segunda >= MARGEM
        if nota >= TROCA_CERTA and destacado:
            return tamanho, Troca("", candidato.escrita, candidato.tipo, round(nota, 3), True)
        if vaga.palpite is not None and nota >= vaga.palpite and destacado:
            return tamanho, Troca("", candidato.escrita, candidato.tipo, round(nota, 3), False)
        if nota >= DUVIDA:
            return tamanho, Duvida("", tuple(c.escrita for n, c in notas[:2] if n >= DUVIDA))
        return None

    def _fora_de_vaga(self, palavras: list[str], i: int) -> tuple[int, Troca | Duvida] | None:
        """O nome que o ASR partiu em duas ou três palavras, com som quase igual."""
        for tamanho in (3, 2):
            trecho = palavras[i : i + tamanho]
            if len(trecho) < tamanho or any(p in PARADAS or p in COMUNS for p in trecho):
                continue
            ouvido = " ".join(trecho)
            if self.conhecido(ouvido) or any(self.conhecido(p) for p in trecho):
                continue
            notas = self._melhores(" ".join(self._originais[i : i + tamanho]), None)
            if not notas:
                continue
            nota, candidato = notas[0]
            segunda = notas[1][0] if len(notas) > 1 else 0.0
            if nota >= TROCA_CERTA and nota - segunda >= MARGEM:
                return tamanho, Troca("", candidato.escrita, candidato.tipo, round(nota, 3), True)
        return None


def _resto(troca: Troca) -> tuple[str, str, float, bool]:
    return troca.escrita, troca.tipo, troca.parecenca, troca.certa


def _vaga_antes(palavras: list[str], i: int) -> Vaga | None:
    for vaga in sorted(VAGAS, key=lambda v: -len(v.antes)):
        n = len(vaga.antes)
        if i >= n and tuple(palavras[i - n : i]) == vaga.antes:
            return vaga
    return None


__all__ = [
    "DUVIDA",
    "LEXICO_BASE",
    "NOTA_DA_VOZ",
    "TROCA_CERTA",
    "TROCA_PALPITE",
    "Candidato",
    "Duvida",
    "Reconciliacao",
    "Reconciliador",
    "Troca",
    "Vaga",
    "som",
    "sons_do_candidato",
]
