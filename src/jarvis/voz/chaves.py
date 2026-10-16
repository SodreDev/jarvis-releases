"""Chave de API: vem do ambiente, não aparece em lugar nenhum (ADR-0017).

Quatro proibições do dono, e como cada uma é **estrutural** em vez de disciplina:

1. **Nunca no repositório.** Não há arquivo de chave, nem campo de chave na configuração: o
   registro de motores guarda o *nome* da variável (`variavel_da_chave`), e `Chave.do_ambiente`
   é o único caminho de leitura. A configuração do dono (`jarvis.voz.config`) recusa qualquer
   chave que alguém escreva nela.
2. **Nunca em log, auditoria ou evento.** `Chave` **não tem** `__repr__` que mostre o valor —
   `repr()`, `str()`, `f"{chave}"`, `print(chave)` e um `dataclass` que contenha uma `Chave`
   imprimem o nome da variável e o comprimento, e mais nada. É por isso que a chave é um tipo e
   não um `str`: um `str` em `payload` de evento vaza na primeira vez que alguém formatar o
   envelope, e o log do barramento é encadeado por hash — vazamento ali não se apaga.
3. **Nunca em argumento de linha de comando.** `argv` é visível para qualquer processo do
   usuário (`/proc/<pid>/cmdline`) e entra no histórico do shell. Não existe opção de CLI que
   aceite chave; e `proibir_segredo_em_argv` **recusa a subir** se o valor de uma das variáveis
   aparecer em `argv`, inclusive por acidente do dono.
4. **Nunca lida por quem não precisa.** `usar()` é o único acesso ao valor, tem nome fácil de
   procurar (`grep -rn "\\.usar()"`) e é chamado em um lugar por adaptador: na montagem do
   cabeçalho HTTP.

E uma rede de segurança para o resto: `redigir` apaga o valor de qualquer texto antes de ele
virar mensagem de erro, frase de degradação ou linha de diagnóstico. O teste que prova isso
roda o caminho inteiro com uma chave conhecida e varre **tudo** o que o processo escreveu.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from jarvis.ambiente import ambiente_ou_os

VARIAVEL_GROQ: Final = "JARVIS_GROQ_API_KEY"
VARIAVEL_ELEVENLABS: Final = "JARVIS_ELEVENLABS_API_KEY"
VARIAVEIS: Final[tuple[str, ...]] = (VARIAVEL_GROQ, VARIAVEL_ELEVENLABS)
"""As variáveis que o produto conhece. O registro de motores aponta para elas pelo nome."""

MARCA: Final = "«chave de {variavel}, não mostrada»"
"""O que entra no lugar do segredo quando um texto é redigido."""

COMPRIMENTO_MINIMO: Final = 8
"""Abaixo disso não é chave: é alguém colando um pedaço. Recusar cedo evita uma chamada que
voltaria 401 com o segredo pela metade em algum log de terceiro."""


class SegredoAusente(RuntimeError):
    """A variável não está no ambiente (ou está vazia). A mensagem diz **o nome**, nunca valor."""


class SegredoNaLinhaDeComando(RuntimeError):
    """O valor de uma chave apareceu em `argv`. O processo não sobe (proibição 3)."""


class SegredoNaConfiguracao(RuntimeError):
    """Alguém escreveu uma chave no arquivo de configuração. Recusado na leitura."""


@dataclass(frozen=True, slots=True, repr=False)
class Chave:
    """Um segredo que sabe não se mostrar.

    `valor` é um campo normal — esconder não é esconder do programador, é esconder de
    `repr`, de `str`, de `print`, de formatação e de serialização por acidente. Quem quer o
    valor chama `usar()`, e isso aparece no `grep`.
    """

    variavel: str
    valor: str

    def __post_init__(self) -> None:
        if not self.valor.strip():
            raise SegredoAusente(f"{self.variavel} está vazia")
        if len(self.valor.strip()) < COMPRIMENTO_MINIMO:
            raise SegredoAusente(
                f"{self.variavel} tem menos de {COMPRIMENTO_MINIMO} caracteres: isso não é uma "
                "chave inteira (e o valor não vai aparecer aqui)"
            )

    @classmethod
    def do_ambiente(cls, variavel: str, *, ambiente: Mapping[str, str] | None = None) -> Chave:
        """A chave, ou `SegredoAusente` dizendo ao dono o que exportar."""
        bruto = ambiente_ou_os(ambiente).get(variavel, "")
        if not bruto.strip():
            raise SegredoAusente(
                f"{variavel} não está no ambiente. Exporte a chave no seu shell "
                f"(`export {variavel}=...`) — ela não entra no repositório, na configuração "
                "nem na linha de comando"
            )
        return cls(variavel=variavel, valor=bruto.strip())

    @classmethod
    def presente(cls, variavel: str, *, ambiente: Mapping[str, str] | None = None) -> bool:
        """ "Dá para usar este motor?" — sem ler o valor para dentro de nada."""
        return bool(ambiente_ou_os(ambiente).get(variavel, "").strip())

    def usar(self) -> str:
        """O valor. Único acesso, e de propósito fácil de procurar no código."""
        return self.valor

    @property
    def caracteres(self) -> int:
        return len(self.valor)

    def __repr__(self) -> str:
        return f"<Chave {self.variavel}: {self.caracteres} caracteres, não mostrada>"

    def __str__(self) -> str:
        return self.__repr__()

    def __format__(self, especificacao: str) -> str:
        """Formatar também é imprimir: `f"{chave:>40}"` não pode virar uma brecha."""
        return format(self.__repr__(), especificacao)


def redigir(texto: str, chaves: Iterable[Chave] = ()) -> str:
    """Apaga o valor das chaves dadas de um texto qualquer.

    É a rede de segurança, não a defesa: a defesa é a chave nunca entrar no texto. Serve para
    o que vem de **fora** — corpo de erro de um serviço, mensagem de exceção de biblioteca —
    onde não há como garantir o que o terceiro resolveu repetir de volta.
    """
    limpo = texto
    for chave in chaves:
        if chave.valor and chave.valor in limpo:
            limpo = limpo.replace(chave.valor, MARCA.format(variavel=chave.variavel))
    return limpo


def redigir_do_ambiente(
    texto: str,
    *,
    variaveis: Sequence[str] = VARIAVEIS,
    ambiente: Mapping[str, str] | None = None,
) -> str:
    """O mesmo, para quem não tem a `Chave` na mão (diagnóstico, mensagem de erro de CLI)."""
    fonte = ambiente_ou_os(ambiente)
    limpo = texto
    for variavel in variaveis:
        valor = fonte.get(variavel, "").strip()
        if valor and valor in limpo:
            limpo = limpo.replace(valor, MARCA.format(variavel=variavel))
    return limpo


PARECE_CHAVE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[\s=:])(?:gsk_|sk_|xi-)[A-Za-z0-9_\-]{12,}"
)
"""Prefixos públicos de chave dos dois serviços (`gsk_` na Groq, `sk_` no ElevenLabs).

