"""O objetivo do turno: o que o dono pediu, e até onde a navegação vai sem perguntar (2026-10-20).

O dono testou o app e ouviu "posso?" a cada passo de uma tarefa que ele mesmo tinha pedido
("abra o canal do Thiago Nigro"): depois de ler uma página o turno ficava *contaminado*, e abrir
link, digitar na busca e navegar passavam a pedir o sim. O pedido dele: só o muito crítico
pergunta; o que cabe no objetivo, não.

O objetivo nasce do **pedido do dono** — nunca do que o modelo ou uma página dizem — e guarda:

- os sites que o dono **citou**, pelo nome ("youtube") ou pelo domínio ("youtube.com");
- os domínios **alcançados** no caminho: páginas que o objetivo abriu, links delas, resultados de
  busca, abas abertas. A página que o objetivo mandou abrir pode levar a um domínio novo (o
  resultado da busca, o canal) sem pergunta.

O que continua perguntando, com objetivo ou sem: URL ou texto que leva **dado do dono ou segredo**
(chave, token, senha, e-mail, CPF, telefone, cartão) para domínio que ele não citou; e domínio
que não foi citado nem alcançado, num turno que leu conteúdo de terceiros — o caso do texto
injetado que diz "abra mal.example". Banco, pagamento, senha, enviar, apagar e instalar seguem
nas regras de sempre (risco dinâmico e tier perigoso), que este módulo não toca.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import unquote_plus, urlsplit

from jarvis.memoryd.importacao import redigir
from jarvis.politica.abertura import dominio_registravel

CARACTERES_DO_PEDIDO: Final = 300
SEGREDOS_QUE_NAO_CONTAM_EM_URL: Final = frozenset({"hex_longo", "conteudo_de_env"})
"""Em URL, hexadecimal longo é quase sempre identificador de página (cache, assinatura de CDN) e
não segredo do dono: contaria como dado do dono e perguntaria à toa."""
_EMAIL: Final = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_CPF: Final = re.compile(r"(?<!\d)(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})(?!\d)")
_TELEFONE: Final = re.compile(
    r"(?:\+55\s?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4})|(?:\(\d{2}\)\s?9?\d{4}-?\d{4})"
)
_DIGITOS: Final = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def _cpf_valido(digitos: str) -> bool:
    if len(set(digitos)) == 1:
        return False
    for tamanho in (9, 10):
        soma = sum(int(d) * (tamanho + 1 - i) for i, d in enumerate(digitos[:tamanho]))
        if (soma * 10 % 11) % 10 != int(digitos[tamanho]):
            return False
    return True


def _luhn(digitos: str) -> bool:
    soma = 0
    for posicao, digito in enumerate(reversed(digitos)):
        n = int(digito)
        if posicao % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        soma += n
    return soma % 10 == 0


def dados_do_dono(texto: str, *, em_url: bool = False) -> list[str]:
    """Os tipos de dado pessoal ou segredo que o texto leva (vazio = nenhum). Em URL, o texto é
    decodificado antes (`%40` é `@`)."""
    claro = unquote_plus(texto) if em_url else texto
    achados = set(redigir(claro).achados)
    if em_url:
        achados -= SEGREDOS_QUE_NAO_CONTAM_EM_URL
    if _EMAIL.search(claro):
        achados.add("email")
    if any(_cpf_valido("".join(m.groups())) for m in _CPF.finditer(claro)):
        achados.add("cpf")
    if _TELEFONE.search(claro):
        achados.add("telefone")
    for corrida in _DIGITOS.finditer(claro):
        digitos = re.sub(r"[ -]", "", corrida.group())
        if 13 <= len(digitos) <= 19 and _luhn(digitos):
            achados.add("cartao")
    return sorted(achados)


def termos(texto: str) -> list[str]:
    """Palavras sem acento nem caixa; o ponto fica só por dentro (`youtube.com`)."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    ).casefold()
    return [t.strip(".") for t in re.sub(r"[^\w\s.]", " ", sem_acento).split() if t.strip(".")]


def _host(url_ou_host: str) -> str:
    partes = urlsplit(url_ou_host.strip())
    if partes.scheme and partes.hostname:
        return partes.hostname
    return url_ou_host.strip().lower()


@dataclass(slots=True)
class Objetivo:
    """O objetivo de um turno. Quem o cria é o código, com a fala do dono; quem o amplia é o
    código, com os endereços que as ferramentas do objetivo devolveram."""

    pedido: str
    """A fala do dono, redigida e curta: é o texto do objetivo."""
    _termos: frozenset[str] = frozenset()
    alcancados: set[str] = field(default_factory=set)
    """Domínios registráveis (`youtube.com`) que o caminho do objetivo alcançou."""

    @classmethod
    def do_pedido(cls, fala: str) -> Objetivo:
        limpo = " ".join(redigir(fala).texto.split())
        curto = limpo if len(limpo) <= CARACTERES_DO_PEDIDO else limpo[:CARACTERES_DO_PEDIDO] + "…"
        return cls(pedido=curto, _termos=frozenset(termos(fala)))

    def citado(self, url_ou_host: str) -> bool:
        """O dono disse o nome ou o domínio deste site (e o host é ele ou um subdomínio dele)."""
        registravel = dominio_registravel(_host(url_ou_host))
        if not registravel:
            return False
        return registravel in self._termos or registravel.split(".")[0] in self._termos

    def dentro(self, url_ou_host: str) -> bool:
        registravel = dominio_registravel(_host(url_ou_host))
        return bool(registravel) and (self.citado(registravel) or registravel in self.alcancados)

    def alcancar(self, enderecos: Iterable[str]) -> None:
        for endereco in enderecos:
            registravel = dominio_registravel(_host(str(endereco)))
            if registravel:
                self.alcancados.add(registravel)

    def leva_dado_do_dono(self, url: str) -> list[str]:
        """Os dados do dono que a URL leva para um domínio que ele **não citou** (vazio = nada)."""
        return [] if self.citado(url) else dados_do_dono(url, em_url=True)


def enderecos_do_resultado(dados: object) -> list[str]:
    """Os endereços que um resultado de ferramenta traz: `url` e `dominio` no topo, `href` e `url`
    de links, resultados, vídeos, abas e dos elementos do mapa da página. Só endereço — o texto do
    resultado não é lido."""
    achados: list[str] = []

    def visitar(valor: object, profundidade: int) -> None:
        if profundidade > 3:
            return
        if isinstance(valor, dict):
            for chave in ("url", "href", "dominio", "destinoDoLink"):
                endereco = valor.get(chave)
                if isinstance(endereco, str) and endereco:
                    achados.append(endereco)
            for chave in ("links", "resultados", "videos", "abas", "aba", "elementos"):
                if chave in valor:
                    visitar(valor[chave], profundidade + 1)
        elif isinstance(valor, list):
            for item in valor[:200]:
                visitar(item, profundidade + 1)

    visitar(dados, 0)
    return achados
