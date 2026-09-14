"""K F2-04: adapters de clipboard, o monitor do clipboard_hist_ctrl e o REGISTRY.

- Windows (W1): o call site do system_ctrl com WindowsClipboard dá as mesmas
  respostas do oráculo legado; watch + _on_change dão o mesmo histórico que o
  _monitor_loop legado, com sleep de 0,8 s.
- clipboard_hist_ctrl: sem backend que monitore, UMA mensagem e nenhuma thread.
- Linux: wl-clipboard novo (--watch), velho no GNOME (monitor desligado, sem
  D-Bus) e velho no KDE (Klipper assume, serviço falso no barramento PRIVADO);
  xclip/xsel; Klipper. Ferramentas sempre falsas (fake_tools).
"""
import subprocess
import sys
import threading
import time
import types

import pytest

from jarvis.platform import registry
from jarvis.platform.capabilities import Cap
from jarvis.platform.common.unavailable import Unavailable
from jarvis.platform.detect import detect
from jarvis.platform.windows.clipboard import WindowsClipboard
from tests.golden.legacy_31bc0ce import (
    CLIPBOARD_HISTORY_MAX,
    legacy_get_clipboard,
    legacy_monitor_loop_iteration,
    legacy_set_clipboard,
)

WIN32 = detect(sys_platform="win32", environ={}, frozen=False)
WAYLAND_KDE = detect(sys_platform="linux", environ={"WAYLAND_DISPLAY": "w", "XDG_CURRENT_DESKTOP": "KDE"}, frozen=False)
WAYLAND_GNOME = detect(sys_platform="linux", environ={"WAYLAND_DISPLAY": "w", "XDG_CURRENT_DESKTOP": "GNOME"}, frozen=False)
X11 = detect(sys_platform="linux", environ={"DISPLAY": ":0"}, frozen=False)
HEADLESS = detect(sys_platform="linux", environ={}, frozen=False)

linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="só Linux")

KLIPPER = ("org.kde.klipper", "/klipper", "org.kde.klipper.klipper")


@pytest.fixture(autouse=True)
def _isolado(monkeypatch, tmp_path):
    """D-Bus de sessão/sistema em sockets inexistentes; caches limpos."""
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


@pytest.fixture
def chc(monkeypatch):
    from comandos import clipboard_hist_ctrl as mod

    monkeypatch.setattr(mod, "_history", [])
    monkeypatch.setattr(mod, "_last", None)
    monkeypatch.setattr(mod, "_aviso_sem_monitor", False)
    monkeypatch.setattr(mod, "_monitor_thread", None)
    yield mod
    mod._stop_event.set()


def _esperar(cond, timeout=3.0):
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _rodar_watch(backend, on_change):
    stop = threading.Event()
    resultado = {}
    t = threading.Thread(target=lambda: resultado.setdefault("ret", backend.watch(on_change, stop)), daemon=True)
    t.start()
    return stop, t, resultado


# ── Windows ──────────────────────────────────────────────────────────────────────

def _fake_pyperclip(paste=None, copy=None):
    return types.SimpleNamespace(paste=paste or (lambda: ""), copy=copy or (lambda _t: None))


def _boom(*_a):
    raise RuntimeError("negado")


@pytest.mark.parametrize("paste", [lambda: "texto colado", lambda: None, _boom])
def test_windows_get_clipboard_igual_ao_legado(monkeypatch, paste):
    import jarvis.platform as plat
    from comandos import system_ctrl

    fake = _fake_pyperclip(paste=paste)
    monkeypatch.setattr(plat, "get", lambda cap: WindowsClipboard(WIN32, pyperclip_mod=fake))
    assert system_ctrl.get_clipboard() == legacy_get_clipboard(fake)


@pytest.mark.parametrize("copy", [lambda _t: None, _boom])
def test_windows_set_clipboard_igual_ao_legado(monkeypatch, copy):
    import jarvis.platform as plat
    from comandos import system_ctrl

    fake = _fake_pyperclip(copy=copy)
    monkeypatch.setattr(plat, "get", lambda cap: WindowsClipboard(WIN32, pyperclip_mod=fake))
    assert system_ctrl.set_clipboard("olá") == legacy_set_clipboard(fake, "olá")


