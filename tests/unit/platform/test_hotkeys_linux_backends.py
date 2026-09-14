"""K F2-01 (b): portal GlobalShortcuts → KGlobalAccel, desktop entry, conversões e override.

Portal e KGlobalAccel FALSOS (dbusmock configurado via jeepney) no barramento PRIVADO;
o portal falso responde os pedidos emitindo Response no caminho de request previsto.
HOME isolado. Nada do D-Bus, do portal ou dos atalhos do host.
"""
import subprocess
import sys
import threading
import time

import pytest

from jarvis.platform import registry
from jarvis.platform.capabilities import Cap
from jarvis.platform.detect import detect
from jarvis.platform.errors import CapabilityUnavailable
from jarvis.platform.protocols import HotkeyBinding

linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="só Linux")

WAYLAND = detect(sys_platform="linux", environ={"WAYLAND_DISPLAY": "w", "XDG_CURRENT_DESKTOP": "KDE"}, frozen=False)
MOCK = "org.freedesktop.DBus.Mock"
PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
IFACE_GS = "org.freedesktop.portal.GlobalShortcuts"
SESSAO = "/org/freedesktop/portal/desktop/session/1_42/jarvis"
KGA_BUS, KGA_PATH, KGA_IFACE = "org.kde.kglobalaccel", "/kglobalaccel", "org.kde.KGlobalAccel"
COMPONENT_PATH, COMPONENT_IFACE = "/component/jarvis", "org.kde.kglobalaccel.Component"


def _esperar(cond, timeout=5.0):
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _valor(v):
    return v[1] if isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str) else v


@pytest.fixture(autouse=True)
def _isolado(monkeypatch, tmp_path):
    from jarvis.platform.linux import dbus as jdbus

    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/sem-sessao")
    monkeypatch.setenv("DBUS_SYSTEM_BUS_ADDRESS", f"unix:path={tmp_path}/sem-sistema")
    monkeypatch.delenv("JARVIS_HOTKEYS_BACKEND", raising=False)
    jdbus.reset()
    registry._clear_all()
    yield
    registry._clear_all()
    jdbus.reset()


# ── conversões ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("trigger, portal", [
    ("<shift>+g", "SHIFT+g"), ("<ctrl>+<alt>+j", "CTRL+ALT+j"), ("<cmd>+<shift>+g", "LOGO+SHIFT+g"),
])
def test_trigger_para_portal(trigger, portal):
    from jarvis.platform.linux_wayland.hotkeys_portal import convert_trigger_to_portal

    assert convert_trigger_to_portal(trigger) == portal


@pytest.mark.parametrize("trigger, codigo, texto", [
    ("<shift>+g", 0x02000000 | 0x47, "Shift+G"),
    ("<cmd>+<shift>+g", 0x10000000 | 0x02000000 | 0x47, "Meta+Shift+G"),
    ("<ctrl>+<alt>+j", 0x04000000 | 0x08000000 | ord("J"), "Ctrl+Alt+J"),
    ("<ctrl>+space", 0x04000000 | 0x20, "Ctrl+Space"),
    ("<alt>+<f5>", 0x08000000 | 0x01000034, "Alt+F5"),
])
def test_trigger_para_qt_e_descricao(trigger, codigo, texto):
    from jarvis.platform.linux.hotkeys_kglobalaccel import convert_trigger_to_qt_key, describe_qt_key

    assert convert_trigger_to_qt_key(trigger) == codigo
    assert describe_qt_key(codigo) == texto


def test_trigger_sem_tecla_ou_invalido():
    from jarvis.platform.linux.hotkeys_kglobalaccel import convert_trigger_to_qt_key

    for ruim in ("<ctrl>+<shift>", "<ctrl>+tecla_inventada"):
        with pytest.raises(ValueError):
            convert_trigger_to_qt_key(ruim)


# ── desktop entry ────────────────────────────────────────────────────────────────

