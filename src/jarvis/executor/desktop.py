"""Mídia, janelas, área de transferência e notificação do desktop — por `comandos.py`.

Cada função monta o `argv` inteiro a partir de **argumentos tipados** (enum, id de janela que veio
da lista real, texto que vai por `stdin` ou depois de `--`): o modelo nunca escolhe programa nem
flag. O que a área de transferência devolve passa pela redação de segredos antes de chegar ao
modelo. Fechar janela e encerrar app moram em `fechar.py` (ADR-0042), com o alvo resolvido pelo
código e as proteções de processo.

**Não verificado ao vivo** (só o falso nos testes): MPRIS por `gdbus`/`playerctl` e `wmctrl` no
desktop do dono. `wmctrl` só enxerga janelas X11/XWayland: o que for Wayland nativo (Qt/KDE) pode
não aparecer — a lista diz "nenhuma" em vez de inventar.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Mapping
from typing import Any, Final

from jarvis.executor.comandos import ComandoIndisponivel, Lancador
from jarvis.memoryd.importacao import redigir

ACOES_DE_MIDIA: Final = {
    "tocar": "Play",
    "pausar": "Pause",
    "alternar": "PlayPause",
    "proxima": "Next",
    "anterior": "Previous",
    "parar": "Stop",
}
PLAYERCTL: Final = {
    "tocar": "play",
    "pausar": "pause",
    "alternar": "play-pause",
    "proxima": "next",
    "anterior": "previous",
    "parar": "stop",
}
PREFIXO_MPRIS: Final = "org.mpris.MediaPlayer2."
METODO_MPRIS: Final = "org.mpris.MediaPlayer2.Player."
LIMITE_DA_AREA: Final = 4000
LIMITE_DE_ESCRITA: Final = 20_000


# --- mídia (MPRIS) --------------------
def _players(lancar: Lancador) -> list[str]:
    saida = lancar(
        ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus", "--object-path",
         "/org/freedesktop/DBus", "--method", "org.freedesktop.DBus.ListNames"],
        3.0,
        None,
    )  # fmt: skip
    return sorted(set(re.findall(r"'(org\.mpris\.MediaPlayer2\.[\w.\-]+)'", saida.saida)))


def _propriedade(lancar: Lancador, player: str, nome: str) -> str:
    return lancar(
        ["gdbus", "call", "--session", "--dest", player, "--object-path", "/org/mpris/MediaPlayer2",
         "--method", "org.freedesktop.DBus.Properties.Get", "org.mpris.MediaPlayer2.Player", nome],
        3.0,
        None,
    ).saida  # fmt: skip


def _escolher(lancar: Lancador, players: list[str], filtro: str) -> str:
    if filtro:
        alvo = _sem_acento(filtro)
        achados = [p for p in players if alvo in _sem_acento(p.removeprefix(PREFIXO_MPRIS))]
        if not achados:
            raise ValueError(
                f"nenhum player de mídia chamado {filtro!r}: abertos agora: {_nomes(players)}"
            )
        players = achados
    tocando = [p for p in players if "Playing" in _propriedade(lancar, p, "PlaybackStatus")]
    return (tocando or players)[0]


def _nomes(players: list[str]) -> str:
    return ", ".join(p.removeprefix(PREFIXO_MPRIS) for p in players) or "nenhum"


def controlar_midia(lancar: Lancador, acao: str, player: str = "") -> dict[str, Any]:
    if acao not in ACOES_DE_MIDIA:
        raise ValueError(f"ação {acao!r} não existe: {', '.join(ACOES_DE_MIDIA)}")
    try:
        saida = lancar(
            [
                "playerctl",
                *([f"--player={_nome_seguro(player)}"] if player else []),
                PLAYERCTL[acao],
            ],
            3.0,
            None,
        )
        if saida.ok:
            return {"acao": acao, "via": "playerctl"}
    except ComandoIndisponivel:
        pass
    players = _players(lancar)
    if not players:
        raise ComandoIndisponivel("não há nenhum player de mídia aberto")
    escolhido = _escolher(lancar, players, player)
    lancar(
        ["gdbus", "call", "--session", "--dest", escolhido, "--object-path",
         "/org/mpris/MediaPlayer2", "--method", METODO_MPRIS + ACOES_DE_MIDIA[acao]],
        3.0,
        None,
    )  # fmt: skip
    return {"acao": acao, "player": escolhido.removeprefix(PREFIXO_MPRIS), "via": "mpris"}


def estado_da_midia(lancar: Lancador) -> dict[str, Any]:
    players = _players(lancar)
    saida: list[dict[str, str]] = []
    for player in players:
        estado = re.search(
            r"'(Playing|Paused|Stopped)'", _propriedade(lancar, player, "PlaybackStatus")
        )
        meta = _propriedade(lancar, player, "Metadata")
        titulo = re.search(r"'xesam:title':\s*<'((?:[^'\\]|\\.)*)'>", meta)
        artista = re.search(r"'xesam:artist':\s*<\[?'((?:[^'\\]|\\.)*)'", meta)
        saida.append(
            {
                "player": player.removeprefix(PREFIXO_MPRIS),
                "estado": estado.group(1) if estado else "desconhecido",
                "titulo": titulo.group(1)[:120] if titulo else "",
                "artista": artista.group(1)[:80] if artista else "",
            }
        )
    return {"players": saida, "observacao": "" if saida else "nenhum player de mídia aberto"}


def _nome_seguro(nome: str) -> str:
    if not re.fullmatch(r"[\w.\-]{1,40}", nome):
        raise ValueError("nome de player inválido (letras, números, ponto e hífen)")
    return nome


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    ).casefold()


# --- janelas (wmctrl) --------------------
def listar_janelas(lancar: Lancador) -> list[dict[str, str]]:
    saida = lancar(["wmctrl", "-lx"], 3.0, None)
    janelas: list[dict[str, str]] = []
    for linha in saida.saida.splitlines():
        partes = linha.split(None, 4)
        if len(partes) < 4 or not partes[0].startswith("0x") or partes[1] == "-1":
            continue  # `-1` = área de trabalho/painel, não janela de app
        classe = partes[2].split(".")[-1]
        janelas.append(
            {"id": partes[0], "app": classe, "titulo": (partes[4] if len(partes) > 4 else "")[:100]}
        )
    return janelas


def achar_janela(janelas: list[dict[str, str]], app: str) -> dict[str, str]:
    """A janela do app pedido, escolhida **pelo código** na lista real. Ambígua → erro com nomes."""
    alvo = _sem_acento(app).strip()
    achadas = [
        j for j in janelas if alvo in _sem_acento(j["app"]) or alvo in _sem_acento(j["titulo"])
    ]
    if not achadas:
        raise ValueError(f"nenhuma janela de {app!r} aberta agora")
    exatas = [j for j in achadas if _sem_acento(j["app"]) == alvo]
    achadas = exatas or achadas
    if len(achadas) > 1 and len({j["app"] for j in achadas}) > 1:
        raise ValueError(
            "mais de um app casa: "
            + ", ".join(sorted({j["app"] for j in achadas}))
            + ". Diga qual."
        )
    return achadas[0]


def focar(lancar: Lancador, app: str) -> dict[str, Any]:
    janela = achar_janela(listar_janelas(lancar), app)
    if not lancar(["wmctrl", "-i", "-a", janela["id"]], 3.0, None).ok:
        raise ComandoIndisponivel("o gerenciador de janelas não deixou focar")
    return {"app": janela["app"], "titulo": janela["titulo"]}


# --- área de transferência --------------------
def _wayland(ambiente: Mapping[str, str] | None) -> bool:
    return bool((ambiente if ambiente is not None else os.environ).get("WAYLAND_DISPLAY"))


def ler_area(lancar: Lancador, ambiente: Mapping[str, str] | None = None) -> str:
    argv = (
        ["wl-paste", "--no-newline", "--type", "text"]
        if _wayland(ambiente)
        else ["xclip", "-selection", "clipboard", "-o"]
    )
    saida = lancar(argv, 3.0, None)
    return saida.saida if saida.ok else ""


def texto_da_area(lancar: Lancador, ambiente: Mapping[str, str] | None = None) -> dict[str, Any]:
    """O texto da área de transferência, **sem segredo** e curto: ela costuma ter senha."""
    bruto = ler_area(lancar, ambiente)
    redacao = redigir(bruto[: LIMITE_DA_AREA * 4])
    texto = redacao.texto[:LIMITE_DA_AREA]
    return {
        "texto": texto,
        "vazia": not bruto.strip(),
        "truncado": len(redacao.texto) > LIMITE_DA_AREA,
        "segredos_ocultados": sum(redacao.achados.values()),
    }


def escrever_area(
    lancar: Lancador, texto: str, ambiente: Mapping[str, str] | None = None
) -> dict[str, Any]:
    if len(texto) > LIMITE_DE_ESCRITA:
        raise ValueError(
            f"texto grande demais para a área de transferência (máx. {LIMITE_DE_ESCRITA})"
        )
    argv = ["wl-copy"] if _wayland(ambiente) else ["xclip", "-selection", "clipboard"]
    if not lancar(argv, 3.0, texto).ok:
        raise ComandoIndisponivel("não consegui escrever na área de transferência")
    return {"caracteres": len(texto)}


# --- notificação do desktop --------------------
def notificar(lancar: Lancador, titulo: str, texto: str) -> dict[str, Any]:
    """`notify-send` com `--` antes do texto: título e corpo nunca viram opção do programa."""
    argv = [
        "notify-send",
        "--app-name=Jarvis",
        "--expire-time=8000",
        "--",
        titulo[:80],
        texto[:300],
    ]
    if not lancar(argv, 3.0, None).ok:
        raise ComandoIndisponivel("o desktop não aceitou a notificação")
    return {"titulo": titulo[:80]}
