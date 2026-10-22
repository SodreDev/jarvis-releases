"""As janelas do sistema e qual delas é o app que o Jarvis abriu (dono, 2026-10-20, ADR-0037).

Ao abrir um app, o foco tem de ir para ele — e app **lento** (o Steam, que pode pedir a conta antes,
e o jogo, que demora e abre a janela dele depois) não aparece na hora. Esta parte lista as janelas
(a em primeiro plano e as em segundo) e decide **com evidência** qual é a do app:

- o **PID**: a janela é do processo lançado ou de um descendente dele;
- o **jogo do Steam**: a classe `steam_app_<id>` ou o processo da janela descende do `reaper` do
  Steam com `AppId=<id>` — o id que estava no `steam://rungameid/<id>` do lançamento;
- a **classe** da janela (`WM_CLASS` no X11, `app_id` no Wayland) é a do app: o `StartupWMClass` do
  `.desktop`, o id do `.desktop` ou o executável;
- o **executável** do processo da janela é o que foi lançado;
- a janela é **nova** (não existia antes do lançamento) e o **título** traz o nome do catálogo.

Janela de nome genérico que pode ou não ser o app **não** é focada por palpite: nova e com o nome
no título não bastam (2 pontos); é preciso uma ligação com o que foi lançado (PID, jogo, classe ou
executável). Duas candidatas empatadas são dúvida — o dono escolhe. A janela de entrar na conta do
Steam é dele: o Jarvis espera. Executável e classe genéricos (`python3`, `flatpak`, `java`…) não
contam: dizem nada sobre qual app é.

Quem lista é o mesmo de `jarvis.entrada.foco`: `kdotool` no KDE (Wayland ou X11; uma chamada por
ciclo, encadeada) e `wmctrl` + `xprop` no X11. No Wayland sem o `kdotool` não há como ver as janelas
dos outros apps — e o Jarvis diz isso em vez de chutar.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable

from jarvis.executor import desktop
from jarvis.executor.comandos import (
    ComandoIndisponivel,
    ComandoRecusado,
    Lancador,
    executar,
    instalado,
)

PRAZO_S: Final = 3.0
PRAZO_DO_FOCO_S: Final = 300.0
"""Quanto se espera a janela de um app aberto (o dono muda em `prazo_do_foco_s`): cinco minutos,
porque o jogo pelo Steam demora."""
LIMITE_DE_JANELAS: Final = 200
NA_LISTA_DO_MODELO: Final = 40
# Padrões como texto, sem `re.compile`: a varredura de «sem shell» proíbe qualquer chamada
# `compile()` no executor, e o `re` guarda o padrão compilado sozinho.
ID_DE_JANELA: Final = r"0x[0-9a-fA-F]{1,8}|\{[0-9a-fA-F-]{36}\}"
"""X11 (`0x3a00003`) ou KWin (`{uuid}`): o mesmo padrão do `janela_id` do manifesto."""
_HEXA: Final = r"\b(0x[0-9a-fA-F]+)\b"
_LOGIN_DO_STEAM: Final = (
    r"(?i)\b(?:entrar|login|log in|sign in|iniciar sess\w*|escolh\w* (?:a|uma) conta|"
    r"choose an account|account|conta)\b"
)
_JOGO_DO_STEAM: Final = r"steam://(?:rungameid|run)/(\d+)"
_APPID: Final = r"AppId=(\d+)"


def id_de_janela(texto: str) -> bool:
    return re.fullmatch(ID_DE_JANELA, texto) is not None


GENERICOS: Final = frozenset(
    {
        "python", "python3", "python2", "java", "node", "electron", "sh", "bash", "env", "flatpak",
        "snap", "wine", "wine64", "wine-preloader", "wine64-preloader", "mono", "dotnet", "perl",
        "ruby", "gjs", "xdg-open", "gtk-launch", "kioclient", "kioclient5", "kstart", "kstart5",
        "proton", "reaper", "bwrap", "pressure-vessel-wrap", "appimagelauncher",
    }
)  # fmt: skip
"""Executáveis que são o embrulho, não o app: casar por eles casaria qualquer coisa."""
DO_SISTEMA: Final = frozenset(
    {
        "plasmashell", "org.kde.plasmashell", "kwin", "kwin_wayland", "kwin_x11", "krunner",
        "org.kde.krunner", "ksmserver", "ksplashqml", "xwaylandvideobridge",
        "org.kde.xwaylandvideobridge", "polkit-kde-authentication-agent-1",
        "org.kde.polkit-kde-authentication-agent-1", "spectacle", "org.kde.spectacle",
    }
)  # fmt: skip
"""A casca do desktop (painel, área de trabalho, lançador): não é janela de app."""


@dataclass(frozen=True, slots=True)
class JanelaDoSistema:
    id: str
    titulo: str
    classe: str
    pid: int | None
    ativa: bool = False
    """Em primeiro plano (a janela ativa, a do teclado); as outras estão em segundo."""
    monitor: str = ""
    """O monitor dela (`DP-1`, `HDMI-A-1`), quando a leitura diz; vazio = não se sabe."""
    principal: bool = False
    """Está no monitor principal (o primeiro da ordem do KDE)."""
    na_frente: bool = False
    """É a da frente **no monitor dela** — com dois monitores, a janela que o dono vê no principal
    não é a ativa quando ele está no outro (dono, 2026-10-21: o Brave na frente do principal não
    era «o que está em foco» para o Jarvis)."""
    minimizada: bool = False
    visivel: bool = True
    """Nesta área de trabalho e não minimizada."""
    normal: bool = True
    """Janela de app ou diálogo — não painel, área de trabalho, menu ou aviso."""


@dataclass(frozen=True, slots=True)
class Monitor:
    nome: str
    principal: bool
    x: int = 0
    y: int = 0
    largura: int = 0
    altura: int = 0


@dataclass(frozen=True, slots=True)
class EstadoDasJanelas:
    """Uma leitura só: as janelas, os monitores (o principal primeiro) e qual está ativa."""

    janelas: tuple[JanelaDoSistema, ...]
    monitores: tuple[Monitor, ...] = ()
    monitor_ativo: str = ""
    """O monitor do teclado e do mouse para o KWin (`activeScreen`)."""

    @property
    def ativa(self) -> JanelaDoSistema | None:
        return next((j for j in self.janelas if j.ativa), None)

    def da_frente(self, monitor: str) -> JanelaDoSistema | None:
        return next((j for j in self.janelas if j.na_frente and j.monitor == monitor), None)


class Janelas(Protocol):
    def listar(self) -> list[JanelaDoSistema]:
        """As janelas de agora — em primeiro e em segundo plano —, ou `[]` se não deu para ver."""
        ...

    def ativar(self, janela_id: str) -> bool:
        """Põe a janela em foco. `False` = o gerenciador de janelas não deixou."""
        ...


@runtime_checkable
class FechaJanelas(Protocol):
    """A porta que também fecha uma janela (ADR-0042): o pedido educado do gerenciador de janelas,
    como o X dela — o app pode perguntar se salva. Nunca mata o processo."""

    def fechar(self, janela_id: str) -> bool:
        """`False` = o gerenciador de janelas não aceitou o pedido."""
        ...


def _rodar(lancar: Lancador, *argv: str) -> str | None:
    """A saída, ou `None` quando o programa falhou, não existe ou não respondeu."""
    try:
        saida = lancar(list(argv), PRAZO_S, None)
    except (ComandoIndisponivel, ComandoRecusado):
        return None
    return saida.saida if saida.ok else None


def _pid(texto: str) -> int | None:
    texto = texto.strip()
    return int(texto) if texto.isdigit() and int(texto) > 0 else None


CONSULTA_DO_KWIN: Final = r"""
const ordem = workspace.stackingOrder;
const mesa = workspace.currentDesktop;
const ativa = workspace.activeWindow;
const telas = (workspace.screenOrder || workspace.screens).map((o) => ({
    nome: String(o.name), x: o.geometry.x, y: o.geometry.y,
    largura: o.geometry.width, altura: o.geometry.height,
}));
const janelas = [];
for (const w of workspace.windowList()) {
    if (janelas.length >= 200) break;
    janelas.push({
        id: String(w.internalId), titulo: String(w.caption || ""),
        classe: String(w.resourceClass || ""), pid: w.pid || 0,
        tela: w.output ? String(w.output.name) : "", pilha: ordem.indexOf(w),
        minimizada: !!w.minimized, normal: !!(w.normalWindow || w.dialog),
        nesta_mesa: !!(w.onAllDesktops || w.desktops.some((d) => mesa && d.id === mesa.id)),
    });
}
output_result(JSON.stringify({
    versao: 1, ativa: ativa ? String(ativa.internalId) : "",
    tela_ativa: workspace.activeScreen ? String(workspace.activeScreen.name) : "",
    telas: telas, janelas: janelas,
}));
"""
"""A leitura de janelas do KWin numa chamada (`kdotool kwinscript --inline`, kdotool ≥ 0.3): só
lê — nenhuma propriedade é escrita. Traz o que a busca encadeada não traz: o monitor de cada
janela, a ordem dos monitores (o principal primeiro), a pilha (quem está na frente de quem), a área
de trabalho e se está minimizada. E não quebra sem janela ativa: o `getactivewindow` da busca
encadeada estoura em `null` (tudo minimizado, «mostrar a área de trabalho») e a lista inteira
voltava vazia — medido num KWin 6.7.5 virtual com dois monitores, 2026-10-21."""
_NOME_DE_MONITOR: Final = r"[\w.:() +-]{1,40}"


class JanelasPorKdotool:
    """KDE Plasma (Wayland ou X11): `kdotool`, ids do KWin (`{uuid}`).

    A leitura é a `CONSULTA_DO_KWIN`, numa chamada. Com um `kdotool` sem `kwinscript` (< 0.3), a
    busca encadeada de antes: `search` põe todas as janelas na pilha e cada ação imprime uma linha
    por janela (`%@`) — ids, títulos, classes, PIDs —, e a ativa vem numa chamada à parte, que
    pode falhar sem levar a lista junto. Título com quebra de linha desalinha os blocos: aí vale o
    caminho lento, uma chamada por janela."""

    def __init__(self, lancar: Lancador = executar) -> None:
        self._lancar = lancar
        self._sem_kwinscript = False

    def estado(self) -> EstadoDasJanelas | None:
        """A leitura completa (com monitores), ou `None` se o `kdotool` não a faz."""
        if self._sem_kwinscript:
            return None
        try:
            saida = self._lancar(
                ["kdotool", "kwinscript", "--inline", CONSULTA_DO_KWIN], PRAZO_S, None
            )
        except (ComandoIndisponivel, ComandoRecusado):
            return None
        if not saida.ok:
            # O kdotool de antes não conhece `kwinscript`: não adianta perguntar de novo.
            self._sem_kwinscript = "kwinscript" in saida.erro or "unexpected" in saida.erro
            return None
        return estado_do_kwin(saida.saida)

    def listar(self) -> list[JanelaDoSistema]:
        estado = self.estado()
        if estado is not None:
            return list(estado.janelas)
        bruto = _rodar(
            self._lancar,
            "kdotool",
            "search",
            "--class",
            ".",
            *("getwindowid", "%@", "getwindowname", "%@"),
            *("getwindowclassname", "%@", "getwindowpid", "%@"),
        )
        if bruto is None:
            return []
        linhas = bruto.split("\n")
        if linhas and linhas[-1] == "":
            linhas.pop()
        ativa = (_rodar(self._lancar, "kdotool", "getactivewindow") or "").strip()
        janelas = _blocos_do_kdotool([*linhas, ativa or ID_SEM_ATIVA])
        return janelas if janelas is not None else self._uma_a_uma()

    def _uma_a_uma(self) -> list[JanelaDoSistema]:
        ids = (_rodar(self._lancar, "kdotool", "search", "--class", ".") or "").split()
        ativa = (_rodar(self._lancar, "kdotool", "getactivewindow") or "").strip()
        janelas = []
        for janela_id in ids[:NA_LISTA_DO_MODELO]:
            if not id_de_janela(janela_id):
                continue
            titulo = (_rodar(self._lancar, "kdotool", "getwindowname", janela_id) or "").strip()
            classe = (
                _rodar(self._lancar, "kdotool", "getwindowclassname", janela_id) or ""
            ).strip()
            pid = _pid(_rodar(self._lancar, "kdotool", "getwindowpid", janela_id) or "")
            janelas.append(
                JanelaDoSistema(janela_id, titulo[:200], classe[:120], pid, janela_id == ativa)
            )
        return janelas

    def ativar(self, janela_id: str) -> bool:
        if not id_de_janela(janela_id):
            return False
        return _rodar(self._lancar, "kdotool", "windowactivate", janela_id) is not None

    def fechar(self, janela_id: str) -> bool:
        """`kdotool windowclose {uuid}` ("Close a window", no `--help` dele): o pedido do KWin."""
        if not id_de_janela(janela_id):
            return False
        return _rodar(self._lancar, "kdotool", "windowclose", janela_id) is not None


ID_SEM_ATIVA: Final = "{00000000-0000-0000-0000-000000000000}"
"""O lugar da ativa quando não há janela ativa: um id que nenhuma janela tem."""


def _inteiro(valor: object) -> int:
    return int(valor) if isinstance(valor, int | float) and not isinstance(valor, bool) else 0


def estado_do_kwin(bruto: str) -> EstadoDasJanelas | None:
    """A resposta da `CONSULTA_DO_KWIN` (a última linha, JSON) conferida campo a campo: id no
    formato do KWin, texto como texto, número como número. Fora disso, `None` — e quem chamou
    tenta a busca encadeada."""
    linhas = [linha for linha in bruto.splitlines() if linha.strip()]
    if not linhas:
        return None
    try:
        dados = json.loads(linhas[-1])
    except ValueError:
        return None
    if not isinstance(dados, dict) or not isinstance(dados.get("janelas"), list):
        return None
    telas = [t for t in dados.get("telas") or [] if isinstance(t, dict)]
    nomes = [str(t.get("nome", "")) for t in telas]
    if not all(re.fullmatch(_NOME_DE_MONITOR, n) for n in nomes):
        return None
    principal = nomes[0] if nomes else ""
    monitores = tuple(
        Monitor(
            n,
            n == principal,
            _inteiro(t.get("x")),
            _inteiro(t.get("y")),
            _inteiro(t.get("largura")),
            _inteiro(t.get("altura")),
        )
        for n, t in zip(nomes, telas, strict=True)
    )
    ativa = str(dados.get("ativa") or "")
    brutas: list[dict[str, Any]] = []
    for item in dados["janelas"][:LIMITE_DE_JANELAS]:
        if not isinstance(item, dict) or not id_de_janela(str(item.get("id", ""))):
            return None
        brutas.append(item)
    # A da frente em cada monitor: a de cima na pilha entre as que o dono pode ver ali (nesta área
    # de trabalho, não minimizadas, de app — painel e área de trabalho não contam).
    frente: dict[str, tuple[int, str]] = {}
    for item in brutas:
        tela = str(item.get("tela") or "")
        visivel = bool(item.get("nesta_mesa")) and not item.get("minimizada")
        classe = _dobrar(str(item.get("classe") or ""))
        if not (tela and visivel and item.get("normal") and classe not in DO_SISTEMA):
            continue
        pilha = _inteiro(item.get("pilha"))
        if tela not in frente or pilha > frente[tela][0]:
            frente[tela] = (pilha, str(item["id"]))
    na_frente = {janela_id for _, janela_id in frente.values()}
    janelas = tuple(
        JanelaDoSistema(
            str(item["id"]),
            str(item.get("titulo") or "")[:200],
            str(item.get("classe") or "")[:120],
            _pid(str(_inteiro(item.get("pid")))),
            str(item["id"]) == ativa,
            monitor=str(item.get("tela") or "")[:40],
            principal=bool(principal) and str(item.get("tela") or "") == principal,
            na_frente=str(item["id"]) in na_frente,
            minimizada=bool(item.get("minimizada")),
            visivel=bool(item.get("nesta_mesa")) and not item.get("minimizada"),
            normal=bool(item.get("normal")),
        )
        for item in brutas
    )
    tela_ativa = str(dados.get("tela_ativa") or "")
    return EstadoDasJanelas(
        janelas, monitores, tela_ativa if re.fullmatch(_NOME_DE_MONITOR, tela_ativa) else ""
    )


def _blocos_do_kdotool(linhas: list[str]) -> list[JanelaDoSistema] | None:
    """Os quatro blocos (ids, títulos, classes, PIDs) e a ativa no fim; `None` se desalinhou."""
    if (len(linhas) - 1) % 4:
        return None
    n = (len(linhas) - 1) // 4
    ids, titulos, classes, pids = (linhas[i * n : (i + 1) * n] for i in range(4))
    ativa = linhas[-1].strip()
    if not all(id_de_janela(i.strip()) for i in [*ids, ativa]):
        return None
    if not all(p.strip().isdigit() or p.strip() in ("", "null", "-1") for p in pids):
        return None
    return [
        JanelaDoSistema(i.strip(), t.strip()[:200], c.strip()[:120], _pid(p), i.strip() == ativa)
        for i, t, c, p in zip(ids, titulos, classes, pids, strict=True)
    ][:LIMITE_DE_JANELAS]


class JanelasPorWmctrl:
    """X11: `wmctrl -lxp` (id, mesa, PID, classe, título) e a ativa pelo `xprop`."""

    def __init__(self, lancar: Lancador = executar) -> None:
        self._lancar = lancar

    def listar(self) -> list[JanelaDoSistema]:
        bruto = _rodar(self._lancar, "wmctrl", "-lxp")
        if bruto is None:
            return []
        raiz = _rodar(self._lancar, "xprop", "-root", "_NET_ACTIVE_WINDOW") or ""
        achado = re.search(_HEXA, raiz.split("#", 1)[-1]) if "#" in raiz else None
        ativa = int(achado.group(1), 16) if achado else 0
        janelas = []
        for linha in bruto.splitlines()[:LIMITE_DE_JANELAS]:
            partes = linha.split(None, 5)
            if len(partes) < 5 or not partes[0].startswith("0x") or partes[1] == "-1":
                continue  # `-1` = área de trabalho/painel, não janela de app
            janela_id, pid, classe = partes[0], partes[2], partes[3]
            titulo = partes[5] if len(partes) > 5 else ""
            if titulo == "N/A":  # o wmctrl não leu o título (WM_NAME fora do UTF-8): desconhecido
                titulo = ""
            janelas.append(
                JanelaDoSistema(
                    janela_id,
                    titulo.strip()[:200],
                    classe.split(".")[-1][:120],
                    _pid(pid),
                    bool(ativa) and int(janela_id, 16) == ativa,
                )
            )
        return janelas

    def ativar(self, janela_id: str) -> bool:
        if not id_de_janela(janela_id):
            return False
        return _rodar(self._lancar, "wmctrl", "-i", "-a", janela_id) is not None

    def fechar(self, janela_id: str) -> bool:
        """`wmctrl -i -c`: o `_NET_CLOSE_WINDOW` do X11, o mesmo do X da janela."""
        if not id_de_janela(janela_id):
            return False
        return _rodar(self._lancar, "wmctrl", "-i", "-c", janela_id) is not None


def janelas_do_ambiente(
    ambiente: Mapping[str, str],
    lancar: Lancador = executar,
    tem: Callable[[str], bool] = instalado,
) -> Janelas | None:
    """O mesmo critério de `jarvis.entrada.foco`: no Wayland só o `kdotool` (KDE) vê as janelas
    dos outros; no X11, `kdotool` no KDE ou `wmctrl` + `xprop`. `None` = não há como ver."""
    kde = "KDE" in ambiente.get("XDG_CURRENT_DESKTOP", "").upper()
    if ambiente.get("WAYLAND_DISPLAY") or ambiente.get("XDG_SESSION_TYPE") == "wayland":
        return JanelasPorKdotool(lancar) if kde and tem("kdotool") else None
    if not ambiente.get("DISPLAY"):
        return None
    if kde and tem("kdotool"):
        return JanelasPorKdotool(lancar)
    if tem("wmctrl") and tem("xprop"):
        return JanelasPorWmctrl(lancar)
    return None


# --- o que as ferramentas window.* fazem com a porta -----------------------------------------
def de_app(janela: JanelaDoSistema) -> bool:
    return bool(janela.titulo) and janela.normal and _dobrar(janela.classe) not in DO_SISTEMA


@runtime_checkable
class LeEstado(Protocol):
    """A porta que lê tudo numa vez, com os monitores (o KWin, pela `CONSULTA_DO_KWIN`)."""

    def estado(self) -> EstadoDasJanelas | None: ...


def estado_de(janelas: Janelas) -> EstadoDasJanelas:
    """A leitura com monitores quando a porta a faz; senão a lista, sem monitor."""
    if isinstance(janelas, LeEstado):
        estado = janelas.estado()
        if estado is not None:
            return estado
    return EstadoDasJanelas(tuple(janelas.listar()))


def _janela_para_o_modelo(j: JanelaDoSistema) -> dict[str, Any]:
    dados: dict[str, Any] = {"id": j.id, "app": j.classe, "titulo": j.titulo[:100]}
    if j.monitor:
        dados |= {"monitor": j.monitor, "principal": j.principal}
    return dados


def listar_para_o_modelo(janelas: Janelas) -> dict[str, Any]:
    """As janelas de app, cada uma com o monitor dela (quando a leitura diz), se é a ativa (a do
    teclado) e se é a da frente no monitor dela; as da frente e a ativa primeiro."""
    estado = estado_de(janelas)
    lista = sorted(
        (j for j in estado.janelas if de_app(j)),
        key=lambda j: (not j.ativa, not j.na_frente, not j.principal, j.monitor),
    )[:NA_LISTA_DO_MODELO]
    resposta: dict[str, Any] = {
        "janelas": [
            _janela_para_o_modelo(j)
            | {"primeiro_plano": j.ativa}
            | ({"na_frente_do_monitor": j.na_frente} if j.monitor else {})
            | ({"minimizada": True} if j.minimizada else {})
            for j in lista
        ]
    }
    if estado.monitores:
        resposta["monitores"] = [
            {"monitor": m.nome, "principal": m.principal} for m in estado.monitores
        ]
    return resposta


def foco_para_o_modelo(janelas: Janelas) -> dict[str, Any]:
    """«Qual janela está em foco?» (dono, 2026-10-21): a **ativa** — a do teclado — com o monitor
    dela, e **em cada monitor a da frente**. Com dois monitores as duas perguntas têm respostas
    diferentes: o dono fala com o Jarvis (ou usa o outro monitor) e o Brave continua na frente do
    principal — é ele que o dono «está vendo» ali."""
    estado = estado_de(janelas)
    ativa = estado.ativa
    resposta: dict[str, Any] = {"foco": None}
    if ativa is None:
        resposta["sem_foco"] = (
            "nenhuma janela está ativa agora (tudo minimizado, ou a área de trabalho na frente)"
        )
    elif de_app(ativa):
        resposta["foco"] = _janela_para_o_modelo(ativa)
    else:  # o painel, a área de trabalho, o lançador: diz, sem fingir que é um app
        resposta["foco"] = {"app": ativa.classe, "titulo": ativa.titulo[:100], "do_sistema": True}
    if estado.monitores:
        resposta["monitores"] = [
            {
                "monitor": m.nome,
                "principal": m.principal,
                "do_teclado": m.nome == estado.monitor_ativo,
                "na_frente": (
                    _janela_para_o_modelo(frente)
                    if (frente := estado.da_frente(m.nome)) is not None
                    else None
                ),
            }
            for m in estado.monitores
        ]
    else:
        resposta["aviso"] = (
            "esta leitura não diz o monitor de cada janela (kdotool sem kwinscript, ou X11)"
        )
    return resposta


def focar(janelas: Janelas, app: str, janela_id: str = "") -> dict[str, Any]:
    """Põe em foco a janela `janela_id` (conferida na lista de agora) ou a do app pelo nome —
    escolhida pelo código, como em `desktop.achar_janela`. Já em foco, não mexe."""
    lista = [j for j in janelas.listar() if de_app(j)]
    if janela_id:
        alvo = next((j for j in lista if j.id == janela_id), None)
        if alvo is None:
            raise ValueError("essa janela não está mais aberta")
    else:
        escolhida = desktop.achar_janela(
            [{"id": j.id, "app": j.classe, "titulo": j.titulo} for j in lista], app
        )
        alvo = next(j for j in lista if j.id == escolhida["id"])
    if not alvo.ativa and not janelas.ativar(alvo.id):
        raise ComandoIndisponivel("o gerenciador de janelas não deixou focar")
    return {"app": alvo.classe, "titulo": alvo.titulo[:100], "janela_id": alvo.id}


# --- os processos ----------------------------------------------------------------------------
class Processos(Protocol):
    """O que se lê de um processo para ligá-lo ao que foi lançado. Nunca o ambiente dele (pode
    ter chave de API): só o pai, o executável e a linha de comando."""

    def pai(self, pid: int) -> int | None: ...

    def executavel(self, pid: int) -> str: ...

    def argumentos(self, pid: int) -> tuple[str, ...]: ...


@dataclass(frozen=True, slots=True)
class ProcessosDoProc:
    """Linux: o `/proc` (só processos do próprio usuário se deixam ler por inteiro)."""

    raiz: Path = Path("/proc")

    def pai(self, pid: int) -> int | None:
        try:
            for linha in (self.raiz / str(pid) / "status").read_text("utf-8").splitlines():
                if linha.startswith("PPid:"):
                    return int(linha.split()[1])
        except (OSError, ValueError, IndexError):
            return None
        return None

    def executavel(self, pid: int) -> str:
        try:
            return (self.raiz / str(pid) / "exe").readlink().name
        except OSError:
            try:
                return (self.raiz / str(pid) / "comm").read_text("utf-8").strip()
            except OSError:
                return ""

    def argumentos(self, pid: int) -> tuple[str, ...]:
        try:
            with (self.raiz / str(pid) / "cmdline").open("rb") as arquivo:
                bruto = arquivo.read(8192)
        except OSError:
            return ()
        return tuple(a.decode("utf-8", "replace") for a in bruto.split(b"\0") if a)


def descendente(pid: int | None, de: int | None, pai: Callable[[int], int | None]) -> bool:
    """`pid` é `de` ou um descendente dele (sobe pela cadeia de pais, até 32 níveis)."""
    if pid is None or de is None:
        return False
    atual: int | None = pid
    for _ in range(32):
        if atual is None or atual <= 1:
            return False
        if atual == de:
            return True
        atual = pai(atual)
    return False


def jogo_do_steam(pid: int | None, processos: Processos) -> str:
    """O `AppId` do `reaper` do Steam acima do processo (`reaper SteamLaunch AppId=480 -- …`)."""
    atual = pid
    for _ in range(32):
        if atual is None or atual <= 1:
            return ""
        argumentos = processos.argumentos(atual)
        if any(Path(a).name == "reaper" for a in argumentos[:2]):
            achado = next((m.group(1) for a in argumentos if (m := re.fullmatch(_APPID, a))), "")
            if achado:
                return achado
        atual = processos.pai(atual)
    return ""


# --- a evidência -----------------------------------------------------------------------------
def _dobrar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return " ".join(sem_acento.casefold().split())


def _palavra(nome: str, titulo: str) -> bool:
    """O nome inteiro no título («Spotify» em «Spotify Premium»), não pedaço de outra palavra."""
    return len(nome) >= 3 and re.search(rf"(?<!\w){re.escape(nome)}(?!\w)", titulo) is not None


@dataclass(frozen=True, slots=True)
class PistaDoApp:
    """O que o código sabe do app que abriu — nada vem do modelo."""

    nome: str
    nomes: tuple[str, ...]
    pid: int | None
    executavel: str = ""
    classe_do_desktop: str = ""
    """`StartupWMClass` do `.desktop`, quando há."""
    id_do_desktop: str = ""
    """O id do `.desktop` (`org.kde.dolphin`): é o `app_id` do app no Wayland."""
    jogo_do_steam: str = ""
    """O id do jogo, quando o app é um jogo aberto pelo Steam (`steam://rungameid/<id>`)."""

    @property
    def classes(self) -> frozenset[str]:
        """As classes que só este app teria. Num jogo do Steam, o `steam` é o lançador, não ele."""
        candidatas = {
            self.classe_do_desktop,
            self.id_do_desktop,
            self.id_do_desktop.rsplit(".", 1)[-1] if "." in self.id_do_desktop else "",
            "" if self.jogo_do_steam else self.executavel,
        }
        return frozenset(
            _dobrar(c) for c in candidatas if len(c) >= 3 and _dobrar(c) not in GENERICOS
        )

    @classmethod
    def do_app(
        cls,
        nome: str,
        nomes: Sequence[str],
        argv: Sequence[str],
        pid: int | None,
        *,
        arquivo: Path | None = None,
        id_do_desktop: str = "",
    ) -> PistaDoApp:
        jogo = next((m.group(1) for a in argv if (m := re.search(_JOGO_DO_STEAM, a))), "")
        if not jogo and "-applaunch" in argv[:-1]:
            seguinte = argv[list(argv).index("-applaunch") + 1]
            jogo = seguinte if seguinte.isdigit() else ""
        return cls(
            nome=nome,
            nomes=tuple(nomes),
            pid=pid,
            executavel=Path(argv[0]).name if argv else "",
            classe_do_desktop=_classe_do_desktop(arquivo),
            id_do_desktop=id_do_desktop,
            jogo_do_steam=jogo,
        )


def _classe_do_desktop(arquivo: Path | None) -> str:
    if arquivo is None:
        return ""
    try:
        for linha in arquivo.read_text(encoding="utf-8", errors="replace").splitlines():
            if linha.startswith("StartupWMClass="):
                return linha.split("=", 1)[1].strip()
    except OSError:
        return ""
    return ""


@dataclass(frozen=True, slots=True)
class Evidencia:
    janela: JanelaDoSistema
    pontos: int
    razoes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Leitura:
    """O que a lista de janelas diz agora sobre o app."""

    alvo: Evidencia | None = None
    """A janela do app, com evidência forte e sem empate."""
    duvida: tuple[Evidencia, ...] = ()
    """Candidatas fortes empatadas: o dono escolhe."""
    fracas: tuple[Evidencia, ...] = ()
    """Novas e com o nome no título, mas sem ligação com o lançado: não se focam por palpite."""
    conta_do_steam: bool = False
    """O Steam está pedindo a conta: é com o dono, e o Jarvis espera."""


PONTOS_FORTES: Final = 3
"""PID (3), jogo do Steam (3), ou classe/executável (2) com mais um sinal (nova, título)."""


def avaliar(
    janelas: Iterable[JanelaDoSistema],
    pista: PistaDoApp,
    antes: frozenset[str],
    *,
    processos: Processos | None = None,
    velhas_valem: bool = True,
) -> Leitura:
    """A janela do app, só com evidência (ADR-0037). Sem ela, nenhuma — e o Jarvis espera.

    `velhas_valem=False` nos primeiros segundos: lançar costuma abrir janela nova, e a janela que
    o app já tinha só é a resposta quando ele reaproveitou a instância aberta."""
    proc = processos if processos is not None else ProcessosDoProc()
    nomes = {_dobrar(n) for n in (pista.nome, *pista.nomes) if n}
    classes = pista.classes
    executavel = "" if pista.jogo_do_steam else _dobrar(pista.executavel)
    avaliadas: list[Evidencia] = []
    conta_do_steam = False
    for janela in janelas:
        classe, titulo = _dobrar(janela.classe), _dobrar(janela.titulo)
        nova = janela.id not in antes
        if classe in DO_SISTEMA:
            continue
        if pista.jogo_do_steam and classe == "steam":
            # O cliente do Steam (loja, biblioteca, atualização, conta) não é o jogo; a janela de
            # entrar na conta é do dono — não se foca nem se clica.
            conta_do_steam |= bool(re.search(_LOGIN_DO_STEAM, janela.titulo))
            continue
        if not nova and not velhas_valem:
            continue
        pontos, razoes = 0, []
        if pista.jogo_do_steam:
            # Tudo o que o Steam abre descende dele: o PID não distingue o jogo das janelas do
            # Steam. O que liga a janela ao jogo é o id dele.
            if classe == f"steam_app_{pista.jogo_do_steam}" or (
                jogo_do_steam(janela.pid, proc) == pista.jogo_do_steam
            ):
                pontos += 3
                razoes.append("jogo do Steam")
        elif descendente(janela.pid, pista.pid, proc.pai):
            pontos += 3
            razoes.append("pid")
        if classe and classe in classes:
            pontos += 2
            razoes.append("classe")
        if (
            "pid" not in razoes
            and executavel
            and executavel not in GENERICOS
            and janela.pid is not None
            and _dobrar(proc.executavel(janela.pid)) == executavel
        ):
            pontos += 2
            razoes.append("executável")
        if nova:
            pontos += 1
            razoes.append("nova")
        if titulo and any(_palavra(nome, titulo) for nome in nomes):
            pontos += 1
            razoes.append("título")
        if pontos:
            avaliadas.append(Evidencia(janela, pontos, tuple(razoes)))
    fortes = [e for e in avaliadas if e.pontos >= PONTOS_FORTES]
    fracas = tuple(
        e for e in avaliadas if e.pontos < PONTOS_FORTES and {"nova", "título"} <= set(e.razoes)
    )
    if not fortes:
        return Leitura(fracas=fracas, conta_do_steam=conta_do_steam)
    maximo = max(e.pontos for e in fortes)
    topo = tuple(e for e in fortes if e.pontos == maximo)
    if len(topo) > 1:
        return Leitura(duvida=topo, fracas=fracas, conta_do_steam=conta_do_steam)
    return Leitura(alvo=topo[0], fracas=fracas, conta_do_steam=conta_do_steam)
