"""K F2-02: adapters de tray, run_in_gui_thread e o REGISTRY (N0, sem display).

- Windows (W1): PystrayTray monta o mesmo menu/ícone do oráculo legado, roda icon.run
  numa thread e começa oculto; set_visible/stop no ícone.
- qt_gui.run_in_gui_thread com QtCore falso: da thread da GUI roda direto; de outra
  thread posta e espera; timeout devolve None; exceção volta para quem chamou.
- QtSystemTray com PySide6 falso: QMenu na ordem, separador, ação padrão, clique no
  ícone dispara a ação padrão, começa oculto, tudo pela GUI. Sonda do watcher num
  D-Bus PRIVADO. O Qt de verdade é coberto pelo gate N2/N3 (test_qt_gui_thread).
"""
import subprocess
import sys
import threading
import time
import types

import pytest

from jarvis.platform import registry
from jarvis.platform.capabilities import Cap
from jarvis.platform.detect import detect
from jarvis.platform.protocols import TrayItem
from jarvis.platform.windows.tray import PystrayTray
from tests.golden.legacy_31bc0ce import legacy_criar_tray_icon, legacy_criar_tray_menu

WIN32 = detect(sys_platform="win32", environ={}, frozen=False)
WAYLAND = detect(sys_platform="linux", environ={"WAYLAND_DISPLAY": "w"}, frozen=False)

linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="só Linux")


@pytest.fixture(autouse=True)
def _isolado(monkeypatch, tmp_path):
    from jarvis.platform.linux import dbus as jdbus

    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/sem-sessao")
    monkeypatch.setenv("DBUS_SYSTEM_BUS_ADDRESS", f"unix:path={tmp_path}/sem-sistema")
    jdbus.reset()
    registry._clear_all()
    yield
    registry._clear_all()
    jdbus.reset()


# ── Windows: pystray literal ────────────────────────────────────────────────────

class _MenuItem:
    def __init__(self, label, callback, *, default=False):
        self.label, self.callback, self.default = label, callback, default


class _Menu:
    SEPARATOR = object()

    def __init__(self, *items):
        self.items = items


class _Icon:
    def __init__(self, name, image, title, menu):
        self.name, self.image, self.title, self.menu = name, image, title, menu
        self.visible = None
        self.rodou = threading.Event()
        self.parado = False

    def run(self):
        self.rodou.set()

    def stop(self):
        self.parado = True


def _itens(restaurar, briefing, encerrar):
    return [TrayItem("Restaurar JARVIS", restaurar, default=True), TrayItem("Briefing", briefing),
            TrayItem("", None, separator=True), TrayItem("Encerrar", encerrar)]


def test_pystray_igual_ao_legado():
    fake = types.SimpleNamespace(Menu=_Menu, MenuItem=_MenuItem, Icon=_Icon)
    restaurar, briefing, encerrar = object(), object(), object()
    imagem = object()
    tray = PystrayTray(WIN32, pystray_mod=fake)
    assert tray.setup("J.A.R.V.I.S.", lambda: imagem, _itens(restaurar, briefing, encerrar)) is True

    velho_menu = legacy_criar_tray_menu(fake, on_restaurar=restaurar, on_briefing=briefing, on_encerrar=encerrar)
    velho_icone = legacy_criar_tray_icon(fake, imagem, velho_menu)
    novo = tray._icon
    assert (novo.name, novo.image, novo.title, novo.visible) == (velho_icone.name, velho_icone.image,
                                                                 velho_icone.title, velho_icone.visible)

    def resumo(menu):
        return [("SEP",) if i is _Menu.SEPARATOR else (i.label, i.callback, i.default) for i in menu.items]

    assert resumo(novo.menu) == resumo(velho_menu)
    assert novo.rodou.wait(2)

    tray.set_visible(True)
    assert novo.visible is True
    tray.set_visible(False)
    assert novo.visible is False
    tray.stop()
    assert novo.parado


def test_pystray_sonda(monkeypatch):
    monkeypatch.setitem(sys.modules, "pystray", types.ModuleType("pystray"))
    assert PystrayTray.probe(WIN32).ok
    monkeypatch.setitem(sys.modules, "pystray", None)
    p = PystrayTray.probe(WIN32)
    assert p.ok is False and "pystray indisponível" in p.reason


# ── qt_gui.run_in_gui_thread com QtCore falso ───────────────────────────────────

class _FilaGui:
    """Thread "da GUI" falsa: executa o que o QTimer.singleShot posta."""

    def __init__(self, processa=True):
        self.thread = threading.Thread(target=self._laco, daemon=True, name="gui-falsa")
        self.fila = []
        self.processa = processa
        self.parar = threading.Event()
        self.thread.start()

    def _laco(self):
        while not self.parar.is_set():
            if self.processa and self.fila:
                self.fila.pop(0)()
            time.sleep(0.005)


