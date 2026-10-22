"""Os sites que o dono chama pelo nome — a tabela que o roteador de método e o caminho rápido usam.

Pedido do dono (2026-10-21): tarefa de site **específico** («pesquisa vídeos do Primo Rico no
YouTube», «as notícias do g1», «abre o GitHub») vai pelo navegador dele desde o primeiro passo, e
a busca é a do **próprio site** — não uma busca geral numa aba escondida que abre e fecha. Por
isso cada site daqui diz a página inicial e, quando tem, o endereço da busca dele. A busca
**genérica** («busca na internet o que é…») é outra coisa: vai direto, sem navegador
(`jarvis.executor.web.buscar`).

Do código, nunca do modelo: a consulta entra no endereço codificada para URL e o destino é sempre o
domínio da tabela.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final
from urllib.parse import quote, quote_plus


@dataclass(frozen=True, slots=True)
class Site:
    nome: str
    """Como o dono fala, sem acento e em minúsculas («youtube», «mercado livre»)."""
    inicio: str
    """A página inicial."""
    busca: str = ""
    """O endereço da busca do próprio site, com `{q}` (a consulta, já codificada); vazio = o site
    não tem busca por endereço (ou ela pede login)."""
    apelidos: tuple[str, ...] = ()
    caminho: bool = False
    """A consulta vai no caminho (`/search/<consulta>`), não na query: espaço vira `%20`."""

    def endereco_da_busca(self, consulta: str) -> str:
        """A busca do próprio site por `consulta`, ou a página inicial se o site não tem busca."""
        termos = " ".join(consulta.split())
        if not self.busca or not termos:
            return self.inicio
        codificada = quote(termos, safe="") if self.caminho else quote_plus(termos)
        return self.busca.format(q=codificada)


SITES: Final[tuple[Site, ...]] = (
    Site(
        "youtube",
        "https://www.youtube.com/",
        "https://www.youtube.com/results?search_query={q}",
        ("you tube",),
    ),
    Site("google", "https://www.google.com/", "https://www.google.com/search?q={q}"),
    Site("gmail", "https://mail.google.com/"),
    Site(
        "wikipedia",
        "https://pt.wikipedia.org/",
        "https://pt.wikipedia.org/w/index.php?search={q}",
        ("wiki",),
    ),
    Site("g1", "https://g1.globo.com/", "https://g1.globo.com/busca/?q={q}"),
    Site("uol", "https://www.uol.com.br/"),
    Site(
        "mercado livre",
        "https://www.mercadolivre.com.br/",
        "https://lista.mercadolivre.com.br/{q}",
        ("mercadolivre",),
        caminho=True,
    ),
    Site("amazon", "https://www.amazon.com.br/", "https://www.amazon.com.br/s?k={q}"),
    Site("github", "https://github.com/", "https://github.com/search?q={q}"),
    Site("reddit", "https://www.reddit.com/", "https://www.reddit.com/search/?q={q}"),
    Site("twitter", "https://x.com/", "https://x.com/search?q={q}"),
    Site("facebook", "https://www.facebook.com/", "https://www.facebook.com/search/top?q={q}"),
    Site("netflix", "https://www.netflix.com/", "https://www.netflix.com/search?q={q}"),
    Site(
        "linkedin",
        "https://www.linkedin.com/",
        "https://www.linkedin.com/search/results/all/?keywords={q}",
    ),
    Site("twitch", "https://www.twitch.tv/", "https://www.twitch.tv/search?term={q}"),
    Site(
        "spotify web",
        "https://open.spotify.com/",
        "https://open.spotify.com/search/{q}",
        caminho=True,
    ),
    Site("instagram", "https://www.instagram.com/"),
    Site("whatsapp", "https://web.whatsapp.com/", apelidos=("whatsapp web", "zap")),
)
"""A tabela. Instagram e WhatsApp só abrem: ali a interação é por mouse e teclado (ADR-0027)."""

DOMINIO: Final = re.compile(
    r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|br|io|app|dev|gov|edu|tv|me|info)(?:\.br)?\b"
)
"""Um domínio dito ou digitado («exemplo.com.br»), já sem acento e em minúsculas."""


def dobrar(texto: str) -> str:
    """Sem acento, minúsculas, pontuação como espaço (o ponto de domínio fica), um espaço só."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    ).casefold()
    return " ".join(re.sub(r"[^\w.\s-]|(?<!\w)\.|\.(?!\w)", " ", sem_acento).split())


def tem_palavra(texto_dobrado: str, palavras: tuple[str, ...]) -> bool:
    """Alguma das palavras (ou frases) inteira no texto já dobrado: «aba» não casa em «acaba»."""
    return any(
        re.search(rf"(?<![\w.]){re.escape(dobrar(p))}(?![\w])", texto_dobrado) for p in palavras
    )


def site_citado(fala: str) -> Site | None:
    """O site da tabela que o dono citou pelo nome (o primeiro na fala), ou `None`."""
    texto = dobrar(fala)
    achados: list[tuple[int, Site]] = []
    for site in SITES:
        for nome in (site.nome, *site.apelidos):
            achado = re.search(rf"(?<![\w.]){re.escape(nome)}(?![\w])", texto)
            if achado is not None:
                achados.append((achado.start(), site))
                break
    return min(achados, key=lambda par: par[0])[1] if achados else None


def dominio_citado(fala: str) -> str:
    """O domínio que o dono disse («exemplo.com.br»), ou vazio."""
    achado = DOMINIO.search(dobrar(fala))
    return achado.group(0) if achado is not None else ""
