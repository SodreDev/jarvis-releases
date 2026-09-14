"""K F2-00: features derivadas no Linux e invariante do win32 sem sondar nada.

No Linux, has_feature(nome) = nome ∈ features_for(ctx) OU derivado(nome):
global_hotkeys = has(HOTKEYS), tray = has(TRAY) e clipboard_monitor =
has(CLIPBOARD) e get(CLIPBOARD).can_watch. O "-nome" do JARVIS_FEATURES vence
o derivado. No win32 continua o estático (ALL_FEATURES) e nada é sondado.
"""
import shutil
import socket
import subprocess
import sys
import types

import pytest

import jarvis.platform as plat
from jarvis.platform import registry
from jarvis.platform.capabilities import Cap
from jarvis.platform.common.base import Probe
from jarvis.platform.detect import detect
from jarvis.platform.features import (
    ALL_FEATURES,
    DERIVED_FEATURES,
    effective_features,
    feature_enabled,
)


def _ctx(kind):
    mapa = {
        "win32": ("win32", {}),
        "linux-x11": ("linux", {"DISPLAY": ":0"}),
        "linux-wayland": ("linux", {"WAYLAND_DISPLAY": "wayland-0"}),
        "linux-headless": ("linux", {}),
        "unsupported": ("darwin", {}),
    }
    sysp, env = mapa[kind]
    return detect(sys_platform=sysp, environ=env, frozen=False)


class _Espiao:
    """has/get falsos que registram cada sondagem."""

    def __init__(self, disponiveis=(), can_watch=False):
        self.disponiveis = set(disponiveis)
        self.can_watch = can_watch
        self.chamadas = []

    def has(self, cap):
        self.chamadas.append(("has", cap))
        return cap in self.disponiveis

    def get(self, cap):
        self.chamadas.append(("get", cap))
        return types.SimpleNamespace(can_watch=self.can_watch)


def _enabled(kind, nome, espiao, environ=None):
    return feature_enabled(
        _ctx(kind), nome, has=espiao.has, get=espiao.get,
        environ={} if environ is None else environ,
    )


def test_derivadas_sao_as_tres_da_spec():
    assert DERIVED_FEATURES == frozenset({"global_hotkeys", "tray", "clipboard_monitor"})


@pytest.mark.parametrize("kind", ["linux-wayland", "linux-x11", "linux-headless"])
@pytest.mark.parametrize(
    "nome, disponiveis, can_watch, esperado",
    [
        ("tray", {Cap.TRAY}, False, True),
        ("tray", set(), False, False),
        ("clipboard_monitor", {Cap.CLIPBOARD}, True, True),
        ("clipboard_monitor", {Cap.CLIPBOARD}, False, False),
        ("clipboard_monitor", set(), True, False),
    ],
)
def test_derivada_segue_a_capacidade(kind, nome, disponiveis, can_watch, esperado):
    assert _enabled(kind, nome, _Espiao(disponiveis, can_watch)) is esperado


def test_global_hotkeys_no_wayland_segue_hotkeys():
    assert _enabled("linux-wayland", "global_hotkeys", _Espiao({Cap.HOTKEYS})) is True
    esp = _Espiao()
    assert _enabled("linux-wayland", "global_hotkeys", esp) is False
    assert esp.chamadas == [("has", Cap.HOTKEYS)]


def test_clipboard_sem_capacidade_nem_chama_get():
    esp = _Espiao(set(), can_watch=True)
    assert _enabled("linux-wayland", "clipboard_monitor", esp) is False
    assert ("get", Cap.CLIPBOARD) not in esp.chamadas


def test_estatico_ligado_nao_sonda():
    esp = _Espiao()
    assert _enabled("linux-x11", "global_hotkeys", esp) is True
    assert esp.chamadas == []


@pytest.mark.parametrize("nome", sorted(ALL_FEATURES - DERIVED_FEATURES))
def test_feature_nao_derivada_nunca_sonda(nome):
    esp = _Espiao(set(Cap), can_watch=True)
    assert _enabled("linux-wayland", nome, esp) is False
    assert esp.chamadas == []


def test_menos_nome_vence_derivado():
    esp = _Espiao({Cap.TRAY})
    assert _enabled("linux-wayland", "tray", esp, {"JARVIS_FEATURES": "-tray"}) is False
    assert esp.chamadas == []
    # o último item vale: "-tray,+tray" liga pelo estático
    assert _enabled("linux-wayland", "tray", _Espiao(), {"JARVIS_FEATURES": "-tray,+tray"}) is True


def test_mais_nome_liga_sem_sondar():
    esp = _Espiao()
    assert _enabled("linux-wayland", "tray", esp, {"JARVIS_FEATURES": "+tray"}) is True
    assert esp.chamadas == []


def test_nome_desconhecido_nao_sonda():
    esp = _Espiao(set(Cap))
    assert _enabled("linux-wayland", "banana", esp) is False
    assert esp.chamadas == []


def test_unsupported_nao_deriva():
    esp = _Espiao(set(Cap), can_watch=True)
    for nome in DERIVED_FEATURES:
        assert _enabled("unsupported", nome, esp) is False
    assert esp.chamadas == []


def test_derivacao_que_levanta_vira_false():
    def explode(cap):
        raise RuntimeError("sonda quebrou")

    assert feature_enabled(_ctx("linux-wayland"), "tray", has=explode, get=explode, environ={}) is False


def test_effective_features_no_linux():
    esp = _Espiao({Cap.HOTKEYS, Cap.TRAY})
    ctx = _ctx("linux-wayland")
    assert effective_features(ctx, has=esp.has, get=esp.get, environ={}) == {"global_hotkeys", "tray"}
    assert effective_features(
        ctx, has=esp.has, get=esp.get, environ={"JARVIS_FEATURES": "-tray"}
    ) == {"global_hotkeys"}