@linux
def test_desktop_entry_idempotente_e_atualiza_exec(isolated_home):
    from jarvis.platform.linux.desktop_entry import ensure_desktop_entry

    caminho = ensure_desktop_entry("io.github.teste.Jarvis", main_path="/opt/jarvis/main.py", executable="/usr/bin/python3")
    assert caminho == isolated_home["data"] / "applications" / "io.github.teste.Jarvis.desktop"
    texto = caminho.read_text()
    assert "Exec=/usr/bin/python3 /opt/jarvis/main.py" in texto and "NoDisplay=true" in texto and "Icon=" in texto
    antes = caminho.stat().st_mtime_ns
    time.sleep(0.01)
    assert ensure_desktop_entry("io.github.teste.Jarvis", main_path="/opt/jarvis/main.py", executable="/usr/bin/python3")
    assert caminho.stat().st_mtime_ns == antes

    ensure_desktop_entry("io.github.teste.Jarvis", main_path="/home/ana b/main.py", executable="/usr/bin/python3")
    assert 'Exec=/usr/bin/python3 "/home/ana b/main.py"' in caminho.read_text()


@linux
def test_desktop_entry_no_appimage_nao_grava(isolated_home, monkeypatch):
    from jarvis.platform.linux.desktop_entry import desktop_entry_path, ensure_desktop_entry

    monkeypatch.setenv("APPIMAGE", "/tmp/Jarvis.AppImage")
    assert ensure_desktop_entry("io.github.teste.Jarvis") is None
    assert not desktop_entry_path("io.github.teste.Jarvis").exists()


# ── registro e override ──────────────────────────────────────────────────────────

def test_cadeias_por_kind():
    portal = "jarvis.platform.linux_wayland.hotkeys_portal:PortalGlobalShortcuts"
    kga = "jarvis.platform.linux.hotkeys_kglobalaccel:KGlobalAccelHotkeys"
    pynput = "jarvis.platform.common.pynput_hotkeys:PynputHotkeys"
    assert registry._chain_for(Cap.HOTKEYS, "linux-wayland") == (portal, kga)
    assert registry._chain_for(Cap.HOTKEYS, "linux-x11") == (pynput, kga)
    assert registry._chain_for(Cap.HOTKEYS, "win32") == (pynput,)
    assert registry._chain_for(Cap.HOTKEYS, "linux-headless") == ()


@pytest.mark.parametrize("valor, esperado", [
    ("kglobalaccel", ("jarvis.platform.linux.hotkeys_kglobalaccel:KGlobalAccelHotkeys",)),
    ("PORTAL", ("jarvis.platform.linux_wayland.hotkeys_portal:PortalGlobalShortcuts",)),
    ("pynput", ("jarvis.platform.common.pynput_hotkeys:PynputHotkeys",)),
])
def test_override_escolhe_a_cadeia_no_linux(monkeypatch, valor, esperado):
    monkeypatch.setenv("JARVIS_HOTKEYS_BACKEND", valor)
    assert registry._chain_for(Cap.HOTKEYS, "linux-wayland") == esperado


def test_override_invalido_avisa_e_ignora_e_win32_nao_muda(monkeypatch):
    monkeypatch.setenv("JARVIS_HOTKEYS_BACKEND", "xdotool")
    with pytest.warns(UserWarning, match="JARVIS_HOTKEYS_BACKEND inválido"):
        cadeia = registry._chain_for(Cap.HOTKEYS, "linux-wayland")
    assert len(cadeia) == 2
    monkeypatch.setenv("JARVIS_HOTKEYS_BACKEND", "kglobalaccel")
    assert registry._chain_for(Cap.HOTKEYS, "win32") == ("jarvis.platform.common.pynput_hotkeys:PynputHotkeys",)
    assert registry._chain_for(Cap.VOLUME, "linux-wayland")[0].endswith("WpctlVolume")


# ── serviços falsos ──────────────────────────────────────────────────────────────

@pytest.fixture
def servicos(private_session_bus, isolated_home):
    pytest.importorskip("jeepney")
    dbusmock = pytest.importorskip("dbusmock")
    from jarvis.platform.linux import dbus as jdbus

    procs = []

    def subir(nome, caminho, iface):
        procs.append(dbusmock.DBusTestCase.spawn_server(nome, caminho, iface, stdout=subprocess.DEVNULL))

    yield types_ns(jdbus=jdbus, subir=subir)
    jdbus.reset()
    for p in procs:
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=5)


