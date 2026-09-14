"""Mídia no Linux (F2-08): MPRIS via D-Bus de sessão → playerctl.

- ``MprisMedia``: ``ListNames`` filtrando ``org.mpris.MediaPlayer2.*``; o player
  ativo é o primeiro (em ordem alfabética) com ``PlaybackStatus == "Playing"``,
  senão o primeiro ``Paused``, senão o primeiro da lista. Comandos em
  ``org.mpris.MediaPlayer2.Player`` (PlayPause/Stop/Next/Previous); título e
  artista de ``Metadata`` (``xesam:title``, ``xesam:artist[0]``). A sonda só exige
  o D-Bus de sessão: o player é procurado a cada comando (um player aberto depois
  do boot também vale).
- ``PlayerctlMedia``: ``playerctl play-pause|stop|next|previous`` e
  ``playerctl metadata --format`` (título, artista, player e status separados por tab).
- Sem player: ``CapabilityUnavailable`` com "nenhum player MPRIS" (o midia_ctrl
  responde "Nenhum player de mídia ativo, Senhor.").
- ``toggle_mute``/``volume_step`` delegam a ``Cap.VOLUME`` (passo = 2% por nível).
"""
from __future__ import annotations

import re
from typing import List, Optional

from ..capabilities import Cap
from ..common.base import BackendBase, Probe
from ..errors import CapabilityUnavailable
from . import dbus as _dbus
from . import tools

PREFIXO = "org.mpris.MediaPlayer2."
CAMINHO = "/org/mpris/MediaPlayer2"
IFACE_PLAYER = "org.mpris.MediaPlayer2.Player"
FORMATO_PLAYERCTL = "{{title}}\t{{artist}}\t{{playerName}}\t{{status}}"


def _sem_player() -> CapabilityUnavailable:
    return CapabilityUnavailable(Cap.MEDIA, [("org.mpris.MediaPlayer2.*", "nenhum player MPRIS")])


def _variante(valor):
    """(assinatura, valor) do jeepney → valor."""
    if isinstance(valor, tuple) and len(valor) == 2 and isinstance(valor[0], str):
        return valor[1]
    return valor


def _nome_do_player(bus_name: str) -> str:
    return bus_name[len(PREFIXO):].split(".")[0] if bus_name.startswith(PREFIXO) else bus_name


class _VolumeViaCap:
    def toggle_mute(self) -> None:
        from jarvis.platform import get

        get(Cap.VOLUME).toggle_output_mute()

    def volume_step(self, steps: int) -> None:
        from jarvis.platform import get

        get(Cap.VOLUME).step_output(int(steps) * 2)


class MprisMedia(_VolumeViaCap, BackendBase):
    name = "linux.mpris"

    def __init__(self, ctx=None):
        self.ctx = ctx

    @classmethod
    def probe(cls, ctx) -> Probe:
        try:
            _dbus.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                       "ListNames", timeout=_dbus.PROBE_TIMEOUT)
        except Exception as e:
            return Probe(False, f"sem D-Bus de sessão ({type(e).__name__})")
        return Probe(True)

    def _players(self) -> List[str]:
        (nomes,) = _dbus.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                              "ListNames", timeout=_dbus.PROBE_TIMEOUT)
        return sorted(n for n in nomes if n.startswith(PREFIXO))

    def _status(self, player: str) -> str:
        try:
            return str(_dbus.get_property(player, CAMINHO, IFACE_PLAYER, "PlaybackStatus", _dbus.PROBE_TIMEOUT))
        except Exception:
            return ""

    def _ativo(self) -> str:
        players = self._players()
        if not players:
            raise _sem_player()
        status = {p: self._status(p) for p in players}
        for procurado in ("Playing", "Paused"):
            for p in players:
                if status[p] == procurado:
                    return p
        return players[0]

    def _comando(self, metodo: str) -> None:
        _dbus.call(self._ativo(), CAMINHO, IFACE_PLAYER, metodo)

    def play_pause(self) -> None:
        self._comando("PlayPause")

    def stop(self) -> None:
        self._comando("Stop")

    def next(self) -> None:
        self._comando("Next")

    def previous(self) -> None:
        self._comando("Previous")

    next_track = next
    previous_track = previous

    def now_playing(self) -> dict:
        player = self._ativo()
        meta = _dbus.get_property(player, CAMINHO, IFACE_PLAYER, "Metadata") or {}
        titulo = _variante(meta.get("xesam:title")) or ""
        artistas = _variante(meta.get("xesam:artist")) or []
        if isinstance(artistas, str):
            artistas = [artistas]
        return {
            "title": str(titulo),
            "artist": str(artistas[0]) if artistas else "",
            "player": _nome_do_player(player),
            "status": self._status(player),
        }


class PlayerctlMedia(_VolumeViaCap, BackendBase):
    name = "linux.playerctl"

    def __init__(self, ctx=None):
        self.ctx = ctx

    @classmethod
    def probe(cls, ctx) -> Probe:
        if tools.which("playerctl"):
            return Probe(True)
        return Probe(False, "playerctl ausente no PATH")

    def _run(self, *args: str) -> str:
        r = tools.run_tool(["playerctl", *args])
        if r is None:
            raise OSError("playerctl indisponível ou sem resposta")
        if r.returncode != 0:
            if "no players" in (r.stderr or "").lower():
                raise _sem_player()
            raise OSError(f"playerctl {args[0]} falhou (código {r.returncode}) {(r.stderr or '').strip()}".strip())
        return r.stdout

    def play_pause(self) -> None:
        self._run("play-pause")

    def stop(self) -> None:
        self._run("stop")

    def next(self) -> None:
        self._run("next")

    def previous(self) -> None:
        self._run("previous")

    next_track = next
    previous_track = previous

    def now_playing(self) -> Optional[dict]:
        linha = self._run("metadata", "--format", FORMATO_PLAYERCTL).strip("\r\n")
        partes = re.split(r"\t|\\t", linha, maxsplit=3)
        partes += [""] * (4 - len(partes))
        titulo, artista, player, status = partes[:4]
        return {"title": titulo, "artist": artista, "player": player, "status": status}
