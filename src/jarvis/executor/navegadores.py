"""Os navegadores do dono: achar os instalados, deixá-lo escolher o binário e abrir sites neles.

Pedido do dono (2026-10-17): na janela, ver os navegadores instalados, escolher à mão o binário
de cada um quando há mais de um (o Brave do pacote, o Beta, o Flatpak), marcar o **principal** e
os outros, e o `sites.open` abrir no principal. Nada disto passa pelo modelo: a lista é a
configuração (`navegadores = ["firefox=/usr/bin/firefox"]`), o `argv` é montado aqui e a URL é
um elemento só dele, já validada (`validar_url`: só http/https, sem senha).

Sem navegador configurado o comportamento de antes continua: o portal do desktop abre no padrão.

**Uma instância só** (dono, 2026-10-21: o Jarvis abriu "outra instância" do Brave e o vídeo foi
parar nela): o Jarvis só abre um navegador se não houver um ativo. Com a extensão conectada, o
site vai por ela — inclusive o pedido de aba nova, que antes pulava a extensão e executava o
binário com a URL, e o navegador a punha na última janela ativa dele, que podia não ser a do dono;
"abrir o navegador" com ele já aberto traz a janela do dono para a frente. Sem extensão, um
processo do navegador rodando (lido em `/proc`, só o executável) também conta como ativo.
"""

from __future__ import annotations

import shutil
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

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

EXECUTAVEIS_DA_FAMILIA: Final[dict[str, frozenset[str]]] = {
    "brave": frozenset({"brave", "brave-browser"}),
    "chrome": frozenset({"chrome", "google-chrome"}),
    "chromium": frozenset({"chromium", "chromium-browser"}),
    "firefox": frozenset({"firefox", "firefox-bin", "firefox-esr"}),
    "librewolf": frozenset({"librewolf"}),
    "zen": frozenset({"zen", "zen-bin"}),
    "vivaldi": frozenset({"vivaldi", "vivaldi-bin"}),
    "opera": frozenset({"opera"}),
    "microsoft": frozenset({"msedge", "microsoft-edge"}),
    "edge": frozenset({"msedge", "microsoft-edge"}),
    "falkon": frozenset({"falkon"}),
    "epiphany": frozenset({"epiphany", "epiphany-browser"}),
}
"""O nome do executável de cada família, como `/proc/<pid>/exe` o mostra (no Flatpak, o de dentro
da caixa: `/app/lib/firefox/firefox`). Família fora daqui: o próprio nome dela."""

ReutilizarAba = Callable[[str, str, bool], Mapping[str, Any] | None]
"""O navegador já aberto, pela extensão: URL, família e se o pedido é de aba nova. Devolve como
abriu (`tab_id`, `nova_aba`, `visivel`…) ou `None` sem extensão daquela família conectada."""
MostrarAberto = Callable[[str], Mapping[str, Any] | None]
"""O navegador daquela família já aberto com a extensão: põe a janela do dono à vista e diz como
ficou (`visivel`); `None` sem extensão conectada."""
EmExecucao = Callable[[str], int | None]
"""O PID de um processo daquele navegador rodando agora (do próprio usuário), ou `None`."""


def familia_de_navegador(nome: str) -> str | None:
    """A família, se o app é um navegador conhecido («Brave Web Browser» → `brave`), ou `None`."""
    familia = familia_de(nome)
    return familia if familia in EXECUTAVEIS_DA_FAMILIA else None


def navegador_em_execucao(familia: str, *, raiz: Path = Path("/proc")) -> int | None:
    """Um processo da família rodando agora: lê só o executável de cada processo (`exe`), nunca o
    ambiente nem a linha de comando; processo de outro usuário não se deixa ler e não conta."""
    nomes = EXECUTAVEIS_DA_FAMILIA.get(familia, frozenset({familia}))
    try:
        entradas = sorted(
            (e for e in raiz.iterdir() if e.name.isdigit()), key=lambda e: int(e.name)
        )
    except OSError:
        return None
    for entrada in entradas:
        try:
            executavel = (entrada / "exe").readlink()
        except OSError:
            continue
        if executavel.name.removesuffix(" (deleted)").lower() in nomes:
            return int(entrada.name)
    return None