Serve para recusar o acidente do dono colando a chave onde ela não deve ir, mesmo quando a
variável **não** está exportada — aí não há valor para comparar, e o formato é o que resta.
Não é detector de segredo: é uma recusa a mais, barata, no caminho em que o erro é comum.
"""


def proibir_segredo_em_argv(
    argv: Sequence[str],
    *,
    variaveis: Sequence[str] = VARIAVEIS,
    ambiente: Mapping[str, str] | None = None,
) -> None:
    """Recusa subir se uma chave estiver em `argv` (proibição 3).

    Duas provas, porque uma não cobre a outra: o **valor** exportado aparecendo em `argv`
    (o caso certo) e o **formato** de chave dos dois serviços (o caso em que a variável não
    está exportada e não há com o que comparar). A mensagem nunca repete o argumento.
    """
    fonte = ambiente_ou_os(ambiente)
    for indice, argumento in enumerate(argv):
        for variavel in variaveis:
            valor = fonte.get(variavel, "").strip()
            if valor and valor in argumento:
                raise SegredoNaLinhaDeComando(
                    f"o valor de {variavel} apareceu no argumento {indice} da linha de comando. "
                    "`argv` é visível para outros processos e entra no histórico do shell: "
                    "exporte a variável e rode sem passar a chave"
                )
        if PARECE_CHAVE.search(argumento):
            raise SegredoNaLinhaDeComando(
                f"o argumento {indice} tem a forma de uma chave de API. Nenhuma opção deste "
                "programa aceita chave: exporte a variável de ambiente"
            )


def proibir_segredo_na_configuracao(dados: Mapping[str, object], *, arquivo: str = "") -> None:
    """Recusa configuração que tenha chave (proibição 1), em qualquer nível do TOML."""
    onde = f" em {arquivo}" if arquivo else ""
    for chave_do_mapa, valor in dados.items():
        nome = str(chave_do_mapa).lower()
        if isinstance(valor, Mapping):
            proibir_segredo_na_configuracao(valor, arquivo=arquivo)
            continue
        suspeito = any(
            marca in nome for marca in ("api_key", "api-key", "apikey", "chave", "token", "secret")
        )
        if suspeito and str(valor).strip():
            raise SegredoNaConfiguracao(
                f"o campo {chave_do_mapa!r}{onde} parece guardar um segredo. Chave de API vem "
                "só de variável de ambiente; o registro de motores diz qual é o nome dela"
            )
        if isinstance(valor, str) and PARECE_CHAVE.search(valor):
            raise SegredoNaConfiguracao(
                f"o campo {chave_do_mapa!r}{onde} tem um valor com a forma de chave de API. "
                "Apague-o do arquivo e exporte a variável de ambiente"
            )
