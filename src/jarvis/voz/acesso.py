"""O que o dono pode mexer em pastas, aplicativos e navegadores — sem Qt e sem disco.

A janela (`jarvis.gui.acesso`) só chama estas funções e grava o resultado. Cada uma devolve uma
`Configuracao` nova (a classe é imutável) ou levanta `AcessoRecusado` com a frase que o dono lê.
Nada aqui decide o que o Jarvis *pode* fazer: isso é o PDP (`jarvis.politica`). Aqui só se
escreve a lista que o PDP lê, e se recusa de saída o que ele recusaria depois (a lista de
negação não é confirmável nem na configuração).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from jarvis.executor.lancador import PASTAS_DE_APLICATIVOS, App, app_de_caminho, listar_apps
from jarvis.executor.navegadores import Navegador, detectar, familia_de, juntar, separar
from jarvis.politica.abertura import nome_de_app
from jarvis.politica.canonicalizacao import CaminhoRecusado, Sistema, canonicalizar
from jarvis.politica.modos import (
    NEGADOS_ABSOLUTOS_POSIX,
    NEGADOS_RELATIVOS_AO_LAR,
    NOMES_NEGADOS,
    motivo_de_negacao,
)
from jarvis.voz.config import ACESSOS, Configuracao

NIVEIS: Final[tuple[str, ...]] = ("leitura", "escrita")
MODOS_QUE_USAM_AS_RAIZES: Final[tuple[str, ...]] = ("concedido", "total")
FRASE_DOS_MODOS: Final[dict[str, tuple[str, str]]] = {
    "jarvis": ("só a área do Jarvis", "nenhuma pasta sua: o Jarvis só mexe na pasta dele"),
    "padrao": (
        "pastas de sempre",
        "Documentos, Downloads, Imagens, Música, Vídeos e Área de Trabalho",
    ),
    "concedido": ("as pastas que eu escolher", "as de sempre, mais as da lista abaixo"),
    "total": ("o computador inteiro", "tudo que é seu, menos a lista de negação (abaixo)"),
}
"""(nome, o que significa) de cada nível de acesso, na ordem de amplitude."""


class AcessoRecusado(ValueError):
    """A mudança não vale; a mensagem diz por quê, em português."""


def negacoes_fixas() -> tuple[str, ...]:
    """O que fica negado em qualquer nível, para a tela mostrar (não é editável)."""
    return (
        *(f"~/{alvo}" for alvo in NEGADOS_RELATIVOS_AO_LAR if "AppData" not in alvo),
        *NEGADOS_ABSOLUTOS_POSIX,
        *(f"qualquer arquivo chamado {nome}" for nome in NOMES_NEGADOS),
    )


def _caminho_da_pasta(texto: str, lar: Path) -> Path:
    bruto = texto.strip()
    if not bruto:
        raise AcessoRecusado("nenhuma pasta escolhida")
    caminho = Path(bruto).expanduser()
    if not caminho.is_absolute():
        raise AcessoRecusado(f"use o caminho inteiro da pasta (veio {bruto!r})")
    if not caminho.exists():
        raise AcessoRecusado(f"{caminho} não existe")
    if not caminho.is_dir():
        raise AcessoRecusado(
            f"{caminho} é um arquivo: o acesso é por pasta, escolha a pasta que o contém "
            "(o Jarvis lê os arquivos dela, e a lista de negação continua valendo)"
        )
    try:
        canonico = canonicalizar(str(caminho), Sistema.POSIX)
    except CaminhoRecusado as erro:
        raise AcessoRecusado(f"{caminho}: {erro}") from None
    negado = motivo_de_negacao(canonico, lar, Sistema.POSIX)
    if negado is not None:
        raise AcessoRecusado(f"{caminho} fica negada para sempre ({negado})")
    return Path(canonico.texto)


__all__ = [
    "PASTAS_DE_APLICATIVOS",
    "AcessoRecusado",
    "App",
    "Navegador",
    "app_de_caminho",
    "detectar",
    "listar_apps",
    "nome_de_app",
    "separar",
]
"""Re-exportados para a janela: ela chega ao executor e à política por aqui (ADR-0019)."""


def com_modo(configuracao: Configuracao, modo: str) -> Configuracao:
    if modo not in ACESSOS:
        raise AcessoRecusado(f"nível de acesso {modo!r} não existe")
    return configuracao.com(acesso=modo)


def com_raiz(configuracao: Configuracao, texto: str, *, lar: Path) -> Configuracao:
    """Concede uma pasta (só leitura). Vira o nível «as pastas que eu escolher» se ele era
    mais estreito — sem isso a pasta ficaria na lista sem valer, que é a pior mentira."""
    caminho = str(_caminho_da_pasta(texto, lar))
    raizes = (*[r for r in configuracao.raizes if r != caminho], caminho)
    mudancas: dict[str, object] = {"raizes": raizes}
    if configuracao.acesso not in MODOS_QUE_USAM_AS_RAIZES:
        mudancas["acesso"] = "concedido"
    return configuracao.com(**mudancas)


def sem_raiz(configuracao: Configuracao, caminho: str) -> Configuracao:
    return configuracao.com(
        raizes=tuple(r for r in configuracao.raizes if r != caminho),
        raizes_escrita=tuple(r for r in configuracao.raizes_escrita if r != caminho),
    )


def com_nivel_da_raiz(configuracao: Configuracao, caminho: str, nivel: str) -> Configuracao:
    if nivel not in NIVEIS:
        raise AcessoRecusado(f"nível {nivel!r} não existe (há: {', '.join(NIVEIS)})")
    if caminho not in configuracao.raizes:
        raise AcessoRecusado(f"{caminho} não está na lista de pastas")
    sem = tuple(r for r in configuracao.raizes_escrita if r != caminho)
    return configuracao.com(raizes_escrita=(*sem, caminho) if nivel == "escrita" else sem)


def nivel_da_raiz(configuracao: Configuracao, caminho: str) -> str:
    return "escrita" if caminho in configuracao.raizes_escrita else "leitura"


def com_app(configuracao: Configuracao, identificador: str, marcado: bool) -> Configuracao:
    base = tuple(a for a in configuracao.apps_autorizados if a != identificador)
    return configuracao.com(apps_autorizados=(*base, identificador) if marcado else base)


def com_app_extra(configuracao: Configuracao, texto: str) -> Configuracao:
    """Um aplicativo escolhido à mão: um `.desktop` ou um binário executável."""
    caminho = Path(texto.strip()).expanduser()
    if not caminho.is_absolute() or not caminho.is_file():
        raise AcessoRecusado(f"{texto!r} não é um arquivo (use o caminho inteiro)")
    if app_de_caminho(str(caminho)) is None:
        raise AcessoRecusado(
            f"{caminho.name} não serve: tem de ser um .desktop de aplicativo ou um programa "
            "executável (shells, sudo e afins ficam de fora)"
        )
    extras = (*[e for e in configuracao.apps_extras if e != str(caminho)], str(caminho))
    return configuracao.com(apps_extras=extras)


def sem_app_extra(configuracao: Configuracao, caminho: str) -> Configuracao:
    return configuracao.com(apps_extras=tuple(e for e in configuracao.apps_extras if e != caminho))


def com_navegador(configuracao: Configuracao, familia: str, entrada: str) -> Configuracao:
    """Fixa o binário (ou `.desktop`) de uma família. O primeiro navegador vira o principal."""
    caminho = Path(entrada.strip()).expanduser()
    if not caminho.is_absolute() or not caminho.exists():
        raise AcessoRecusado(f"{entrada!r} não existe (use o caminho inteiro)")
    if app_de_caminho(str(caminho)) is None:
        raise AcessoRecusado(f"{caminho.name} não é um programa executável nem um .desktop")
    pares = separar(configuracao.navegadores)
    pares[familia] = str(caminho)
    principal = configuracao.navegador_principal or familia
    return configuracao.com(navegadores=juntar(pares), navegador_principal=principal)


def com_navegador_manual(configuracao: Configuracao, entrada: str) -> tuple[Configuracao, str]:
    """Um navegador que a detecção não achou; a família sai do nome do arquivo."""
    nome = Path(entrada.strip()).name.removesuffix(".desktop")
    familia = familia_de(nome)
    return com_navegador(configuracao, familia, entrada), familia


def sem_navegador(configuracao: Configuracao, familia: str) -> Configuracao:
    pares = separar(configuracao.navegadores)
    pares.pop(familia, None)
    principal = configuracao.navegador_principal
    if principal == familia:
        principal = next(iter(pares), "")
    return configuracao.com(navegadores=juntar(pares), navegador_principal=principal)


def com_principal(configuracao: Configuracao, familia: str) -> Configuracao:
    if familia not in separar(configuracao.navegadores):
        raise AcessoRecusado(f"{familia} ainda não tem binário escolhido: escolha um antes")
    return configuracao.com(navegador_principal=familia)
