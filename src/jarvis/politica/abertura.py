"""Abrir app e abrir site: o que o dono pré-autorizou passa, o resto não (dono, 2026-10-17).

As duas tools declaram confirmação no manifesto — o validador exige isso de todo efeito, e está
certo. O que esta regra faz é o **grant estreito** da SPEC §5.3 ("sempre permitir X" vira grant
com destino), só que configurado pelo dono antes, e não clicado na hora:

- `apps.launch`: o nome tem de resolver para um app que o dono pôs no registro autorizado
  (`apps_autorizados`); dentro, `allow`; fora, `deny` — o executor acrescenta as sugestões.
- `sites.open`: URL que não é `http`/`https` limpa é `deny`; domínio que o dono liberou
  (`sites_sem_confirmar`, com subdomínios) é `allow`; qualquer outro segue a matriz comum, que
  para `egress` é `confirm` na janela.

Nada aqui é decidido pelo modelo nem por conteúdo de página (P1, P6): os conjuntos vêm da
configuração do dono, e a regra só **aperta** ou devolve o que ele mesmo já autorizou.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any, Final
from urllib.parse import urlsplit

from jarvis.politica.memoria import RegraDeMemoria

ESQUEMAS: Final = frozenset({"http", "https"})
TAMANHO_MAXIMO: Final = 2048


class UrlRecusada(ValueError):
    """A URL não é algo que se abre no navegador do dono."""


def validar_url(bruta: str) -> str:
    url = bruta.strip()
    if len(url) > TAMANHO_MAXIMO:
        raise UrlRecusada("URL longa demais")
    if any(c in url for c in "\r\n\t\x00 "):
        raise UrlRecusada("URL com espaço ou caractere de controle")
    partes = urlsplit(url)
    if partes.scheme.lower() not in ESQUEMAS:
        raise UrlRecusada(f"só http e https abrem no navegador (veio {partes.scheme or 'nada'!r})")
    if not partes.hostname:
        raise UrlRecusada("URL sem endereço")
    if partes.username or partes.password:
        raise UrlRecusada("URL com usuário ou senha embutidos não é aberta")
    return url


def dominio(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def dominio_liberado(host: str, liberados: frozenset[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in liberados)


def nome_de_app(texto: str) -> str:
    """Como o nome de um app é comparado: sem acento, sem caixa, sem espaço nas pontas."""
    return (
        "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
        .casefold()
        .strip()
    )


def decidir_abertura(
    tool_id: str,
    args: Mapping[str, Any],
    *,
    apps_autorizados: frozenset[str],
    sites_sem_confirmar: frozenset[str],
) -> RegraDeMemoria | None:
    """O que a regra decide antes da matriz comum. `None` = siga o comum (`confirm`)."""
    if tool_id == "apps.launch":
        if nome_de_app(str(args.get("nome", ""))) in apps_autorizados:
            return RegraDeMemoria("allow", "app no registro que o dono autorizou")
        return RegraDeMemoria(
            "deny", "fora do registro de aplicativos que o dono autorizou (apps_autorizados)"
        )
    if tool_id == "sites.open":
        try:
            url = validar_url(str(args.get("url", "")))
        except UrlRecusada as erro:
            return RegraDeMemoria("deny", str(erro))
        if dominio_liberado(dominio(url), sites_sem_confirmar):
            return RegraDeMemoria("allow", f"{dominio(url)} está entre os sites que o dono liberou")
    return None
