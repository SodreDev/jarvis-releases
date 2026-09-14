"""K F2-03: adapters de volume, call sites do system_ctrl e o REGISTRY.

- Windows (W1): descoberta COM literal (mesmos resultados e erros do oráculo);
  system_ctrl com PycawVolume = oráculo (clamp, int(), mensagens); mute e passo
  pelo IAudioEndpointVolume falso.
- Linux: wpctl/pactl FALSOS (fake_tools): microfone, clamp, código ≠ 0, saída
  inesperada, sonda, passo do pactl com clamp.
- REGISTRY: cadeias; sem ferramentas → Unavailable e o system_ctrl responde com
  uma frase curta. Nunca pycaw nem o PipeWire de verdade.
"""
import sys
import types

import pytest

from jarvis.platform import registry
from jarvis.platform.capabilities import Cap
from jarvis.platform.common.unavailable import Unavailable
from jarvis.platform.detect import detect
from jarvis.platform.windows.volume import PycawVolume, _get_audio_volume, _get_mic_volume
from tests.golden.legacy_31bc0ce import (
    legacy_discover_audio_volume_interface,
    legacy_discover_mic_volume_interface,
    legacy_get_mic_volume,
    legacy_get_volume,
    legacy_set_mic_volume,
    legacy_set_volume,
)

WIN32 = detect(sys_platform="win32", environ={}, frozen=False)
WAYLAND = detect(sys_platform="linux", environ={"WAYLAND_DISPLAY": "w"}, frozen=False)
HEADLESS = detect(sys_platform="linux", environ={}, frozen=False)

linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="ferramentas falsas são scripts bash")


def _path_so(tmp_path, *pastas):
    """PATH só com as pastas dadas e um bash (shebang das ferramentas falsas),
    sem o /usr/bin do host: nunca acha o wpctl/pactl de verdade."""
    import os
    import shutil

    so_bash = tmp_path / "so_bash"
    so_bash.mkdir(exist_ok=True)
    if not (so_bash / "bash").exists():
        (so_bash / "bash").symlink_to(shutil.which("bash"))
    return os.pathsep.join([*(str(p) for p in pastas), str(so_bash)])


@pytest.fixture(autouse=True)
def _limpo():
    from jarvis.platform.linux import tools

    registry._clear_all()
    tools.clear_which_cache()
    yield
    registry._clear_all()
    tools.clear_which_cache()


class _Vol:
    """IAudioEndpointVolume falso."""

    def __init__(self, scalar=0.5):
        self.scalar = scalar
        self.set_calls = []
        self.mute = False
        self.passos = []

    def SetMasterVolumeLevelScalar(self, valor, _reservado):
        self.set_calls.append(valor)
        self.scalar = valor

    def GetMasterVolumeLevelScalar(self):
        return self.scalar

    def GetMute(self):
        return self.mute

    def SetMute(self, valor, _reservado):
        self.mute = valor

    def VolumeStepUp(self, _reservado):
        self.passos.append("up")

    def VolumeStepDown(self, _reservado):
        self.passos.append("down")


def _com_env(*, speakers=None, mic=None, mic_is_none=False):
    class _Iface:
        pass

    class _Dev:
        def Activate(self, _iid, _clsctx, _reservado):
            return _Iface()

    class _AudioUtilities:
        def GetSpeakers(self):
            return speakers if speakers is not None else _Dev()

        def GetMicrophone(self):
            if mic_is_none:
                return None
            return mic if mic is not None else _Dev()

    class _IAudioEndpointVolume:
        _iid_ = "IID_IAudioEndpointVolume"

    return dict(
        audio_utilities=_AudioUtilities(),
        iaudio_endpoint_volume=_IAudioEndpointVolume(),
        comtypes_mod=types.SimpleNamespace(CoInitialize=lambda: None),
        cast_fn=lambda interface, _tipo: interface,
        pointer_fn=lambda t: t,
        clsctx_all=1,
    )


def _resultado(fn, **kw):
    try:
        v = fn(**kw)
        return ("ok", type(v).__name__ if not isinstance(v, str) else v)
    except Exception as e:  # noqa: BLE001 — comparar o erro com o oráculo
        return ("erro", type(e).__name__, str(e))


# ── Windows: descoberta COM literal ─────────────────────────────────────────────

class _Wrapper:
    def __init__(self):
        class _Real:
            def Activate(self, *_a):
                return "iface"
        self._dev = _Real()


class _Inutil:
    pass


@pytest.mark.parametrize("env", [
    dict(), dict(speakers=_Wrapper()), dict(speakers=_Inutil()),
], ids=["direto", "wrapper_dev", "incompativel"])
def test_descoberta_saida_igual_ao_legado(env):
    novo = _resultado(lambda: _get_audio_volume(_com_env(**env)))
    velho = _resultado(lambda: legacy_discover_audio_volume_interface(**_com_env(**env)))
    assert novo == velho


