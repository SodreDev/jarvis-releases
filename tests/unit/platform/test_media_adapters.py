"""K F2-08: adapters de mídia, call sites do midia_ctrl e o REGISTRY.

- Windows (W1): VirtualKeyMedia faz a mesma sequência de keybd_event do oráculo e
  o midia_ctrl devolve as mesmas mensagens; SMTC com subprocess.run falso = oráculo;
  _LazyUser32 no Linux não toca ctypes.windll.
- Sem player (CapabilityUnavailable): "Nenhum player de mídia ativo, Senhor.".
- Linux: MPRIS com players FALSOS (dbusmock, barramento PRIVADO): Playing, senão
  Paused, senão o primeiro; Metadata; mute/volume via Cap.VOLUME; playerctl falso.
"""
import ast
import subprocess
import sys
import types
from pathlib import Path

import pytest

from jarvis.platform import registry
from jarvis.platform.capabilities import Cap
from jarvis.platform.common.unavailable import Unavailable
from jarvis.platform.detect import detect
from jarvis.platform.errors import CapabilityUnavailable
from jarvis.platform.windows.media import VirtualKeyMedia
from tests.golden.legacy_31bc0ce import (
    legacy_faixa_anterior,
    legacy_get_media_info_ps,
    legacy_mutar,
    legacy_o_que_esta_tocando,
    legacy_parar,
    legacy_play_pause,
    legacy_proxima_faixa,
    legacy_volume_down,
    legacy_volume_up,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
WIN32 = detect(sys_platform="win32", environ={}, frozen=False)
WAYLAND = detect(sys_platform="linux", environ={"WAYLAND_DISPLAY": "w"}, frozen=False)
HEADLESS = detect(sys_platform="linux", environ={}, frozen=False)

linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="só Linux")

PATH_MPRIS = "/org/mpris/MediaPlayer2"
IFACE = "org.mpris.MediaPlayer2.Player"
MOCK = "org.freedesktop.DBus.Mock"


@pytest.fixture(autouse=True)
def _isolado(monkeypatch, tmp_path):
    from jarvis.platform.linux import dbus as jdbus
    from jarvis.platform.linux import tools

    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/sem-sessao")
    monkeypatch.setenv("DBUS_SYSTEM_BUS_ADDRESS", f"unix:path={tmp_path}/sem-sistema")
    jdbus.reset()
    tools.clear_which_cache()
    registry._clear_all()
    yield
    registry._clear_all()
    tools.clear_which_cache()
    jdbus.reset()


# ── Windows ──────────────────────────────────────────────────────────────────────

class _User32:
    def __init__(self):
        self.calls = []

    def keybd_event(self, *args):
        self.calls.append(args)


def _run_com(saida):
    chamadas = []

    def run(*args, **kwargs):
        chamadas.append((args, kwargs))
        if isinstance(saida, Exception):
            raise saida
        return types.SimpleNamespace(stdout=saida)

    run.chamadas = chamadas
    return run


@pytest.fixture
def mdc_windows(monkeypatch):
    import jarvis.platform as plat
    from comandos import midia_ctrl

    def usar(run_fn=None):
        u, sleeps = _User32(), []
        media = VirtualKeyMedia(WIN32, user32=u, sleep_fn=sleeps.append, run_fn=run_fn or _run_com("NULL"))
        monkeypatch.setattr(plat, "get", lambda cap: media)
        return midia_ctrl, u, sleeps

    return usar


@pytest.mark.parametrize("nome, legado, args", [
    ("play_pause", legacy_play_pause, ()),
    ("parar", legacy_parar, ()),
    ("proxima_faixa", legacy_proxima_faixa, ()),
    ("faixa_anterior", legacy_faixa_anterior, ()),
    ("mutar", legacy_mutar, ()),
    ("volume_up", legacy_volume_up, ()),
    ("volume_down", legacy_volume_down, (5,)),
    ("volume_up", legacy_volume_up, (0,)),
    ("volume_down", legacy_volume_down, (-2,)),
])
def test_teclas_e_mensagens_iguais_ao_legado(mdc_windows, nome, legado, args):
    mdc, u, _sleeps = mdc_windows()
    velhas = []
    esperado = legado(lambda *a: velhas.append(a), *args, sleep_fn=lambda s: None)
    assert getattr(mdc, nome)(*args) == esperado
    assert u.calls == velhas


def test_pausas_iguais_ao_midia_ctrl_antigo(mdc_windows):
    mdc, _u, sleeps = mdc_windows()
    mdc.play_pause()
    assert sleeps == [0.05]
    sleeps.clear()
    mdc.volume_up(3)
    assert sleeps == [0.05, 0.02] * 3


