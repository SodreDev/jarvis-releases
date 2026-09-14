"""Session no Linux (F2-07): ociosidade, idioma e fuso.

Idle (cada backend devolve None quando não consegue ler e nunca levanta):
- ``ScreenSaverSession``: ``org.freedesktop.ScreenSaver`` ``/ScreenSaver``
  ``GetSessionIdleTime`` → u em SEGUNDOS (kscreenlocker). Um bug antigo devolvia
  ms: valor maior que o uptime vira /1000, com um aviso só.
- ``MutterSession``: ``org.gnome.Mutter.IdleMonitor``
  ``/org/gnome/Mutter/IdleMonitor/Core`` ``GetIdletime`` → t em MS.
- ``LogindSession``: ``org.freedesktop.login1``
  ``/org/freedesktop/login1/session/auto`` no barramento de SISTEMA, propriedades
  ``IdleHint`` (b) e ``IdleSinceHintMonotonic`` (t, µs): idle = CLOCK_MONOTONIC −
  since com IdleHint, senão 0.
- ``XdgSession``: sem idle (None). É o último elo das cadeias, para locale e fuso
  nunca ficarem indisponíveis.

Sonda das sessões D-Bus: a própria leitura (uma chamada com timeout de 1 s, sem
efeito colateral). jeepney só entra dentro das chamadas (via linux.dbus).
Locale: LC_ALL > LC_MESSAGES > LANG ("pt_BR.UTF-8" → "pt-BR"; "C"/"POSIX" não
contam) > "pt-BR". Fuso: TZ > link /etc/localtime (depois de "zoneinfo/") > "UTC".
"""
from __future__ import annotations

import os
import threading
import time
from typing import Mapping, Optional

from ..common.base import BackendBase, Probe
from . import dbus as _dbus

DEFAULT_LOCALE = "pt-BR"
DEFAULT_TIMEZONE = "UTC"
LOCALTIME_PATH = "/etc/localtime"

# Barramento de SISTEMA do logind: DBUS_SYSTEM_BUS_ADDRESS quando definida,
# senão o socket padrão. Testes apontam a variável para o barramento privado
# (fixture private_session_bus) ou para um socket inexistente.
SYSTEM_BUS_DEFAULT: Optional[str] = "unix:path=/run/dbus/system_bus_socket"

_aviso_ms_dado = False


def _uptime_seconds() -> float:
    try:
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    except (AttributeError, OSError):
        return time.monotonic()


def _system_bus_address() -> Optional[str]:
    return (os.environ.get("DBUS_SYSTEM_BUS_ADDRESS") or "").strip() or SYSTEM_BUS_DEFAULT


def _locale_de(valor: str) -> Optional[str]:
    base = valor.split(".", 1)[0].split("@", 1)[0].strip()
    if not base or base in ("C", "POSIX"):
        return None
    return base.replace("_", "-")


class XdgSession(BackendBase):
    name = "linux.xdg"

    def __init__(
        self,
        ctx=None,
        *,
        environ: Optional[Mapping[str, str]] = None,
        localtime_path: str = LOCALTIME_PATH,
    ):
        self.ctx = ctx
        self._environ = environ
        self._localtime_path = localtime_path

    def _env(self) -> Mapping[str, str]:
        return os.environ if self._environ is None else self._environ

    def idle_seconds(self) -> Optional[float]:
        return None

    def locale(self) -> str:
        env = self._env()
        for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
            loc = _locale_de(env.get(var) or "")
            if loc:
                return loc
        return DEFAULT_LOCALE

    def timezone_name(self) -> str:
        tz = (self._env().get("TZ") or "").strip().lstrip(":")
        if tz:
            return tz.split("zoneinfo/", 1)[1] if "zoneinfo/" in tz else tz
        try:
            alvo = os.readlink(self._localtime_path)
        except OSError:
            return DEFAULT_TIMEZONE
        if "zoneinfo/" in alvo:
            return alvo.split("zoneinfo/", 1)[1]
        return DEFAULT_TIMEZONE

    def close(self) -> None:
        pass


class _DBusIdleSession(XdgSession):
    """Base das sessões que leem a ociosidade por D-Bus: a sonda é a própria leitura."""

    @classmethod
    def probe(cls, ctx) -> Probe:
        inst = cls(ctx)
        try:
            ok = inst.idle_seconds() is not None
        finally:
            inst.close()
        if ok:
            return Probe(True)
        return Probe(False, f"{cls.name}: sem leitura de ociosidade no D-Bus")


class ScreenSaverSession(_DBusIdleSession):
    name = "linux.screensaver"

    def idle_seconds(self) -> Optional[float]:
        global _aviso_ms_dado
        try:
            (valor,) = _dbus.call(
                "org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver",
                "GetSessionIdleTime", timeout=_dbus.PROBE_TIMEOUT,
            )
        except Exception:
            return None
        segundos = float(valor)
        if segundos > _uptime_seconds():
            if not _aviso_ms_dado:
                _aviso_ms_dado = True
                print("[SESSION] ScreenSaver devolveu milissegundos (bug antigo); convertendo para segundos.")
            segundos /= 1000.0
        return segundos


class MutterSession(_DBusIdleSession):
    name = "linux.mutter"

    def idle_seconds(self) -> Optional[float]:
        try:
            (ms,) = _dbus.call(
                "org.gnome.Mutter.IdleMonitor", "/org/gnome/Mutter/IdleMonitor/Core",
                "org.gnome.Mutter.IdleMonitor", "GetIdletime", timeout=_dbus.PROBE_TIMEOUT,
            )
        except Exception:
            return None
        return int(ms) / 1000.0


class LogindSession(_DBusIdleSession):
    name = "linux.logind"

    _BUS = "org.freedesktop.login1"
    _PATH = "/org/freedesktop/login1/session/auto"
    _IFACE = "org.freedesktop.login1.Session"

    def __init__(self, ctx=None, **kwargs):
        super().__init__(ctx, **kwargs)
        self._router = None
        self._lock = threading.Lock()

    def _prop(self, nome: str):
        return _dbus.get_property(
            self._BUS, self._PATH, self._IFACE, nome, _dbus.PROBE_TIMEOUT, router=self._router
        )

    def idle_seconds(self) -> Optional[float]:
        with self._lock:
            try:
                if self._router is None:
                    endereco = _system_bus_address()
                    if endereco is None:
                        return None
                    self._router = _dbus.open_router(endereco, timeout=_dbus.PROBE_TIMEOUT)
                if not self._prop("IdleHint"):
                    return 0.0
                since_us = int(self._prop("IdleSinceHintMonotonic"))
            except Exception:
                self._close_locked()
                return None
        agora_us = time.clock_gettime_ns(time.CLOCK_MONOTONIC) // 1000
        return max(0.0, (agora_us - since_us) / 1_000_000)

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        if self._router is not None:
            _dbus.close_router(self._router)
            self._router = None
