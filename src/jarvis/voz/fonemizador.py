"""Fonemizador pt-BR com licença permissiva: `epitran` (MIT) + tônica por regra (ADR-0016/0017).

É a peça que a ADR-0016 chamou de **opção B**: trocar o `espeak-ng` (GPL-3.0, que não pode
entrar no produto) pelo `epitran` (MIT, que pode), mantendo a voz `pt_BR-*` do piper e o número
já medido do F1-09. A amostra da ADR-0017 mostrou que a troca custava duas coisas, e as duas
estão resolvidas aqui, em cima da regra e não do modelo:

1. **tônica** — o `epitran` não marca acento em `por-Latn` (zero contra 14 do espeak na mesma
   frase). `jarvis.voz.tonica` repõe pela ortografia, palavra por palavra;
2. **`ʷ`** — símbolo do `epitran` fora do `phoneme_id_map` da voz, e ele aparece no `qu`
   (`kʷinzɛ`). A substituição declarada é **apagar**, e isso não é conveniência: em pt-BR
   `quinze` é /ˈkĩzi/, sem /w/ — manter o `ʷ` como `w` daria "cuinze". Antes, esse símbolo
   caía no descarte silencioso do `MotorPiperOnnx`; agora é decisão com motivo e com teste.

**Pontuação atravessa.** O mapa da voz tem `,`, `.`, `?`, `!`, `;`, `:` e espaço, e são eles
que viram pausa. Fonemizar só as palavras e jogar a pontuação fora deixaria a frase sem
respiração — então o texto é partido em palavra / não-palavra, e só a palavra passa pelo G2P.

**O que fica não verificado aqui:** se a prosódia resultante soa bem. Isso é ouvido do dono
(F1-16). O que este módulo garante é cobertura de inventário (`conferir_cobertura`): nenhum
símbolo sai daqui sem estar no mapa da voz, e o que sair aparece no relatório em vez de virar
voz torta.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from jarvis.voz.tonica import acentuar

IDIOMA_EPITRAN: Final = "por-Latn"
LICENCA: Final = "MIT"

SUBSTITUICOES: Final[Mapping[str, str]] = {
    # `ʷ` não existe no inventário da voz, e em pt-BR o `u` do `qu` não soa: `quinze` é
    # /ˈkĩzi/. Apagar é a leitura certa; mapear para `w` daria "cuinze".
    "ʷ": "",
}

PALAVRA: Final[re.Pattern[str]] = re.compile(r"[^\W\d_]+(?:['\-][^\W\d_]+)*", re.UNICODE)
"""Palavra = letras, com hífen e apóstrofo internos (`guarda-chuva`, `d'água`). Número fica
de fora de propósito: ler `15` como "quinze" é normalização de texto, não fonemização, e
inventar isso aqui esconderia a decisão (ver "o que falta" nas notas)."""


class FonemizadorIndisponivel(RuntimeError):
    """O extra não está instalado. A mensagem diz o comando, não "falhou"."""


@dataclass(slots=True)
class FonemizadorEpitran:
    """Texto pt-BR → IPA do inventário da voz, com tônica. Chamável como função.

    É injetado no `MotorPiperOnnx` (F1-09) exatamente como o fonemizador do espeak era: a
    fronteira de licença continua visível na assinatura, só que agora o que atravessa é MIT.
    """

    idioma: str = IDIOMA_EPITRAN
    com_tonica: bool = True
    substituicoes: Mapping[str, str] = field(default_factory=lambda: dict(SUBSTITUICOES))
    nome: str = "epitran+tonica-pt-br"
    licenca: str = LICENCA
    palavras_fonemizadas: int = 0
    _epitran: Any = field(default=None, repr=False)

    def abrir(self) -> None:
        try:
            import epitran
        except ImportError as erro:  # pragma: no cover — ambiente sem o grupo `voz`
            raise FonemizadorIndisponivel(
                "epitran não está instalado: é o fonemizador pt-BR do caminho local "
                "(grupo opcional `voz`). Rode `uv sync --group voz`."
            ) from erro
        self._epitran = epitran.Epitran(self.idioma)

    @property
    def aberto(self) -> bool:
        return self._epitran is not None

    def ipa_da_palavra(self, palavra: str) -> str:
        if self._epitran is None:
            self.abrir()
        assert self._epitran is not None
        # NFD: a voz do piper conhece `i` e o til **combinante** (U+0303) separados, não a
        # vogal nasal pré-composta `ĩ` (U+0129) que o `epitran` às vezes devolve. Sem esta
        # normalização, `jardim` perde a nasalidade em silêncio — e foi `conferir_cobertura`
        # que achou, com um símbolo fora do inventário em três frases.
        bruto = unicodedata.normalize("NFD", str(self._epitran.transliterate(palavra)))
        for de, para in self.substituicoes.items():
            bruto = bruto.replace(de, para)
        self.palavras_fonemizadas += 1
        return acentuar(palavra, bruto) if self.com_tonica else bruto

    def __call__(self, texto: str) -> str:
        """O IPA da frase inteira, com a pontuação no lugar (é ela que vira pausa)."""
        partes: list[str] = []
        posicao = 0
        for achado in PALAVRA.finditer(texto):
            partes.append(texto[posicao : achado.start()])
            partes.append(self.ipa_da_palavra(achado.group()))
            posicao = achado.end()
        partes.append(texto[posicao:])
        return "".join(partes)


@dataclass(frozen=True, slots=True)
class Cobertura:
    """O que o fonemizador produziu e a voz não sabe pronunciar."""

    simbolos: tuple[str, ...]
    fora_do_mapa: tuple[str, ...]
    ocorrencias: int

    @property
    def completa(self) -> bool:
        return not self.fora_do_mapa

    def __str__(self) -> str:
        if self.completa:
            return f"{len(self.simbolos)} símbolos, todos no inventário da voz"
        quais = " ".join(self.fora_do_mapa)
        return (
            f"{len(self.simbolos)} símbolos, {len(self.fora_do_mapa)} fora do inventário "
            f"({quais}) em {self.ocorrencias} ocorrência(s)"
        )


def conferir_cobertura(
    fonemizar: Any,
    mapa: Iterable[str],
    textos: Sequence[str],
) -> Cobertura:
    """Confere o IPA de `textos` contra o inventário da voz, **antes** de sintetizar.

    Existe porque o `MotorPiperOnnx` descarta em silêncio o que não conhece (achado da
    ADR-0017): sem esta conferência, um fonema novo vira voz torta e ninguém fica sabendo.
    Mudar o descarte para erro é emenda da ADR-0016 e decisão do dono; medir a divergência
    não é — e é o que esta função faz.
    """
    conhecidos = set(mapa)
    vistos: dict[str, int] = {}
    for texto in textos:
        for simbolo in str(fonemizar(texto)):
            vistos[simbolo] = vistos.get(simbolo, 0) + 1
    fora = {s: n for s, n in vistos.items() if s not in conhecidos}
    return Cobertura(
        simbolos=tuple(sorted(vistos)),
        fora_do_mapa=tuple(sorted(fora)),
        ocorrencias=sum(fora.values()),
    )
