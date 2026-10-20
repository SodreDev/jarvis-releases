"""Abrir app e abrir site: o que o dono pré-autorizou passa, o resto não (dono, 2026-10-17).

As três tools são do tier `livre` (dono, 2026-10-18: abrir app, site e navegador não pede
confirmação). O que esta regra faz é o **grant estreito** da SPEC §5.3 ("sempre permitir X" vira
grant com destino), só que configurado pelo dono antes, e não clicado na hora — o que ele não
configurou continua negado, e o que o turno leu de terceiros aperta o site:

- `apps.launch`: o nome tem de resolver para um app que o dono pôs no registro autorizado
  (`apps_autorizados`); dentro, `allow`; fora, `deny` — o executor acrescenta as sugestões.
- `browser.launch`: abrir só o navegador (sem endereço); o principal ou um que o dono nomeou
  entre os que ele configurou é `allow`, o resto é `deny`;
- `sites.open`: URL que não é `http`/`https` limpa é `deny`; domínio que o dono liberou
  (`sites_sem_confirmar`, com subdomínios) é `allow`; qualquer outro é livre — **exceto** num turno
  que já leu conteúdo de terceiros (arquivo, página, memória), onde vira `confirm`: o endereço
  carrega o que estiver nele, e foi um texto de fora que pode tê-lo escolhido.

Nada aqui é decidido pelo modelo nem por conteúdo de página (P1, P6): os conjuntos vêm da
configuração do dono, e a regra só **aperta** ou devolve o que ele mesmo já autorizou.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

from jarvis.politica.memoria import RegraDeMemoria

if TYPE_CHECKING:
    from jarvis.politica.objetivo import Objetivo

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


SEGUNDO_NIVEL: Final = frozenset(
    {"com", "net", "org", "gov", "edu", "co", "ac", "mil", "gob", "nom"}
)
"""Sob um domínio de país de 2 letras, estes rótulos são parte do sufixo (`com.br`, `co.uk`,
`gov.br`): o nome do site é o rótulo antes deles."""


def dominio_registravel(host: str) -> str:
    """`www.youtube.com` → `youtube.com`; `m.youtube.com.br` → `youtube.com.br`;
    `youtube.evil.com` → `evil.com`. Aproximação sem a lista pública de sufixos (TLD e, sob TLD de
    país, um segundo nível comum). Host de rótulo único ou IP não tem nome de site: vazio."""
    rotulos = [r for r in host.lower().rstrip(".").split(".") if r]
    if len(rotulos) < 2 or all(r.isdigit() for r in rotulos):
        return ""
    sufixo = 2 if len(rotulos[-1]) == 2 and rotulos[-2] in SEGUNDO_NIVEL else 1
    return ".".join(rotulos[-(sufixo + 1) :]) if len(rotulos) > sufixo else ""


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
    navegadores: frozenset[str] = frozenset(),
    navegador_principal: str = "",
    contaminado: bool = False,
    objetivo: Objetivo | None = None,
) -> RegraDeMemoria | None:
    """O que a regra decide antes da matriz comum. `None` = siga o comum (o tier do manifesto)."""
    if tool_id == "apps.launch":
        if nome_de_app(str(args.get("nome", ""))) in apps_autorizados:
            return RegraDeMemoria("allow", "app no registro que o dono autorizou")
        return RegraDeMemoria(
            "deny", "fora do registro de aplicativos que o dono autorizou (apps_autorizados)"
        )
    if tool_id == "browser.launch":
        pedido = nome_de_app(str(args.get("navegador", "")))
        if pedido:
            if pedido in navegadores:
                return RegraDeMemoria("allow", "navegador que o dono configurou")
            return RegraDeMemoria(
                "deny", "fora dos navegadores que o dono configurou (Configuração → Navegadores)"
            )
        if navegador_principal in navegadores and navegador_principal:
            return RegraDeMemoria("allow", "navegador principal que o dono configurou")
        return RegraDeMemoria(
            "deny", "nenhum navegador principal configurado (Configuração → Navegadores)"
        )
    if tool_id == "sites.open":
        try:
            url = validar_url(str(args.get("url", "")))
        except UrlRecusada as erro:
            return RegraDeMemoria("deny", str(erro))
        if dominio_liberado(dominio(url), sites_sem_confirmar):
            return RegraDeMemoria("allow", f"{dominio(url)} está entre os sites que o dono liberou")
        if objetivo is not None:
            levados = objetivo.leva_dado_do_dono(url)
            if levados:
                return RegraDeMemoria(
                    "confirm",
                    f"o endereço leva {', '.join(levados)} para {dominio(url)}, que o dono não "
                    "citou: confirma antes de abrir",
                )
            if objetivo.dentro(url):
                return None  # dentro do objetivo (citado ou alcançado): o tier decide
        if contaminado:
            # Abrir site é livre (dono, 2026-10-18), mas o endereço leva o que estiver nele. Se o
            # turno leu conteúdo de terceiros, um endereço escolhido por esse conteúdo (injeção)
            # poderia carregar dado do dono: aí só abre com o "sim" dele.
            return RegraDeMemoria(
                "confirm",
                f"o turno leu conteúdo de terceiros e {dominio(url)} não é um site que o dono "
                "liberou: confirma antes de abrir",
            )
    return None