@pytest.fixture
def qtcore_falso(monkeypatch):
    def montar(gui):
        class QThread:
            @staticmethod
            def currentThread():
                return threading.current_thread()

        class QTimer:
            @staticmethod
            def singleShot(ms, contexto, fn):
                assert ms == 0
                contexto.gui.fila.append(fn)

        contexto = types.SimpleNamespace(gui=gui, thread=lambda: gui.thread)
        app = types.SimpleNamespace(instance=lambda: contexto)
        core = types.ModuleType("PySide6.QtCore")
        core.QThread, core.QTimer, core.QCoreApplication = QThread, QTimer, app
        pacote = types.ModuleType("PySide6")
        pacote.QtCore = core
        monkeypatch.setitem(sys.modules, "PySide6", pacote)
        monkeypatch.setitem(sys.modules, "PySide6.QtCore", core)
        return contexto

    return montar


def test_run_in_gui_thread_de_outra_thread_posta_e_espera(qtcore_falso):
    from jarvis.platform.linux.qt_gui import run_in_gui_thread

    gui = _FilaGui()
    contexto = qtcore_falso(gui)
    try:
        assert run_in_gui_thread(contexto, lambda: threading.current_thread().name, timeout=2) == "gui-falsa"
        assert run_in_gui_thread(None, lambda: 7, timeout=2) == 7  # contexto padrão = QApplication
    finally:
        gui.parar.set()


def test_run_in_gui_thread_na_propria_gui_roda_direto(qtcore_falso):
    from jarvis.platform.linux.qt_gui import run_in_gui_thread

    gui = types.SimpleNamespace(thread=threading.current_thread(), fila=[])
    contexto = qtcore_falso(gui)
    assert run_in_gui_thread(contexto, lambda: 1, timeout=0.2) == 1
    assert gui.fila == []


def test_run_in_gui_thread_timeout_e_excecao(qtcore_falso):
    from jarvis.platform.linux.qt_gui import run_in_gui_thread

    parada = _FilaGui(processa=False)
    contexto = qtcore_falso(parada)
    inicio = time.monotonic()
    assert run_in_gui_thread(contexto, lambda: 1, timeout=0.2) is None
    assert time.monotonic() - inicio < 1.0
    parada.parar.set()

    gui = _FilaGui()
    contexto = qtcore_falso(gui)
    try:
        def quebra():
            raise ValueError("falhou na GUI")

        with pytest.raises(ValueError, match="falhou na GUI"):
            run_in_gui_thread(contexto, quebra, timeout=2)
    finally:
        gui.parar.set()


# ── QtSystemTray com PySide6 falso ──────────────────────────────────────────────

class _Sinal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in self.slots:
            slot(*args)


class _Acao:
    def __init__(self, texto):
        self.texto = texto
        self.triggered = _Sinal()


class _QMenu:
    def __init__(self):
        self.entradas = []
        self.padrao = None

    def addSeparator(self):
        self.entradas.append("SEP")

    def addAction(self, texto):
        acao = _Acao(texto)
        self.entradas.append(acao)
        return acao

    def setDefaultAction(self, acao):
        self.padrao = acao


class _QSystemTrayIcon:
    class ActivationReason:
        Trigger, DoubleClick, Context = "trigger", "double", "context"

    def __init__(self, icone):
        self.icone = icone
        self.activated = _Sinal()
        self.visivel = None
        self.menu = None
        self.dica = None
        self.escondido = False

    def setToolTip(self, texto):
        self.dica = texto

    def setContextMenu(self, menu):
        self.menu = menu

    def setVisible(self, valor):
        self.visivel = valor

    def hide(self):
        self.escondido = True


@pytest.fixture
def pyside_falso(monkeypatch):
    import jarvis.platform.linux.tray_qt as tray_qt

    class _QPixmap:
        def loadFromData(self, dados, formato):
            self.dados, self.formato = dados, formato
            return True

    gui = types.ModuleType("PySide6.QtGui")
    gui.QPixmap, gui.QIcon = _QPixmap, lambda pixmap: ("icone", pixmap)
    widgets = types.ModuleType("PySide6.QtWidgets")
    widgets.QMenu, widgets.QSystemTrayIcon = _QMenu, _QSystemTrayIcon
    pacote = types.ModuleType("PySide6")
    for nome, mod in (("PySide6", pacote), ("PySide6.QtGui", gui), ("PySide6.QtWidgets", widgets)):
        monkeypatch.setitem(sys.modules, nome, mod)
    chamadas_gui = []

    def gui_direto(contexto, fn, timeout=5.0):
        chamadas_gui.append(timeout)
        return fn()

    monkeypatch.setattr(tray_qt, "run_in_gui_thread", gui_direto)
    return chamadas_gui