@dataclass(frozen=True, slots=True)
class NavegadorAberto:
    """O que o `browser.launch` fez: abriu o navegador, ou ele já estava aberto (e não ganhou
    outra janela nem instância)."""

    familia: str
    pid: int | None
    ja_aberto: bool = False
    visivel: bool = False

    def para_o_modelo(self) -> dict[str, Any]:
        if not self.ja_aberto:
            return {"navegador": self.familia, "pid": self.pid}
        situacao = (
            "o navegador já estava aberto: a janela do dono veio para a frente, e nada de outra "
            "janela"
            if self.visivel
            else "o navegador já estava aberto e não abri outra janela; ele não veio para a frente "
            "(sem a extensão conectada, ou o sistema segurou o foco)"
        )
        return {
            "navegador": self.familia,
            "pid": None,
            "ja_aberto": True,
            "visivel": self.visivel,
            "situacao": situacao,
        }


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
    reutilizar_aba: ReutilizarAba | None = None
    """Com a extensão conectada, o site abre por ela, no navegador que já está aberto."""
    mostrar_aberto: MostrarAberto | None = None
    """Com a extensão conectada, "abrir o navegador" traz a janela do dono para a frente."""
    em_execucao: EmExecucao | None = None
    """Sem extensão, o navegador rodando também conta como aberto (o app liga o `/proc`)."""

    def familias(self) -> tuple[str, ...]:
        return tuple(self.navegadores)

    def escolher(self, pedido: str = "") -> str:
        alvo = _simples(pedido) if pedido.strip() else self.principal
        if alvo not in self.navegadores:
            validos = ", ".join(self.navegadores) or "nenhum"
            raise AppRecusado(f"navegador {alvo!r} não está configurado (há: {validos})")
        return alvo

    def abrir(
        self, url: str, navegador: str = "", *, reutilizar_aba: bool = True
    ) -> tuple[str, bool]:
        """Abre `url`; devolve família e se uma aba que já estava aberta foi reutilizada.

        Com a extensão conectada, vai por ela — também a aba nova (`reutilizar_aba=False`), que
        antes pulava a extensão e executava o binário: com o navegador aberto, ele punha a URL na
        última janela ativa dele, que foi a janela própria do Jarvis (dono, 2026-10-21). Só sem
        extensão o binário é executado com a URL: abre o navegador, ou, se ele já está rodando,
        o próprio navegador a entrega à instância que já existe. Não há atalho de linha de comando
        portátil que prometa trocar a aba ativa, portanto nunca fingimos reutilização.
        """
        familia = self.escolher(navegador)
        if self.reutilizar_aba is not None:
            feito = self.reutilizar_aba(url, familia, not reutilizar_aba)
            if feito is not None:
                return familia, not feito.get("nova_aba", False)
        argv = argv_da_entrada(self.navegadores[familia])
        if not argv:
            raise AppRecusado(
                f"o navegador {familia} ({self.navegadores[familia]}) não está mais lá: "
                "escolha o binário de novo em Configuração → Navegadores"
            )
        self.lancar((*argv, url), ambiente=self.ambiente)
        return familia, False

    def ja_aberto(self, familia: str) -> NavegadorAberto | None:
        """O navegador daquela família já aberto, sem lançar nada (dono, 2026-10-21): com a
        extensão conectada, a janela do dono vem para a frente; sem ela, o processo rodando basta
        (abrir o binário de novo daria outra janela). `None` quando não há um ativo — ou quando a
        extensão diz que ele está aberto sem janela nenhuma: aí abrir é abrir a janela dele, na
        instância que já existe."""
        mostrado = self.mostrar_aberto(familia) if self.mostrar_aberto is not None else None
        if mostrado is not None:
            if mostrado.get("sem_janela"):
                return None
            return NavegadorAberto(
                familia, None, ja_aberto=True, visivel=bool(mostrado.get("visivel"))
            )
        if self.em_execucao is not None and self.em_execucao(familia):
            return NavegadorAberto(familia, None, ja_aberto=True)
        return None

    def abrir_sozinho(self, navegador: str = "") -> NavegadorAberto:
        """Abre só o navegador, sem URL — se não houver um ativo (`ja_aberto`)."""
        familia = self.escolher(navegador)
        aberto = self.ja_aberto(familia)
        if aberto is not None:
            return aberto
        argv = argv_da_entrada(self.navegadores[familia])
        if not argv:
            raise AppRecusado(
                f"o navegador {familia} ({self.navegadores[familia]}) não está mais lá: "
                "escolha o binário de novo em Configuração → Navegadores"
            )
        return NavegadorAberto(familia, self.lancar(argv, ambiente=self.ambiente))

    def resolver(self, pedido: str) -> str | None:
        """A família configurada que o dono quis dizer («Brave», «brave-browser»), ou `None`."""
        alvo = _simples(pedido)
        if alvo in self.navegadores:
            return alvo
        return next(
            (f for f in self.navegadores if f == familia_de(pedido) or _simples(f) == alvo), None
        )


def existe(caminho: str) -> bool:
    return Path(caminho).expanduser().exists()