@pytest.mark.parametrize("saida", [
    "Musica|Artista|Playing|App.exe!Spotify",
    "Musica||Paused|App.exe!Spotify",
    "Musica|Artista|4|",
    "NULL",
    OSError("powershell não encontrado"),
])
def test_smtc_igual_ao_legado(mdc_windows, saida):
    run = _run_com(saida)
    mdc, _u, _s = mdc_windows(run_fn=run)
    assert mdc.o_que_esta_tocando() == legacy_o_que_esta_tocando(_run_com(saida))
    assert VirtualKeyMedia(WIN32, run_fn=_run_com(saida)).now_playing() == legacy_get_media_info_ps(_run_com(saida))
    (argv,), kwargs = run.chamadas[0]
    assert argv[:3] == ["powershell", "-NoProfile", "-Command"]
    assert kwargs == {"capture_output": True, "text": True, "timeout": 8}


def test_lazy_user32_no_linux_nao_toca_windll(monkeypatch):
    import ctypes

    if sys.platform == "win32":
        pytest.skip("só faz sentido fora do Windows")

    class _Tripwire:
        def __getattr__(self, nome):
            raise AssertionError(f"ctypes.windll foi tocado (.{nome})")

    monkeypatch.setattr(ctypes, "windll", _Tripwire(), raising=False)
    with pytest.raises(NotImplementedError):
        VirtualKeyMedia(WIN32, sleep_fn=lambda s: None).play_pause()


def test_sem_player_aviso_do_midia_ctrl(monkeypatch):
    import jarvis.platform as plat
    from comandos import midia_ctrl as mdc

    monkeypatch.setattr(plat, "get", lambda cap: Unavailable(Cap.MEDIA, [("x", "nenhum player MPRIS")]))
    for fn in (mdc.play_pause, mdc.parar, mdc.proxima_faixa, mdc.faixa_anterior, mdc.mutar,
               mdc.volume_up, mdc.volume_down, mdc.o_que_esta_tocando):
        assert fn() == "Nenhum player de mídia ativo, Senhor."


def test_midia_ctrl_sem_smtc_e_sem_teclas_nas_funcoes_migradas():
    tree = ast.parse((REPO_ROOT / "comandos" / "midia_ctrl.py").read_text(encoding="utf-8-sig"))
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_get_media_info_ps" not in funcs
    for nome in ("play_pause", "parar", "proxima_faixa", "faixa_anterior", "mutar",
                 "volume_up", "volume_down", "o_que_esta_tocando"):
        chamadas = {getattr(c.func, "id", getattr(c.func, "attr", None))
                    for c in ast.walk(funcs[nome]) if isinstance(c, ast.Call)}
        assert "_press_key" not in chamadas and "keybd_event" not in chamadas, nome


# ── Linux: MPRIS com players falsos ─────────────────────────────────────────────

@pytest.fixture
def players(private_session_bus):
    pytest.importorskip("jeepney")
    dbusmock = pytest.importorskip("dbusmock")
    from jarvis.platform.linux import dbus as jdbus

    procs = []

    def subir(nome, status, titulo="", artista=""):
        bus = f"org.mpris.MediaPlayer2.{nome}"
        procs.append(dbusmock.DBusTestCase.spawn_server(bus, PATH_MPRIS, IFACE, stdout=subprocess.DEVNULL))
        jdbus.call(bus, PATH_MPRIS, MOCK, "AddProperty", "ssv", (IFACE, "PlaybackStatus", ("s", status)))
        meta = {"xesam:title": ("s", titulo), "xesam:artist": ("as", [artista] if artista else [])}
        jdbus.call(bus, PATH_MPRIS, MOCK, "AddProperty", "ssv", (IFACE, "Metadata", ("a{sv}", meta)))
        jdbus.call(bus, PATH_MPRIS, MOCK, "AddMethods", "sa(ssss)", (IFACE, [
            ("PlayPause", "", "", ""), ("Stop", "", "", ""), ("Next", "", "", ""), ("Previous", "", "", ""),
        ]))

        def chamadas(metodo):
            (linhas,) = jdbus.call(bus, PATH_MPRIS, MOCK, "GetMethodCalls", "s", (metodo,))
            return len(linhas)

        return chamadas

    yield subir
    jdbus.reset()
    for p in procs:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=5)


@linux
def test_mpris_tocando_ganha_do_pausado(players):
    from jarvis.platform.linux.media import MprisMedia

    vlc = players("vlc", "Paused", "Pausada", "X")
    spotify = players("spotify", "Playing", "Tocando", "Y")
    m = MprisMedia(WAYLAND)
    m.play_pause()
    assert (spotify("PlayPause"), vlc("PlayPause")) == (1, 0)
    assert m.now_playing() == {"title": "Tocando", "artist": "Y", "player": "spotify", "status": "Playing"}