@pytest.mark.parametrize("env", [
    dict(), dict(mic=_Wrapper()), dict(mic=_Inutil()), dict(mic_is_none=True),
], ids=["direto", "wrapper_dev", "incompativel", "sem_microfone"])
def test_descoberta_mic_igual_ao_legado(env):
    novo = _resultado(lambda: _get_mic_volume(_com_env(**env)))
    velho = _resultado(lambda: legacy_discover_mic_volume_interface(**_com_env(**env)))
    assert novo == velho


# ── Windows: call sites do system_ctrl ──────────────────────────────────────────

@pytest.fixture
def sc_windows(monkeypatch):
    import jarvis.platform as plat
    from comandos import system_ctrl

    def usar(get_audio=None, get_mic=None):
        monkeypatch.setattr(plat, "get", lambda cap: PycawVolume(WIN32, get_audio_fn=get_audio, get_mic_fn=get_mic))
        return system_ctrl

    return usar


def _boom():
    raise RuntimeError("sem dispositivo")


@pytest.mark.parametrize("nivel", [150, -20, 42, 29])
def test_set_volume_e_mic_iguais_ao_legado(sc_windows, nivel):
    novo, velho = _Vol(), _Vol()
    sc = sc_windows(get_audio=lambda: novo, get_mic=lambda: novo)
    assert sc.set_volume(nivel) == legacy_set_volume(lambda: velho, nivel)
    assert sc.set_mic_volume(nivel) == legacy_set_mic_volume(lambda: velho, nivel)
    assert novo.set_calls == velho.set_calls


@pytest.mark.parametrize("scalar", [0.73, 0.29, 1.0, 0.0])
def test_get_volume_e_mic_iguais_ao_legado(sc_windows, scalar):
    sc = sc_windows(get_audio=lambda: _Vol(scalar), get_mic=lambda: _Vol(scalar))
    assert sc.get_volume() == legacy_get_volume(lambda: _Vol(scalar))
    assert sc.get_mic_volume() == legacy_get_mic_volume(lambda: _Vol(scalar))


def test_erros_iguais_ao_legado(sc_windows):
    sc = sc_windows(get_audio=_boom, get_mic=_boom)
    assert sc.set_volume(50) == legacy_set_volume(_boom, 50)
    assert sc.get_volume() == legacy_get_volume(_boom)
    assert sc.set_mic_volume(50) == legacy_set_mic_volume(_boom, 50)
    assert sc.get_mic_volume() == legacy_get_mic_volume(_boom)


def test_sem_backend_frase_curta(monkeypatch):
    import jarvis.platform as plat
    from comandos import system_ctrl as sc

    indisponivel = Unavailable(Cap.VOLUME, [("jarvis.platform.linux.volume:WpctlVolume", "wpctl ausente no PATH")])
    monkeypatch.setattr(plat, "get", lambda cap: indisponivel)
    for resposta in (sc.set_volume(30), sc.get_volume(), sc.set_mic_volume(80), sc.get_mic_volume()):
        assert resposta.startswith("Não foi possível")
        assert "nenhum controle de volume disponível nesta sessão" in resposta
        assert "jarvis.platform" not in resposta


def test_windows_mute_e_passo():
    vol = _Vol()
    v = PycawVolume(WIN32, get_audio_fn=lambda: vol, get_mic_fn=lambda: vol)
    v.toggle_output_mute()
    assert vol.mute is True
    v.toggle_input_mute()
    assert vol.mute is False
    v.step_output(4)
    v.step_output(-2)
    v.step_output(1)
    v.step_output(0)
    assert vol.passos == ["up", "up", "down", "up"]


def test_system_ctrl_sem_pycaw_nem_descoberta_com():
    import ast
    from pathlib import Path

    fonte = (Path(__file__).resolve().parents[3] / "comandos" / "system_ctrl.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(fonte)
    defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert not {"_get_audio_volume", "_get_mic_volume"} & defs
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("pycaw")]


@pytest.mark.parametrize("scalar, set_esperado, imprime", [(0.5, [1.0], True), (0.985, [1.0], True), (0.995, [], False)])
def test_garantir_mic_maximo_igual_ao_windows(sc_windows, capsys, scalar, set_esperado, imprime):
    vol = _Vol(scalar)
    sc = sc_windows(get_mic=lambda: vol)
    sc.garantir_mic_maximo()
    assert vol.set_calls == set_esperado
    assert ("restaurado para 100%" in capsys.readouterr().out) is imprime


# ── Linux: wpctl falso ──────────────────────────────────────────────────────────

@linux
def test_wpctl_microfone_saida_e_mute(fake_tools):
    from jarvis.platform.linux.volume import WpctlVolume

    calls = fake_tools({"wpctl": 'case "$*" in *SOURCE*get*|get*SOURCE*) echo "Volume: 0.55";; get*) echo "Volume: 0.10 [MUTED]";; esac'})
    w = WpctlVolume(WAYLAND)
    assert w.get_input() == 55
    assert w.get_output() == 10
    w.toggle_input_mute()
    assert "set-mute @DEFAULT_AUDIO_SOURCE@ toggle" in calls["wpctl"].read_text()