def test_windows_watch_mais_on_change_igual_ao_loop_legado(chc):
    leituras = ["abc", "abc", "a", None, RuntimeError("x"), "def", "abc", "  z  ", "def"]

    def leitor(seq):
        it = iter(seq)

        def _ler():
            v = next(it)
            if isinstance(v, Exception):
                raise v
            return v
        return _ler

    stop = threading.Event()
    sleeps = []

    def dormir(s):
        sleeps.append(s)
        if len(sleeps) == len(leituras):
            stop.set()

    WindowsClipboard(WIN32, get_text_fn=leitor(leituras), sleep_fn=dormir).watch(chc._on_change, stop)

    historico, last, ler = [], None, leitor(leituras)
    for _ in leituras:
        last = legacy_monitor_loop_iteration(ler, historico, last)

    assert chc._history == historico
    assert historico == ["abc", "def", "abc", "def"]  # "a" e "  z  " têm 1 caractere útil
    assert sleeps == [0.8] * len(leituras)


def test_on_change_respeita_limite(chc):
    for i in range(CLIPBOARD_HISTORY_MAX + 1):
        chc._on_change(f"item{i}")
    assert len(chc._history) == CLIPBOARD_HISTORY_MAX
    assert chc._history[0] == "item1"


# ── clipboard_hist_ctrl.start_monitor ───────────────────────────────────────────

def test_sem_monitor_avisa_uma_vez_e_nao_cria_thread(chc, monkeypatch, capsys):
    monkeypatch.setattr(chc, "_plat_get_clipboard", lambda: types.SimpleNamespace(can_watch=False))
    chc.start_monitor()
    chc.start_monitor()
    assert capsys.readouterr().out.count("monitor de clipboard desligado") == 1
    assert chc._monitor_thread is None


def test_backend_indisponivel_vira_monitor_desligado(chc, monkeypatch, capsys):
    monkeypatch.setattr(chc, "_plat_get_clipboard", lambda: Unavailable(Cap.CLIPBOARD, []))
    chc.start_monitor()
    assert "monitor de clipboard desligado" in capsys.readouterr().out
    assert chc._monitor_thread is None


def test_watch_que_levanta_para_com_mensagem(chc, monkeypatch, capsys):
    class _Quebra:
        can_watch = True

        def watch(self, on_change, stop):
            raise OSError("compositor sumiu")

    monkeypatch.setattr(chc, "_plat_get_clipboard", lambda: _Quebra())
    chc.start_monitor()
    chc._monitor_thread.join(timeout=2)
    assert "monitor de clipboard parou: compositor sumiu" in capsys.readouterr().out


# ── Wayland (wl-clipboard falso) ────────────────────────────────────────────────

def _wl_paste(novo=True):
    lista = 'echo "text/plain"' if novo else 'echo "wl-paste: compositor does not support data-control" >&2; exit 1'
    return (
        'case "$*" in\n'
        f'  *--list-types*) {lista} ;;\n'
        '  *--watch*) for i in 1 2; do echo __JARVIS_CLIP__; sleep 0.2; done; exec sleep 30 ;;\n'
        '  *) printf "%s" "copiado" ;;\n'
        'esac'
    )


@linux
def test_wl_get_e_set(fake_tools, tmp_path):
    from jarvis.platform.linux_wayland.clipboard import WlClipboard

    saida = tmp_path / "wl-copy.stdin"
    calls = fake_tools({"wl-paste": _wl_paste(), "wl-copy": f'cat > "{saida}"'})
    wl = WlClipboard(WAYLAND_KDE)
    assert wl.get_text() == "copiado"
    assert calls["wl-paste"].read_text().splitlines() == ["--no-newline --type text"]
    assert wl.set_text("olá, Jarvis") is True
    assert saida.read_text(encoding="utf-8") == "olá, Jarvis"