class _Imagem:
    def save(self, buffer, formato):
        assert formato == "PNG"
        buffer.write(b"\x89PNG-falso")


@linux
def test_qt_tray_menu_padrao_clique_e_visibilidade(pyside_falso):
    from jarvis.platform.linux.tray_qt import QtSystemTray

    chamadas = []
    tray = QtSystemTray(WAYLAND)
    itens = _itens(lambda: chamadas.append("restaurar"), lambda: chamadas.append("briefing"),
                   lambda: chamadas.append("encerrar"))
    assert tray.setup("J.A.R.V.I.S.", _Imagem, itens) is True

    icone = tray._icone
    assert icone.dica == "J.A.R.V.I.S." and icone.visivel is False
    assert icone.icone[1].dados == b"\x89PNG-falso"
    menu = icone.menu
    assert [e if e == "SEP" else e.texto for e in menu.entradas] == ["Restaurar JARVIS", "Briefing", "SEP", "Encerrar"]
    assert menu.padrao is menu.entradas[0]

    menu.entradas[1].triggered.emit(False)
    icone.activated.emit(_QSystemTrayIcon.ActivationReason.Context)
    icone.activated.emit(_QSystemTrayIcon.ActivationReason.Trigger)
    assert chamadas == ["briefing", "restaurar"]

    tray.set_visible(True)
    assert icone.visivel is True
    tray.stop()
    assert icone.escondido and tray._icone is None
    assert len(pyside_falso) == 3  # setup, set_visible e stop passaram pela GUI


@linux
def test_qt_tray_setup_que_falha_devolve_false(pyside_falso, monkeypatch, capsys):
    import jarvis.platform.linux.tray_qt as tray_qt

    monkeypatch.setattr(tray_qt, "run_in_gui_thread", lambda *a, **k: None)  # GUI não respondeu
    assert tray_qt.QtSystemTray(WAYLAND).setup("J.A.R.V.I.S.", _Imagem, []) is False

    def sem_app(*a, **k):
        raise RuntimeError("run_in_gui_thread: sem QApplication")

    monkeypatch.setattr(tray_qt, "run_in_gui_thread", sem_app)
    assert tray_qt.QtSystemTray(WAYLAND).setup("J.A.R.V.I.S.", _Imagem, []) is False
    assert "sem QApplication" in capsys.readouterr().out


# ── sonda do watcher e REGISTRY ──────────────────────────────────────────────────

@linux
def test_qt_tray_sonda_com_e_sem_watcher(private_session_bus):
    pytest.importorskip("jeepney")
    dbusmock = pytest.importorskip("dbusmock")
    from jarvis.platform.linux import dbus as jdbus
    from jarvis.platform.linux.tray_qt import QtSystemTray

    p = QtSystemTray.probe(WAYLAND)
    assert p.ok is False and "StatusNotifierWatcher" in p.reason
    proc = dbusmock.DBusTestCase.spawn_server("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
                                              "org.kde.StatusNotifierWatcher", stdout=subprocess.DEVNULL)
    try:
        assert QtSystemTray.probe(WAYLAND).ok
    finally:
        jdbus.reset()
        proc.terminate()
        proc.wait(timeout=5)


def test_qt_tray_sonda_x11_nao_consulta_o_watcher(monkeypatch):
    import jarvis.platform.linux.tray_qt as tray_qt

    def proibido(*args, **kwargs):
        raise AssertionError("no X11 a sonda não consulta o D-Bus")

    monkeypatch.setattr(tray_qt._dbus, "name_has_owner", proibido)
    x11 = detect(sys_platform="linux", environ={"DISPLAY": ":0"}, frozen=False)
    assert tray_qt.QtSystemTray.probe(x11).ok


def test_cadeias_por_kind():
    assert registry._chain_for(Cap.TRAY, "win32") == ("jarvis.platform.windows.tray:PystrayTray",)
    assert registry._chain_for(Cap.TRAY, "linux-wayland") == ("jarvis.platform.linux.tray_qt:QtSystemTray",)
    assert registry._chain_for(Cap.TRAY, "linux-x11") == ("jarvis.platform.linux.tray_qt:QtSystemTray",)
    assert registry._chain_for(Cap.TRAY, "linux-headless") == ()


@linux
def test_sem_watcher_feature_tray_desligada():
    from jarvis.platform.features import feature_enabled

    def has(cap):
        return registry.has(cap, WAYLAND)

    def get(cap):
        return registry.resolve(cap, WAYLAND)

    assert feature_enabled(WAYLAND, "tray", has=has, get=get, environ={}) is False