@linux
@pytest.mark.parametrize("pct, esperado", [(150, "1.00"), (-5, "0.00"), (7, "0.07")])
def test_wpctl_set_com_clamp(fake_tools, pct, esperado):
    from jarvis.platform.linux.volume import WpctlVolume

    calls = fake_tools({"wpctl": "true"})
    WpctlVolume(WAYLAND).set_output(pct)
    assert calls["wpctl"].read_text().splitlines() == [f"set-volume @DEFAULT_AUDIO_SINK@ {esperado} --limit 1.0"]


@linux
def test_wpctl_codigo_diferente_de_zero_levanta(fake_tools):
    from jarvis.platform.linux.volume import WpctlVolume

    fake_tools({"wpctl": 'echo "Could not connect to PipeWire" >&2; exit 1'})
    with pytest.raises(OSError, match="Could not connect to PipeWire"):
        WpctlVolume(WAYLAND).get_output()
    with pytest.raises(OSError):
        WpctlVolume(WAYLAND).set_input(40)


@linux
def test_wpctl_sonda(fake_tools, monkeypatch, tmp_path):
    from jarvis.platform.linux import tools
    from jarvis.platform.linux.volume import WpctlVolume

    fake_tools({"wpctl": 'case "$1" in status) exit 0;; esac; exit 3'})
    monkeypatch.setenv("PATH", _path_so(tmp_path, tmp_path / "fake_tools_bin"))
    assert WpctlVolume.probe(WAYLAND).ok

    fake_tools({"wpctl": "exit 1"})
    tools.clear_which_cache()
    assert WpctlVolume.probe(WAYLAND).ok is False

    vazio = tmp_path / "vazio"
    vazio.mkdir()
    monkeypatch.setenv("PATH", str(vazio))
    tools.clear_which_cache()
    p = WpctlVolume.probe(WAYLAND)
    assert p.ok is False and "ausente" in p.reason


# ── Linux: pactl falso ──────────────────────────────────────────────────────────

@linux
def test_pactl_microfone_mute_e_passo_com_clamp(fake_tools):
    from jarvis.platform.linux.volume import PactlVolume

    calls = fake_tools({"pactl": (
        'case "$1" in get-sink-volume) '
        'echo "Volume: front-left: 62259 /  95% / -1.34 dB,   front-right: 62259 /  95% / -1.34 dB";; '
        'esac'
    )})
    p = PactlVolume(WAYLAND)
    p.set_input(80)
    p.toggle_input_mute()
    p.step_output(10)
    p.step_output(0)
    linhas = calls["pactl"].read_text().splitlines()
    assert linhas == [
        "set-source-volume @DEFAULT_SOURCE@ 80%",
        "set-source-mute @DEFAULT_SOURCE@ toggle",
        "get-sink-volume @DEFAULT_SINK@",
        "set-sink-volume @DEFAULT_SINK@ 100%",
    ]


@linux
def test_pactl_saida_inesperada_levanta(fake_tools):
    from jarvis.platform.linux.volume import PactlVolume

    fake_tools({"pactl": 'echo "Connection failure: Connection refused"'})
    with pytest.raises(ValueError, match="saída inesperada do pactl"):
        PactlVolume(WAYLAND).get_input()


# ── REGISTRY ─────────────────────────────────────────────────────────────────────

def test_cadeias_por_kind():
    assert registry._chain_for(Cap.VOLUME, "win32") == ("jarvis.platform.windows.volume:PycawVolume",)
    cadeia = ("jarvis.platform.linux.volume:WpctlVolume", "jarvis.platform.linux.volume:PactlVolume")
    assert registry._chain_for(Cap.VOLUME, "linux-wayland") == cadeia
    assert registry._chain_for(Cap.VOLUME, "linux-headless") == cadeia


def test_registro_win32_sem_importar_pycaw():
    antes = set(sys.modules)
    assert registry.resolve(Cap.VOLUME, WIN32).name == "windows.pycaw"
    assert not [m for m in set(sys.modules) - antes if m.split(".")[0] in ("pycaw", "comtypes")]


@linux
def test_registro_linux_wpctl_depois_pactl(fake_tools, monkeypatch, tmp_path):
    from jarvis.platform.linux import tools

    bin_dir = tmp_path / "fake_tools_bin"
    fake_tools({"pactl": 'case "$1" in info) exit 0;; esac'})
    monkeypatch.setenv("PATH", _path_so(tmp_path, bin_dir))
    assert registry.resolve(Cap.VOLUME, WAYLAND).name == "linux.pactl"

    fake_tools({"wpctl": 'case "$1" in status) exit 0;; esac'})
    monkeypatch.setenv("PATH", _path_so(tmp_path, bin_dir))
    tools.clear_which_cache()
    registry._clear_all()
    assert registry.resolve(Cap.VOLUME, WAYLAND).name == "linux.wpctl"

    vazio = tmp_path / "vazio"
    vazio.mkdir()
    monkeypatch.setenv("PATH", str(vazio))
    tools.clear_which_cache()
    registry._clear_all()
    assert isinstance(registry.resolve(Cap.VOLUME, HEADLESS), Unavailable)