def types_ns(**kw):
    import types

    return types.SimpleNamespace(**kw)


def _subir_kga(servicos, conflito=False):
    jdbus = servicos.jdbus
    servicos.subir(KGA_BUS, KGA_PATH, KGA_IFACE)
    jdbus.call(KGA_BUS, KGA_PATH, MOCK, "AddMethods", "sa(ssss)", (KGA_IFACE, [
        ("doRegister", "as", "", ""),
        ("setShortcut", "asaiu", "ai", "ret = []" if conflito else "ret = args[1]"),
        ("getComponent", "s", "o", f"ret = '{COMPONENT_PATH}'"),
        ("unRegister", "as", "", ""),
    ]))
    codigo_invoke = (f"self.EmitSignal('{COMPONENT_IFACE}', 'globalShortcutPressed', 'ssx', "
                     "['jarvis', args[0], 0])")
    jdbus.call(KGA_BUS, KGA_PATH, MOCK, "AddObject", "ssa{sv}a(ssss)",
               (COMPONENT_PATH, COMPONENT_IFACE, {}, [("invokeShortcut", "s", "", codigo_invoke)]))

    def chamadas(metodo):
        (linhas,) = jdbus.call(KGA_BUS, KGA_PATH, MOCK, "GetMethodCalls", "s", (metodo,))
        return [[_valor(a) for a in args] for _ts, args in linhas]

    def soltar(acao="ptt", componente="jarvis"):
        jdbus.call(KGA_BUS, COMPONENT_PATH, MOCK, "EmitSignal", "sssav",
                   (COMPONENT_IFACE, "globalShortcutReleased", "ssx", [("s", componente), ("s", acao), ("x", 0)]))

    return types_ns(chamadas=chamadas, soltar=soltar)


class _PortalFalso:
    """Portal GlobalShortcuts falso: responde cada pedido com o código configurado,
    emitindo Response no caminho de request previsto a partir do handle_token."""

    def __init__(self, servicos, hk, *, create=0, bind=0, versao=2):
        self.jdbus = servicos.jdbus
        self.hk = hk
        self.codigos = {"CreateSession": create, "BindShortcuts": bind}
        servicos.subir(PORTAL_BUS, PORTAL_PATH, IFACE_GS)
        j = self.jdbus
        j.call(PORTAL_BUS, PORTAL_PATH, MOCK, "AddProperty", "ssv", (IFACE_GS, "version", ("u", versao)))
        pedido = "ret = '/org/freedesktop/portal/desktop/request/outro/caminho'"
        j.call(PORTAL_BUS, PORTAL_PATH, MOCK, "AddMethods", "sa(ssss)", (IFACE_GS, [
            ("CreateSession", "a{sv}", "o", pedido),
            ("BindShortcuts", "oa(sa{sv})sa{sv}", "o", pedido),
        ]))
        j.call(PORTAL_BUS, PORTAL_PATH, MOCK, "AddMethod", "sssss",
               ("org.freedesktop.host.portal.Registry", "Register", "sa{sv}", "", ""))
        j.call(PORTAL_BUS, PORTAL_PATH, MOCK, "AddObject", "ssa{sv}a(ssss)",
               (SESSAO, "org.freedesktop.portal.Session", {}, [("Close", "", "", "")]))
        self._respondidos = set()
        self._parar = threading.Event()
        self._thread = threading.Thread(target=self._responder, daemon=True)
        self._thread.start()

    def _responder(self):
        j = self.jdbus
        while not self._parar.is_set():
            time.sleep(0.05)
            router = self.hk._router
            if router is None:
                continue
            remetente = router.unique_name.lstrip(":").replace(".", "_")
            for metodo in ("CreateSession", "BindShortcuts"):
                try:
                    (linhas,) = j.call(PORTAL_BUS, PORTAL_PATH, MOCK, "GetMethodCalls", "s", (metodo,))
                except Exception:
                    continue
                for indice, (_ts, args) in enumerate(linhas):
                    if (metodo, indice) in self._respondidos:
                        continue
                    self._respondidos.add((metodo, indice))
                    token = _valor(_valor(args[-1])["handle_token"])
                    caminho = f"{PORTAL_PATH}/request/{remetente}/{token}"
                    if metodo == "CreateSession":
                        resultados = {"session_handle": ("s", SESSAO)}
                    else:
                        resultados = {"shortcuts": ("a(sa{sv})", [("ptt", {"trigger_description": ("s", "Meta+Shift+G")})])}
                    j.call(PORTAL_BUS, PORTAL_PATH, MOCK, "AddObject", "ssa{sv}a(ssss)",
                           (caminho, "org.freedesktop.portal.Request", {}, []))
                    j.call(PORTAL_BUS, caminho, MOCK, "EmitSignal", "sssav",
                           ("org.freedesktop.portal.Request", "Response", "ua{sv}",
                            [("u", self.codigos[metodo]), ("a{sv}", resultados)]))

    def chamadas(self, caminho=PORTAL_PATH):
        (linhas,) = self.jdbus.call(PORTAL_BUS, caminho, MOCK, "GetCalls", "", ())
        return [nome for _ts, nome, _args in linhas]

    def args(self, metodo):
        (linhas,) = self.jdbus.call(PORTAL_BUS, PORTAL_PATH, MOCK, "GetMethodCalls", "s", (metodo,))
        return [[_valor(a) for a in args] for _ts, args in linhas]

    def sinal(self, membro, sessao=SESSAO, atalho="ptt"):
        self.jdbus.call(PORTAL_BUS, PORTAL_PATH, MOCK, "EmitSignal", "sssav",
                        (IFACE_GS, membro, "osta{sv}", [("o", sessao), ("s", atalho), ("t", 0), ("a{sv}", {})]))

    def parar(self):
        self._parar.set()
        self._thread.join(timeout=2)