@linux
def test_wl_novo_watch_com_filho_registrado_e_encerrado(fake_tools):
    import jarvis.platform as plat
    from jarvis.platform.linux_wayland.clipboard import WlClipboard

    plat._reset_for_tests(HEADLESS)  # processes() = PosixProcesses
    try:
        calls = fake_tools({"wl-paste": _wl_paste(novo=True), "wl-copy": "true"})
        wl = WlClipboard(WAYLAND_GNOME)
        assert wl.can_watch is True
        vistos = []
        stop, t, resultado = _rodar_watch(wl, vistos.append)
        assert _esperar(lambda: len(vistos) >= 2)
        assert plat.processes().alive_children()  # wl-paste --watch registrado
        stop.set()
        t.join(timeout=5)
        assert resultado.get("ret") is True
        assert vistos[:2] == ["copiado", "copiado"]
        assert "--type text --watch echo __JARVIS_CLIP__" in calls["wl-paste"].read_text()
        assert plat.processes().alive_children() == []
    finally:
        plat._reset_for_tests(None)


@linux
def test_wl_velho_no_gnome_sem_monitor_e_sem_dbus(fake_tools, monkeypatch):
    from jarvis.platform.linux import clipboard_klipper
    from jarvis.platform.linux_wayland import clipboard as wl_mod

    def proibido(*a, **k):
        raise AssertionError("fora do KDE não consulta o Klipper")

    monkeypatch.setattr(wl_mod, "klipper_available", proibido)
    monkeypatch.setattr(clipboard_klipper, "klipper_available", proibido)
    fake_tools({"wl-paste": _wl_paste(novo=False), "wl-copy": "true"})
    wl = wl_mod.WlClipboard(WAYLAND_GNOME)
    assert wl.can_watch is False
    assert wl.watch(lambda _t: None, threading.Event()) is False


@pytest.fixture
def klipper_falso(private_session_bus):
    pytest.importorskip("jeepney")
    dbusmock = pytest.importorskip("dbusmock")
    from jarvis.platform.linux import dbus as jdbus

    proc = dbusmock.DBusTestCase.spawn_server(*KLIPPER, stdout=subprocess.DEVNULL)
    nome, caminho, iface = KLIPPER
    jdbus.call(nome, caminho, "org.freedesktop.DBus.Mock", "AddMethods", "sa(ssss)", (iface, [
        ("getClipboardContents", "", "s", 'ret = "do klipper"'),
        ("setClipboardContents", "s", "", ""),
    ]))

    def emitir():
        jdbus.call(nome, caminho, "org.freedesktop.DBus.Mock", "EmitSignal", "sssav",
                   (iface, "clipboardHistoryUpdated", "", []))

    def chamadas(metodo):
        (linhas,) = jdbus.call(nome, caminho, "org.freedesktop.DBus.Mock", "GetMethodCalls", "s", (metodo,))
        return [[v[1] for v in args] for _ts, args in linhas]

    try:
        yield types.SimpleNamespace(emitir=emitir, chamadas=chamadas)
    finally:
        jdbus.reset()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


@linux
def test_wl_velho_no_kde_klipper_assume(fake_tools, klipper_falso):
    from jarvis.platform.linux_wayland.clipboard import WlClipboard

    fake_tools({"wl-paste": _wl_paste(novo=False), "wl-copy": "true"})
    wl = WlClipboard(WAYLAND_KDE)
    assert wl.can_watch is True
    vistos = []
    stop, t, _res = _rodar_watch(wl, vistos.append)
    try:
        time.sleep(0.5)  # assinatura feita
        klipper_falso.emitir()
        assert _esperar(lambda: vistos == ["do klipper"])
    finally:
        stop.set()
        t.join(timeout=5)


@linux
def test_klipper_get_set_e_sonda(klipper_falso):
    from jarvis.platform.linux.clipboard_klipper import KlipperClipboard

    assert KlipperClipboard.probe(WAYLAND_KDE).ok
    k = KlipperClipboard(WAYLAND_KDE)
    assert k.get_text() == "do klipper"
    assert k.set_text("novo") is True
    assert klipper_falso.chamadas("setClipboardContents") == [["novo"]]


