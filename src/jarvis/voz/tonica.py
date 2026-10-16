"""Tônica do pt-BR por regra de ortografia — a lacuna que a amostra da ADR-0017 mediu.

**O problema, medido.** A amostra da ADR-0017 comparou o IPA do `epitran` (MIT, que pode
entrar no produto) com o do `espeak-ng` (GPL-3.0, que não pode) na mesma frase: o `epitran` é
mais fiel aos fonemas do pt-BR (`ʒɐɾvis`, `tɛɾsɐ`) e marcou **zero** acentos de tonicidade,
contra **14** do espeak. A voz `pt_BR-faber-medium` foi treinada com o inventário do espeak,
**tônica incluída** — então trocar de fonemizador sem repor a tônica entrega prosódia achatada,
e isso é perda de qualidade, não economia de licença.

**A saída não é modelo, é ortografia.** O português escreve onde a tônica cai: ou o acento
gráfico diz, ou a terminação diz. São duas regras e uma lista pequena de palavras átonas:

1. **acento gráfico manda** — `á é í ó ú â ê ô` apontam a sílaba tônica; `ã õ` apontam quando
   não há outro acento na palavra (em `órgão`, quem manda é o `ó`);
2. **sem acento, a terminação manda** — terminada em `i`, `u`, `l`, `r`, `z`, `x`, `n`, `im`,
   `um`, `om`, `ã`, `ão` ou ditongo decrescente (`ei`, `ai`, `au`, `eu`, `ou`…) é **oxítona**;
   o resto (`a`, `e`, `o`, `am`, `em`, `ens` e os plurais) é **paroxítona**;
3. **palavra átona não recebe marca** — artigo, preposição monossilábica, conjunção, pronome
   oblíquo e contração. O espeak também não marca essas, e marcar todas deixaria a frase com
   catorze ênfases, que é o oposto de prosódia.

**O que isto não é:** não é mapa de frase para ação (P2) nem léxico de pronúncia por palavra. É
regra de escrita aplicada a qualquer palavra, inclusive a que ninguém viu antes; a lista de
átonas tem 40 itens fechados da gramática, não vocabulário.

**O índice é contado do fim**, e é isso que faz a regra sobreviver à diferença entre o número
de núcleos da escrita e o do IPA: `reunião` tem dois grupos vocálicos escritos (`eu`, `ião`) e
três no IPA (`ew`, `i`, `ɐ̃w̃`), e a tônica é o **primeiro do fim** nos dois.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

TIL: Final = "̃"
"""Til combinante. O `epitran` nasaliza com ele (`ɐ̃`, `w̃`), então ele pertence ao núcleo."""

ACENTO_PRIMARIO: Final = "ˈ"
"""U+02C8, o mesmo símbolo que o `phoneme_id_map` das vozes do piper conhece."""

VOGAIS_ESCRITAS: Final = "aeiouáéíóúâêôãõàäëïöüy"
ACENTOS_QUE_MANDAM: Final = "áéíóúâêô"
TIS_QUE_MANDAM: Final = "ãõ"

VOGAIS_IPA: Final = "aeiouɐɛɪɔʊəɨɯøyæɒ"
GLIDES_IPA: Final = "wj"
"""Glide entra no núcleo: `ew` e `ɐ̃w̃` são uma sílaba, não duas."""

TERMINACOES_OXITONAS: Final[tuple[str, ...]] = (
    "i",
    "u",
    "l",
    "r",
    "z",
    "x",
    "n",
    "im",
    "um",
    "om",
    "ã",
    "ão",
)
TERMINACOES_PAROXITONAS_EM_M: Final[tuple[str, ...]] = ("am", "em")
"""`homem` e `falam` são paroxítonas; `jardim` e `album` são oxítonas. A diferença é a vogal,
e é por isso que `-m` não cabe numa lista só."""

DITONGOS_FINAIS: Final[tuple[str, ...]] = (
    "ai",
    "ei",
    "oi",
    "ui",
    "au",
    "eu",
    "ou",
    "iu",
)
"""Ditongo decrescente no fim puxa a tônica para a última sílaba (`anotei`, `chapeu`)."""

ATONAS: Final[frozenset[str]] = frozenset(
    {
        # artigos e contrações
        "o",
        "a",
        "os",
        "as",
        "do",
        "da",
        "dos",
        "das",
        "no",
        "na",
        "nos",
        "nas",
        "ao",
        "aos",
        "à",
        "às",
        "pelo",
        "pela",
        "pelos",
        "pelas",
        "dum",
        "duma",
        # preposições e conjunções átonas
        "de",
        "em",
        "e",
        "ou",
        "que",
        "se",
        "por",
        "pra",
        "pro",
        # pronomes oblíquos
        "me",
        "te",
        "lhe",
        "lhes",
        "vos",
        "mo",
        "ma",
    }
)
"""Fechada e pequena: é gramática, não vocabulário. Uma palavra fora dela recebe tônica pela
regra, mesmo que ninguém a tenha visto antes."""

SO_LETRAS: Final[re.Pattern[str]] = re.compile(r"[^\w]+", re.UNICODE)

OCLUSIVAS_E_FRICATIVAS: Final = "pbtdkgfvʃʒsz"
LIQUIDAS: Final = "lɾrʎ"
"""Ataque de duas consoantes só existe em obstruinte + líquida (`tɾ` de `trinta`, `pl` de
`plano`). Fora disso a primeira consoante é **coda** da sílaba anterior: em `Jarvis` o `ɾ`
fecha `ʒaɾ` e só o `v` abre `vis` — e é aí que o acento entra (`ʒaɾˈvis`), como no espeak."""


def _sem_marcas(texto: str) -> str:
    """Minúsculas, sem pontuação. Mantém o acento: é ele que manda na regra 1."""
    return SO_LETRAS.sub("", texto.lower())


def nucleos_escritos(palavra: str) -> list[tuple[int, int]]:
    """Grupos vocálicos da **escrita**, como (início, fim). Adjacentes contam como um."""
    grupos: list[tuple[int, int]] = []
    inicio: int | None = None
    for indice, letra in enumerate(palavra):
        if letra in VOGAIS_ESCRITAS:
            if inicio is None:
                inicio = indice
        elif inicio is not None:
            grupos.append((inicio, indice))
            inicio = None
    if inicio is not None:
        grupos.append((inicio, len(palavra)))
    return grupos


def _base(simbolo: str) -> str:
    """O caractere sem a marca: `ĩ` → `i`, `ɐ̃` → `ɐ`.

    O `epitran` nasaliza de duas formas na mesma frase — vogal **pré-composta** (`ĩ`, `ẽ`, `ũ`)
    e vogal com til **combinante** (`ɐ̃`, `w̃`). Comparar o caractere cru deixaria metade das
    vogais nasais fora do núcleo, e o acento ia para o começo da palavra: foi o defeito que
    `jardim` (`ˈʒɐɾdĩ` em vez de `ʒɐɾˈdĩ`) e `porém` mostraram.
    """
    return unicodedata.normalize("NFD", simbolo)[0]


def _glide_de_ataque(ipa: str, indice: int) -> bool:
    """O glide abre a sílaba seguinte em vez de fechar a anterior?

    `w` entre duas vogais é ataque, não coda: em `ʒowɐ̃w̃` (`João`) ele abre `wão`, e tratá-lo
    como parte de `o` fundia as duas sílabas em uma — a tônica ia para `Jo`. O `w` final da
    mesma palavra, que não tem vogal depois, é coda e pertence ao núcleo.
    """
    for proximo in ipa[indice + 1 :]:
        if unicodedata.combining(proximo) != 0 or unicodedata.category(proximo) == "Lm":
            continue
        return _base(proximo) in VOGAIS_IPA
    return False


def nucleos_ipa(ipa: str) -> list[tuple[int, int]]:
    """Grupos vocálicos do **IPA**, com glide e til dentro do núcleo."""
    grupos: list[tuple[int, int]] = []
    inicio: int | None = None
    for indice, simbolo in enumerate(ipa):
        base = _base(simbolo)
        nuclear = base in VOGAIS_IPA or base in GLIDES_IPA or simbolo == TIL
        if base in GLIDES_IPA and _glide_de_ataque(ipa, indice):
            nuclear = False
        # Glide e til só continuam um núcleo; não começam um (um `j` depois de consoante é
        # ataque, não núcleo).
        if nuclear and (inicio is not None or base in VOGAIS_IPA):
            if inicio is None:
                inicio = indice
        elif inicio is not None:
            grupos.append((inicio, indice))
            inicio = None
    if inicio is not None:
        grupos.append((inicio, len(ipa)))
    return grupos


def silaba_tonica(palavra: str) -> int:
    """Qual núcleo, **contado do fim**, carrega a tônica. `0` = palavra átona.

    `1` é a última sílaba (oxítona), `2` a penúltima (paroxítona), `3` a antepenúltima.
    """
    limpa = _sem_marcas(palavra)
    if not limpa:
        return 0
    nucleos = nucleos_escritos(limpa)
    if not nucleos:
        return 0
    if limpa in ATONAS:
        return 0
    if len(nucleos) == 1:
        return 1

    # Regra 1: acento gráfico manda.
    for distancia, (inicio, fim) in enumerate(reversed(nucleos), start=1):
        if any(letra in ACENTOS_QUE_MANDAM for letra in limpa[inicio:fim]):
            return distancia
    if not any(letra in ACENTOS_QUE_MANDAM for letra in limpa):
        for distancia, (inicio, fim) in enumerate(reversed(nucleos), start=1):
            if any(letra in TIS_QUE_MANDAM for letra in limpa[inicio:fim]):
                return distancia

    # Regra 2: a terminação manda. O plural não muda a regra — mas o plural de `-m` é `-ns`,
    # e é aí que `jovens` (paroxítona, de `jovem`) se separa de `jardins` (oxítona, de
    # `jardim`): quem decide é a vogal antes do `n`, não o `s`.
    if limpa.endswith("ns") and len(limpa) > 3:
        return 2 if limpa[-3] in "ae" else 1
    nucleo = limpa[:-1] if limpa.endswith("s") and len(limpa) > 2 else limpa
    if nucleo.endswith(TERMINACOES_PAROXITONAS_EM_M):
        return 2
    if nucleo.endswith(DITONGOS_FINAIS) or nucleo.endswith(TERMINACOES_OXITONAS):
        return 1
    return 2


def _unidades(trecho: str) -> list[str]:
    """Consoantes do trecho, cada uma com os modificadores que vêm com ela.

    `kʷ` é **uma** consoante (`ʷ` é letra modificadora, U+02B7), e `ɐ̃` é uma vogal com til
    combinante. Contar caractere em vez de unidade poria o acento no meio de um fonema.
    """
    unidades: list[str] = []
    for simbolo in trecho:
        if unidades and (
            unicodedata.combining(simbolo) != 0 or unicodedata.category(simbolo) == "Lm"
        ):
            unidades[-1] += simbolo
            continue
        unidades.append(simbolo)
    return unidades


def marcar_tonica(ipa: str, distancia_do_fim: int) -> str:
    """Põe `ˈ` antes do ataque da sílaba tônica do IPA de **uma** palavra.

    O acento vai antes das consoantes que **abrem** a sílaba, não antes da vogal: é onde o
    espeak o põe (`tˈeɾəs`), e é o que a voz do piper foi treinada a ouvir. Quais consoantes
    abrem a sílaba é a regra de ataque do português — uma, ou duas em obstruinte + líquida.
    """
    if distancia_do_fim <= 0 or ACENTO_PRIMARIO in ipa:
        return ipa
    nucleos = nucleos_ipa(ipa)
    if not nucleos or distancia_do_fim > len(nucleos):
        return ipa
    inicio_do_nucleo = nucleos[len(nucleos) - distancia_do_fim][0]
    fim_do_nucleo_anterior = (
        nucleos[len(nucleos) - distancia_do_fim - 1][1] if distancia_do_fim < len(nucleos) else 0
    )
    unidades = _unidades(ipa[fim_do_nucleo_anterior:inicio_do_nucleo])
    quantas = 0
    if unidades:
        quantas = 1
        if (
            len(unidades) >= 2
            and unidades[-2][0] in OCLUSIVAS_E_FRICATIVAS
            and unidades[-1][0] in LIQUIDAS
        ):
            quantas = 2
    ataque = inicio_do_nucleo - sum(len(u) for u in unidades[len(unidades) - quantas :])
    return ipa[:ataque] + ACENTO_PRIMARIO + ipa[ataque:]


def acentuar(palavra: str, ipa: str) -> str:
    """O IPA de uma palavra com a tônica no lugar que a ortografia dela indica."""
    return marcar_tonica(ipa, silaba_tonica(palavra))