def _ptt(eventos):
    return HotkeyBinding("ptt", "Falar com o JARVIS (segurar)", "<cmd>+<shift>+g",
                         lambda: eventos.append("press"), lambda: eventos.append("release"))


# ── KGlobalAccel ─────────────────────────────────────────────────────────────────

@linux
def test_kga_bind_flags_padrao_e_ativo_e_sinais(servicos):
    from jarvis.platform.linux.hotkeys_kglobalaccel import IS_DEFAULT, SET_PRESENT, KGlobalAccelHotkeys

    kga = _subir_kga(servicos)
    assert KGlobalAccelHotkeys.probe(WAYLAND).ok
    hk = KGlobalAccelHotkeys(WAYLAND)
    eventos = []
    try:
        assert hk.listen_keys(None, None) is False
        assert hk.bind([_ptt(eventos)]) == {"ptt": "Meta+Shift+G"}
        acao = ["jarvis", "ptt", "J.A.R.V.I.S.", "Falar com o JARVIS (segurar)"]
        qt = 0x10000000 | 0x02000000 | 0x47
        assert kga.chamadas("doRegister") == [[acao]]
        assert kga.chamadas("setShortcut") == [[acao, [qt], IS_DEFAULT], [acao, [qt], SET_PRESENT]]
        assert (IS_DEFAULT, SET_PRESENT) == (8, 2)

        hk.invoke_shortcut("ptt")
        assert _esperar(lambda: eventos == ["press"])
        kga.soltar(componente="outro")
        kga.soltar()
        assert _esperar(lambda: eventos == ["press", "release"])
    finally:
        hk.stop()
    assert kga.chamadas("unRegister") == [[acao]]


@linux
def test_kga_conflito_avisa_uma_vez(servicos, capsys):
    from jarvis.platform.linux.hotkeys_kglobalaccel import SEM_ATALHO, KGlobalAccelHotkeys

    _subir_kga(servicos, conflito=True)
    hk = KGlobalAccelHotkeys(WAYLAND)
    try:
        assert hk.bind([_ptt([])]) == {"ptt": SEM_ATALHO}
        assert hk.bind([_ptt([])]) == {"ptt": SEM_ATALHO}
    finally:
        hk.stop()
    assert capsys.readouterr().out.count("em conflito") == 1