# ── Invariante do win32: ALL_FEATURES e nenhuma sonda ───────────────────────────

@pytest.mark.filterwarnings("ignore:JARVIS_FEATURES")
@pytest.mark.parametrize(
    "environ",
    [{}, {"JARVIS_FEATURES": "-tray,-clipboard_monitor"}, {"JARVIS_FEATURES": "+banana"}],
)
def test_win32_nunca_sonda(environ):
    esp = _Espiao(set(Cap), can_watch=True)
    ctx = _ctx("win32")
    for nome in sorted(ALL_FEATURES | {"banana"}):
        feature_enabled(ctx, nome, has=esp.has, get=esp.get, environ=environ)
    effective_features(ctx, has=esp.has, get=esp.get, environ=environ)
    assert esp.chamadas == []


def test_win32_sem_override_e_all():
    esp = _Espiao()
    ctx = _ctx("win32")
    assert all(feature_enabled(ctx, n, has=esp.has, get=esp.get, environ={}) for n in ALL_FEATURES)
    assert effective_features(ctx, has=esp.has, get=esp.get, environ={}) == ALL_FEATURES
    assert esp.chamadas == []


# ── Pela fachada jarvis.platform ────────────────────────────────────────────────

@pytest.fixture
def fachada(monkeypatch):
    """Fixa o contexto da fachada e restaura REGISTRY, cache e módulos falsos."""
    salvo = dict(registry.REGISTRY)
    monkeypatch.delenv("JARVIS_FEATURES", raising=False)

    def _usar(kind):
        plat._reset_for_tests(_ctx(kind))

    yield _usar
    registry.REGISTRY.clear()
    registry.REGISTRY.update(salvo)
    plat._reset_for_tests(None)
    for nome in [m for m in sys.modules if m.startswith("fake_plat_f2")]:
        sys.modules.pop(nome, None)


def _backend(nome_backend, **attrs):
    class _B:
        name = nome_backend

        @classmethod
        def probe(cls, ctx):
            return Probe(True)

        def __init__(self, ctx):
            self.ctx = ctx

    for k, v in attrs.items():
        setattr(_B, k, v)
    return _B


def _instalar_modulo(nome, **attrs):
    mod = types.ModuleType(nome)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[nome] = mod


def test_has_feature_win32_all_sem_sondar_nada(fachada, monkeypatch):
    fachada("win32")
    chamadas = []

    def espiao(nome):
        def _f(*args, **kwargs):
            chamadas.append(nome)
            raise AssertionError(f"win32 sondou: {nome}")
        return _f

    monkeypatch.setattr(registry, "resolve", espiao("registry.resolve"))
    monkeypatch.setattr(registry, "has", espiao("registry.has"))
    monkeypatch.setattr(registry, "_build", espiao("registry._build"))
    monkeypatch.setattr(subprocess, "Popen", espiao("subprocess.Popen"))
    monkeypatch.setattr(shutil, "which", espiao("shutil.which"))
    monkeypatch.setattr(socket, "socket", espiao("socket.socket"))
    antes = set(sys.modules)

    assert all(plat.has_feature(nome) for nome in ALL_FEATURES)
    assert plat.has_feature("banana") is False

    assert chamadas == []
    assert not [m for m in set(sys.modules) - antes if m.split(".")[0] == "jeepney"]


def test_has_feature_linux_deriva_do_registro_e_refresh_limpa(fachada):
    fachada("linux-wayland")
    _instalar_modulo("fake_plat_f2tray", Tray=_backend("tray-falso"))
    registry.REGISTRY[Cap.TRAY] = {"linux-*": ("fake_plat_f2tray:Tray",)}
    assert plat.has_feature("tray") is True

    registry.REGISTRY[Cap.TRAY] = {}
    assert plat.has_feature("tray") is True  # só o cache do registro segura o valor
    registry.refresh(Cap.TRAY)
    assert plat.has_feature("tray") is False


def test_has_feature_linux_clipboard_monitor_usa_can_watch(fachada):
    fachada("linux-x11")
    _instalar_modulo(
        "fake_plat_f2clip",
        Assiste=_backend("clip-assiste", can_watch=True),
        NaoAssiste=_backend("clip-sem-watch", can_watch=False),
    )
    registry.REGISTRY[Cap.CLIPBOARD] = {"linux-x11": ("fake_plat_f2clip:NaoAssiste",)}
    assert plat.has_feature("clipboard_monitor") is False

    registry.REGISTRY[Cap.CLIPBOARD] = {"linux-x11": ("fake_plat_f2clip:Assiste",)}
    registry.refresh(Cap.CLIPBOARD)
    assert plat.has_feature("clipboard_monitor") is True


def test_report_lista_cadeias_e_features_efetivas(fachada):
    fachada("linux-x11")
    _instalar_modulo("fake_plat_f2rep", B=_backend("rep"))
    registry.REGISTRY.clear()
    registry.REGISTRY[Cap.PATHS] = {"linux-x11": ("fake_plat_f2rep:Missing", "fake_plat_f2rep:B")}
    registry.REGISTRY[Cap.TRAY] = {"linux-*": ("fake_plat_f2rep:B",)}

    rep = plat.report()

    paths = rep["capabilities"]["paths"]
    assert paths["chain"] == ["fake_plat_f2rep:Missing", "fake_plat_f2rep:B"]
    assert paths["backend"] == "rep"
    assert rep["capabilities"]["tray"]["chain"] == ["fake_plat_f2rep:B"]
    assert rep["capabilities"]["hotkeys"] == {"backend": None, "chain": [], "tried": []}
    assert {"global_hotkeys", "tray"} <= set(rep["features"])
    assert "clipboard_monitor" not in rep["features"]
