"""Volume e microfone no Linux (F2-03): wpctl (PipeWire/WirePlumber) → pactl.

Sem shell, via ``jarvis.platform.linux.tools.run_tool`` (timeout, LC_ALL=C).
Saída inesperada ou código ≠ 0 levanta exceção; quem formata a mensagem ao
usuário é o system_ctrl. Porcentagens de escrita ficam em 0-100 (clamp).

- ``WpctlVolume``: ``wpctl get-volume @DEFAULT_AUDIO_SINK@`` → ``Volume: 0.40``
  (``[MUTED]`` opcional; acima de 1.00 é boost) → round(v × 100);
  ``set-volume <alvo> 0.40 --limit 1.0``; ``@DEFAULT_AUDIO_SOURCE@`` no microfone;
  ``set-mute <alvo> toggle``; passo ``2%+``/``2%-``. Sonda: ``wpctl status`` = 0 em 2 s.
- ``PactlVolume``: ``pactl get-sink-volume @DEFAULT_SINK@`` (primeiro ``NN%``);
  ``set-sink-volume @DEFAULT_SINK@ NN%``; ``get/set-source-volume @DEFAULT_SOURCE@``;
  ``set-sink-mute``/``set-source-mute ... toggle``. Sonda: ``pactl info`` = 0.
"""
from __future__ import annotations

import re

from ..common.base import BackendBase, Probe
from . import tools

_WPCTL_VOLUME = re.compile(r"Volume:\s*([0-9]+(?:\.[0-9]+)?)")
_PACTL_PERCENT = re.compile(r"(\d+)%")


def _clamp(pct) -> int:
    return max(0, min(100, int(pct)))


class _ToolVolume(BackendBase):
    name = ""
    tool = ""

    def __init__(self, ctx=None):
        self.ctx = ctx

    def _run(self, *args: str) -> str:
        r = tools.run_tool([self.tool, *args])
        if r is None:
            raise OSError(f"{self.tool} indisponível ou sem resposta")
        if r.returncode != 0:
            detalhe = (r.stderr or r.stdout or "").strip()
            raise OSError(f"{self.tool} {args[0]} falhou (código {r.returncode}) {detalhe}".strip())
        return r.stdout

    @classmethod
    def _probe_cmd(cls, *args: str, timeout: float = tools.DEFAULT_TIMEOUT) -> Probe:
        if tools.which(cls.tool) is None:
            return Probe(False, f"{cls.tool} ausente no PATH")
        r = tools.run_tool([cls.tool, *args], timeout=timeout)
        if r is None or r.returncode != 0:
            return Probe(False, f"{cls.tool} {' '.join(args)} falhou")
        return Probe(True)


class WpctlVolume(_ToolVolume):
    name = "linux.wpctl"
    tool = "wpctl"
    SINK = "@DEFAULT_AUDIO_SINK@"
    SOURCE = "@DEFAULT_AUDIO_SOURCE@"

    @classmethod
    def probe(cls, ctx) -> Probe:
        return cls._probe_cmd("status", timeout=2.0)

    def _get(self, alvo: str) -> int:
        saida = self._run("get-volume", alvo)
        m = _WPCTL_VOLUME.search(saida)
        if not m:
            raise ValueError(f"saída inesperada do wpctl: {saida.strip()[:80]!r}")
        return round(float(m.group(1)) * 100)

    def _set(self, alvo: str, pct) -> None:
        self._run("set-volume", alvo, f"{_clamp(pct) / 100:.2f}", "--limit", "1.0")

    def get_output(self) -> int:
        return self._get(self.SINK)

    def set_output(self, pct: int) -> None:
        self._set(self.SINK, pct)

    def get_input(self) -> int:
        return self._get(self.SOURCE)

    def set_input(self, pct: int) -> None:
        self._set(self.SOURCE, pct)

    def toggle_output_mute(self) -> None:
        self._run("set-mute", self.SINK, "toggle")

    def toggle_input_mute(self) -> None:
        self._run("set-mute", self.SOURCE, "toggle")

    def step_output(self, delta_pct: int) -> None:
        if not delta_pct:
            return
        sinal = "+" if delta_pct > 0 else "-"
        self._run("set-volume", self.SINK, f"{abs(int(delta_pct))}%{sinal}", "--limit", "1.0")


class PactlVolume(_ToolVolume):
    name = "linux.pactl"
    tool = "pactl"
    SINK = "@DEFAULT_SINK@"
    SOURCE = "@DEFAULT_SOURCE@"

    @classmethod
    def probe(cls, ctx) -> Probe:
        return cls._probe_cmd("info")

    def _get(self, comando: str, alvo: str) -> int:
        saida = self._run(comando, alvo)
        m = _PACTL_PERCENT.search(saida)
        if not m:
            raise ValueError(f"saída inesperada do pactl: {saida.strip()[:80]!r}")
        return int(m.group(1))

    def get_output(self) -> int:
        return self._get("get-sink-volume", self.SINK)

    def set_output(self, pct: int) -> None:
        self._run("set-sink-volume", self.SINK, f"{_clamp(pct)}%")

    def get_input(self) -> int:
        return self._get("get-source-volume", self.SOURCE)

    def set_input(self, pct: int) -> None:
        self._run("set-source-volume", self.SOURCE, f"{_clamp(pct)}%")

    def toggle_output_mute(self) -> None:
        self._run("set-sink-mute", self.SINK, "toggle")

    def toggle_input_mute(self) -> None:
        self._run("set-source-mute", self.SOURCE, "toggle")

    def step_output(self, delta_pct: int) -> None:
        """Sem --limit no pactl: calcula o absoluto e aplica o clamp 0-100."""
        if not delta_pct:
            return
        self.set_output(self.get_output() + int(delta_pct))