@linux
def test_kga_sonda_sem_servico():
    from jarvis.platform.linux.hotkeys_kglobalaccel import KGlobalAccelHotkeys

    assert KGlobalAccelHotkeys.probe(WAYLAND).ok is False


# ── portal ───────────────────────────────────────────────────────────────────────

@linux
def test_portal_fluxo_completo(servicos, isolated_home):
    from jarvis.platform.linux.desktop_entry import desktop_entry_path
    from jarvis.platform.linux_wayland.hotkeys_portal import PortalGlobalShortcuts

    hk = PortalGlobalShortcuts(WAYLAND, app_id="io.github.teste.Jarvis")
    assert not desktop_entry_path("io.github.teste.Jarvis").exists()  # nada no __init__
    portal = _PortalFalso(servicos, hk)
    eventos = []
    try:
        assert PortalGlobalShortcuts.probe(WAYLAND).ok
        assert hk.listen_keys(None, None) is False
        assert hk.bind([_ptt(eventos)]) == {"ptt": "Meta+Shift+G"}
        assert hk.name == "portal"
        assert desktop_entry_path("io.github.teste.Jarvis").exists()

        nomes = portal.chamadas()
        assert nomes.index("Register") < nomes.index("CreateSession") < nomes.index("BindShortcuts")
        (sessao, atalhos, janela, _opcoes), = portal.args("BindShortcuts")
        assert sessao == SESSAO and janela == ""
        assert [(i, {k: _valor(v) for k, v in p.items()}) for i, p in atalhos] == [
            ("ptt", {"description": "Falar com o JARVIS (segurar)", "preferred_trigger": "LOGO+SHIFT+g"})]

        portal.sinal("Activated", sessao="/org/freedesktop/portal/desktop/session/outra")
        portal.sinal("Activated")
        assert _esperar(lambda: eventos == ["press"])
        portal.sinal("Deactivated")
        assert _esperar(lambda: eventos == ["press", "release"])
        hk.stop()
        assert "Close" in portal.chamadas(SESSAO)  # Close vai no objeto da sessão
    finally:
        hk.stop()
        portal.parar()


@linux
def test_portal_resposta_1_recusa_sem_repetir(servicos):
    from jarvis.platform.linux_wayland.hotkeys_portal import PortalGlobalShortcuts

    hk = PortalGlobalShortcuts(WAYLAND, app_id="io.github.teste.Jarvis")
    portal = _PortalFalso(servicos, hk, bind=1)
    try:
        with pytest.raises(CapabilityUnavailable, match="usuário recusou"):
            hk.bind([_ptt([])])
        antes = len(portal.chamadas())
        with pytest.raises(CapabilityUnavailable, match="usuário recusou"):
            hk.bind([_ptt([])])
        assert len(portal.chamadas()) == antes
    finally:
        hk.stop()
        portal.parar()


@linux
def test_portal_resposta_2_cai_para_kglobalaccel(servicos, capsys):
    from jarvis.platform.linux_wayland.hotkeys_portal import PortalGlobalShortcuts

    kga = _subir_kga(servicos)
    hk = PortalGlobalShortcuts(WAYLAND, app_id="io.github.teste.Jarvis")
    portal = _PortalFalso(servicos, hk, bind=2)
    eventos = []
    try:
        assert hk.bind([_ptt(eventos)]) == {"ptt": "Meta+Shift+G"}
        assert hk.name == "kglobalaccel"
        assert "usando o KGlobalAccel" in capsys.readouterr().out
        assert len(kga.chamadas("setShortcut")) == 2
    finally:
        hk.stop()
        portal.parar()


@linux
def test_portal_sondas(servicos):
    from jarvis.platform.linux_wayland.hotkeys_portal import PortalGlobalShortcuts

    assert PortalGlobalShortcuts.probe(WAYLAND).ok is False  # sem portal
    hk = PortalGlobalShortcuts(WAYLAND, app_id="io.github.teste.Jarvis")
    portal = _PortalFalso(servicos, hk, versao=0)
    try:
        p = PortalGlobalShortcuts.probe(WAYLAND)
        assert p.ok is False and "versão 0" in p.reason
    finally:
        portal.parar()