@linux
def test_mpris_pausado_ganha_do_parado_e_depois_o_primeiro(players):
    from jarvis.platform.linux.media import MprisMedia

    aaa = players("aaa", "Stopped")
    zzz = players("zzz.instance_1_42", "Paused", "Z")
    m = MprisMedia(WAYLAND)
    m.next()
    m.stop()
    assert (zzz("Next"), zzz("Stop"), aaa("Next")) == (1, 1, 0)
    assert m.now_playing()["player"] == "zzz"


@linux
def test_mpris_so_parados_vai_para_o_primeiro(players):
    from jarvis.platform.linux.media import MprisMedia

    aaa = players("aaa", "Stopped")
    bbb = players("bbb", "Stopped")
    MprisMedia(WAYLAND).previous_track()
    assert (aaa("Previous"), bbb("Previous")) == (1, 0)


@linux
def test_mpris_sem_player_e_sonda(private_session_bus):
    pytest.importorskip("jeepney")
    from jarvis.platform.linux.media import MprisMedia

    assert MprisMedia.probe(WAYLAND).ok
    with pytest.raises(CapabilityUnavailable, match="nenhum player MPRIS"):
        MprisMedia(WAYLAND).play_pause()


@linux
def test_mpris_sonda_sem_barramento():
    from jarvis.platform.linux.media import MprisMedia

    assert MprisMedia.probe(WAYLAND).ok is False


@pytest.mark.parametrize("cls_nome", ["MprisMedia", "PlayerctlMedia"])
def test_mute_e_volume_vao_para_cap_volume(monkeypatch, cls_nome):
    import jarvis.platform as plat
    from jarvis.platform.linux import media

    chamadas = []
    volume = types.SimpleNamespace(
        toggle_output_mute=lambda: chamadas.append(("mute",)),
        step_output=lambda d: chamadas.append(("step", d)),
    )
    monkeypatch.setattr(plat, "get", lambda cap: volume if cap is Cap.VOLUME else None)
    m = getattr(media, cls_nome)(WAYLAND)
    m.toggle_mute()
    m.volume_step(3)
    m.volume_step(-1)
    assert chamadas == [("mute",), ("step", 6), ("step", -2)]


# ── Linux: playerctl falso ──────────────────────────────────────────────────────

@linux
def test_playerctl_comandos_e_metadata(fake_tools):
    from jarvis.platform.linux.media import PlayerctlMedia

    calls = fake_tools({"playerctl": 'case "$1" in metadata) printf "Musica\\tArtista\\tspotify\\tPlaying\\n";; esac'})
    p = PlayerctlMedia(WAYLAND)
    p.stop()
    p.next()
    p.previous()
    assert p.now_playing() == {"title": "Musica", "artist": "Artista", "player": "spotify", "status": "Playing"}
    linhas = calls["playerctl"].read_text().splitlines()
    assert linhas[:3] == ["stop", "next", "previous"]
    assert linhas[3].startswith("metadata --format {{title}}")


@linux
def test_playerctl_sem_player_e_outros_erros(fake_tools):
    from jarvis.platform.linux.media import PlayerctlMedia

    fake_tools({"playerctl": 'echo "No players found" >&2; exit 1'})
    with pytest.raises(CapabilityUnavailable, match="nenhum player MPRIS"):
        PlayerctlMedia(WAYLAND).play_pause()

    fake_tools({"playerctl": 'echo "algo quebrou" >&2; exit 2'})
    with pytest.raises(OSError, match="algo quebrou"):
        PlayerctlMedia(WAYLAND).next()


# ── REGISTRY ─────────────────────────────────────────────────────────────────────

def test_cadeias_por_kind():
    assert registry._chain_for(Cap.MEDIA, "win32") == ("jarvis.platform.windows.media:VirtualKeyMedia",)
    cadeia = ("jarvis.platform.linux.media:MprisMedia", "jarvis.platform.linux.media:PlayerctlMedia")
    assert registry._chain_for(Cap.MEDIA, "linux-wayland") == cadeia
    assert registry._chain_for(Cap.MEDIA, "linux-x11") == cadeia
    assert registry._chain_for(Cap.MEDIA, "linux-headless") == ()


def test_registro_win32():
    assert registry.resolve(Cap.MEDIA, WIN32).name == "windows.virtual_keys"


@linux
def test_registro_linux_mpris_com_barramento(private_session_bus):
    pytest.importorskip("jeepney")
    assert registry.resolve(Cap.MEDIA, WAYLAND).name == "linux.mpris"


@linux
def test_registro_linux_sem_barramento_usa_playerctl(fake_tools, monkeypatch, tmp_path):
    fake_tools({"playerctl": "true"})
    monkeypatch.setenv("PATH", str(tmp_path / "fake_tools_bin"))
    assert registry.resolve(Cap.MEDIA, WAYLAND).name == "linux.playerctl"
    registry._clear_all()
    assert isinstance(registry.resolve(Cap.MEDIA, HEADLESS), Unavailable)