@linux
def test_klipper_sem_servico(private_session_bus):
    from jarvis.platform.linux.clipboard_klipper import KlipperClipboard

    assert KlipperClipboard.probe(WAYLAND_KDE).ok is False
    assert KlipperClipboard(WAYLAND_KDE).set_text("x") is False


# ── X11 (xclip/xsel falsos) ─────────────────────────────────────────────────────

@linux
@pytest.mark.parametrize("modulo_cls, ferramenta, leitura, escrita", [
    ("XclipClipboard", "xclip", "-selection clipboard -o", "-selection clipboard -i"),
    ("XselClipboard", "xsel", "--clipboard --output", "--clipboard --input"),
])
def test_x11_get_set_e_polling(fake_tools, tmp_path, modulo_cls, ferramenta, leitura, escrita):
    from jarvis.platform.linux_x11 import clipboard as x11

    saida = tmp_path / "stdin"
    calls = fake_tools({ferramenta: f'case "$*" in *-o*|*--output*) printf "%s" "do x11" ;; *) cat > "{saida}" ;; esac'})
    cb = getattr(x11, modulo_cls)(X11)
    assert cb.can_watch is True
    assert cb.get_text() == "do x11"
    assert cb.set_text("copiado no x11") is True
    assert saida.read_text() == "copiado no x11"
    linhas = calls[ferramenta].read_text().splitlines()
    assert linhas[:2] == [leitura, escrita]

    vistos = []
    stop, t, resultado = _rodar_watch(cb, vistos.append)
    assert _esperar(lambda: vistos)
    stop.set()
    t.join(timeout=3)
    assert resultado.get("ret") is True and vistos[0] == "do x11"


# ── REGISTRY ─────────────────────────────────────────────────────────────────────

def test_cadeias_por_kind():
    assert registry._chain_for(Cap.CLIPBOARD, "win32") == ("jarvis.platform.windows.clipboard:WindowsClipboard",)
    assert registry._chain_for(Cap.CLIPBOARD, "linux-wayland") == (
        "jarvis.platform.linux_wayland.clipboard:WlClipboard",
        "jarvis.platform.linux.clipboard_klipper:KlipperClipboard",
    )
    assert registry._chain_for(Cap.CLIPBOARD, "linux-x11") == (
        "jarvis.platform.linux_x11.clipboard:XclipClipboard",
        "jarvis.platform.linux_x11.clipboard:XselClipboard",
        "jarvis.platform.linux.clipboard_klipper:KlipperClipboard",
    )
    assert registry._chain_for(Cap.CLIPBOARD, "linux-headless") == ()


def test_registro_win32():
    assert registry.resolve(Cap.CLIPBOARD, WIN32).name == "windows.clipboard"


@linux
def test_registro_linux_por_ferramentas(fake_tools, monkeypatch, tmp_path):
    bin_dir = tmp_path / "fake_tools_bin"
    from jarvis.platform.linux import tools

    fake_tools({"xsel": "true"})
    monkeypatch.setenv("PATH", str(bin_dir))
    assert registry.resolve(Cap.CLIPBOARD, X11).name == "linux_x11.xsel"

    fake_tools({"wl-paste": "true", "wl-copy": "true"})
    monkeypatch.setenv("PATH", str(bin_dir))
    tools.clear_which_cache()
    registry._clear_all()
    assert registry.resolve(Cap.CLIPBOARD, WAYLAND_KDE).name == "linux_wayland.wl_clipboard"

    registry._clear_all()
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    monkeypatch.setenv("PATH", str(vazio))
    tools.clear_which_cache()
    assert isinstance(registry.resolve(Cap.CLIPBOARD, WAYLAND_KDE), Unavailable)  # sem wl-clipboard nem Klipper
    registry._clear_all()
    assert isinstance(registry.resolve(Cap.CLIPBOARD, HEADLESS), Unavailable)
