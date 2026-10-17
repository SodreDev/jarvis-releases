"""Os navegadores do dono: achar os instalados, deixá-lo escolher o binário e abrir sites neles.

Pedido do dono (2026-10-17): na janela, ver os navegadores instalados, escolher à mão o binário
de cada um quando há mais de um (o Brave do pacote, o Beta, o Flatpak), marcar o **principal** e
os outros, e o `sites.open` abrir no principal. Nada disto passa pelo modelo: a lista é a
configuração (`navegadores = ["firefox=/usr/bin/firefox"]`), o `argv` é montado aqui e a URL é
um elemento só dele, já validada (`validar_url`: só http/https, sem senha).

Sem navegador configurado o comportamento de antes continua: o portal do desktop abre no padrão.
"""

from __future__ import annotations

import shutil
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from jarvis.executor.lancador import (
    PASTAS_DE_APLICATIVOS,
    App,
    AppRecusado,
    app_de_binario,
    lancar_argv,
    ler_desktop,
)

BINARIOS_CONHECIDOS: Final[tuple[str, ...]] = (
    "firefox",
    "librewolf",
    "zen-browser",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "brave-browser",
    "brave-browser-stable",
    "brave",
    "vivaldi",
    "vivaldi-stable",
    "opera",
    "microsoft-edge",
    "microsoft-edge-stable",
    "falkon",
    "epiphany",
)
"""Nomes comuns no PATH: achá-los junta ao navegador os binários que não têm `.desktop` próprio."""
MARCADORES_DO_FLATPAK: Final = frozenset({"@@u", "@@U", "@@"})
SUFIXOS_DE_NOME: Final = ("web browser", "browser", "navegador web", "navegador")
"""Tirados do nome para achar a família («Brave Web Browser (Beta)» é o Brave)."""


@dataclass(frozen=True, slots=True)
class Opcao:
    """Um jeito de abrir um navegador: o que vai na configuração e o que o dono lê na tela."""

    entrada: str
    """Caminho absoluto de um binário ou de um `.desktop` — o que `navegadores` guarda."""
    rotulo: str
    argv: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Navegador:
    familia: str
    nome: str
    opcoes: tuple[Opcao, ...]


def _simples(texto: str) -> str:
    return (
        "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
        .casefold()
        .strip()
    )


def familia_de(nome: str) -> str:
    """O nome curto da família: «Brave Web Browser (Beta)» → `brave`, «Google Chrome» → `chrome`."""
    limpo = _simples(nome.split("(")[0])
    for sufixo in SUFIXOS_DE_NOME:
        limpo = limpo.removesuffix(sufixo).strip()
    palavras = [p for p in limpo.replace("_", " ").replace("-", " ").split() if p != "google"]
    base = (palavras[0] if palavras else limpo) or "navegador"
    return "".join(c for c in base if c.isalnum()) or "navegador"


def _argv_do_app(app: App) -> tuple[str, ...]:
    return tuple(a for a in app.argv if a not in MARCADORES_DO_FLATPAK)


def argv_da_entrada(entrada: str) -> tuple[str, ...]:
    """O `argv` (sem URL) do que a configuração guardou, ou `()` se já não existe."""
    arquivo = Path(entrada).expanduser()
    if arquivo.suffix == ".desktop":
        app = ler_desktop(arquivo) if arquivo.is_absolute() else None
        return _argv_do_app(app) if app is not None else ()
    app = app_de_binario(entrada)
    return app.argv if app is not None else ()


def _rotulo(app: App | None, caminho: str) -> str:
    """O que o dono lê no botão: o nome do navegador e o programa que ele abre."""
    if app is not None:
        return f"{app.nome} · {Path(_argv_do_app(app)[0]).name}"
    return caminho


def detectar(
    *,
    pastas: Sequence[str] = PASTAS_DE_APLICATIVOS,
    caminho_dos_binarios: str | None = None,
) -> tuple[Navegador, ...]:
    """Os navegadores instalados: todo `.desktop` que trata `https`, agrupado por família, mais os
    binários conhecidos que estiverem no PATH. Cada família traz **todas** as opções que achou."""
    familias: dict[str, dict[str, Opcao]] = {}
    nomes: dict[str, str] = {}
    vistos: set[str] = set()
    for pasta in pastas:
        base = Path(pasta).expanduser()
        if not base.is_dir():
            continue
        for arquivo in sorted(base.glob("*.desktop")):
            app = ler_desktop(arquivo)
            if app is None or app.id in vistos or "https" not in app.esquemas:
                continue
            vistos.add(app.id)
            familia = familia_de(app.nome)
            nomes.setdefault(familia, app.nome.split("(")[0].strip())
            argv = _argv_do_app(app)
            opcao = Opcao(entrada=str(arquivo), rotulo=_rotulo(app, str(arquivo)), argv=argv)
            familias.setdefault(familia, {}).setdefault(" ".join(argv), opcao)
    for nome_do_binario in BINARIOS_CONHECIDOS:
        achado = shutil.which(nome_do_binario, path=caminho_dos_binarios)
        if achado is None:
            continue
        familia = familia_de(nome_do_binario.replace("-stable", ""))
        opcao = Opcao(entrada=achado, rotulo=achado, argv=(achado,))
        grupo = familias.setdefault(familia, {})
        if all(o.argv[0] != achado for o in grupo.values()):
            grupo.setdefault(achado, opcao)
        nomes.setdefault(familia, familia.capitalize())
    return tuple(
        Navegador(familia=f, nome=nomes[f], opcoes=tuple(familias[f].values()))
        for f in sorted(familias, key=lambda f: _simples(nomes[f]))
    )


def separar(entradas: Iterable[str]) -> dict[str, str]:
    """`["firefox=/usr/bin/firefox"]` → `{"firefox": "/usr/bin/firefox"}` (vale a última)."""
    pares: dict[str, str] = {}
    for entrada in entradas:
        familia, _, caminho = entrada.partition("=")
        if familia and caminho:
            pares[familia] = caminho
    return pares


def juntar(pares: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(f"{familia}={caminho}" for familia, caminho in pares.items())


@dataclass(slots=True)
class AbridorDeNavegador:
    """Abre uma URL no navegador principal, ou no que o pedido nomeou (se estiver configurado)."""

    navegadores: Mapping[str, str]
    principal: str
    lancar: Callable[..., int] = lancar_argv
    ambiente: Mapping[str, str] | None = None

    def familias(self) -> tuple[str, ...]:
        return tuple(self.navegadores)

    def escolher(self, pedido: str = "") -> str:
        alvo = _simples(pedido) if pedido.strip() else self.principal
        if alvo not in self.navegadores:
            validos = ", ".join(self.navegadores) or "nenhum"
            raise AppRecusado(f"navegador {alvo!r} não está configurado (há: {validos})")
        return alvo

    def abrir(self, url: str, navegador: str = "") -> str:
        """Abre `url` e devolve a família usada. `AppRecusado` se o binário sumiu."""
        familia = self.escolher(navegador)
        argv = argv_da_entrada(self.navegadores[familia])
        if not argv:
            raise AppRecusado(
                f"o navegador {familia} ({self.navegadores[familia]}) não está mais lá: "
                "escolha o binário de novo em Configuração → Navegadores"
            )
        self.lancar((*argv, url), ambiente=self.ambiente)
        return familia


def existe(caminho: str) -> bool:
    return Path(caminho).expanduser().exists()
