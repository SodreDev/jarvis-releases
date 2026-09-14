"""K F2-01 (a): backend pynput literal e o registro de HOTKEYS no win32/x11.

- listen_keys = keyboard.Listener(on_press=..., on_release=...) + start, igual ao
  oráculo legado; bind = GlobalHotKeys(handlers) com o mesmo log, parando o anterior.
- Sonda com pynput falso em sys.modules (o pynput real abriria conexão com o X de
  quem roda os testes).
"""
import sys
import types

import pytest

from jarvis.platform import registry
from jarvis.platform.capabilities import Cap
from jarvis.platform.common.pynput_hotkeys import PynputHotkeys
from jarvis.platform.protocols import HotkeyBinding
from tests.golden.legacy_31bc0ce import legacy_start_global_hotkeys, legacy_start_keyboard_listener


class _Listener:
    criados = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.eventos = []
        _Listener.criados.append(self)

    def start(self):
        self.eventos.append("start")

    def stop(self):
        self.eventos.append("stop")


class _GlobalHotKeys:
    def __init__(self, handlers):
        self.handlers = handlers
        self.eventos = []

    def start(self):
        self.eventos.append("start")

    def stop(self):
        self.eventos.append("stop")


class _Log:
    def __init__(self):
        self.linhas = []

    def info(self, msg):
        self.linhas.append(("info", msg))

    def warn(self, msg, exc_info=None):
        self.linhas.append(("warn", msg, exc_info))


def test_listen_keys_igual_ao_legado():
    teclado = types.SimpleNamespace(Listener=_Listener)
    on_press, on_release = (lambda k: None), (lambda k: None)
    hk = PynputHotkeys(keyboard_mod=teclado)
    assert hk.listen_keys(on_press, on_release) is True
    novo = hk._listener
    velho = legacy_start_keyboard_listener(teclado, has_feature=True, on_press=on_press, on_release=on_release)
    assert novo.kwargs == velho.kwargs == {"on_press": on_press, "on_release": on_release}
    assert novo.eventos == velho.eventos == ["start"]


def test_bind_igual_ao_legado_e_log():
    raw = {"<ctrl>+<shift>+s": "screenshot_analise", "<ctrl>+<shift>+x": "acao_desconhecida",
           "<ctrl>+<shift>+h": "hist_hoje"}
    cmds = {"screenshot_analise": "analise a tela", "hist_hoje": "o que eu disse hoje"}
    handler = {cmd: (lambda c=cmd: c) for cmd in cmds.values()}

    # o main.py filtra a ação desconhecida e monta os HotkeyBinding
    bindings = [HotkeyBinding(id=a, description=cmds[a], trigger=c, on_press=handler[cmds[a]])
                for c, a in raw.items() if a in cmds]
    log_novo, log_velho = _Log(), []
    hk = PynputHotkeys(global_hotkeys_cls=_GlobalHotKeys, log=log_novo)
    efetivos = hk.bind(bindings)

    velho = legacy_start_global_hotkeys(_GlobalHotKeys, has_feature=True, raw=raw, hotkey_cmds=cmds,
                                        make_handler=lambda cmd: handler[cmd], print_fn=lambda s: None,
                                        log_info=log_velho.append)
    assert hk._hotkeys_listener.handlers == velho.handlers
    assert hk._hotkeys_listener.eventos == ["start"]
    assert log_novo.linhas == [("info", log_velho[0])]
    assert efetivos == {"screenshot_analise": "<ctrl>+<shift>+s", "hist_hoje": "<ctrl>+<shift>+h"}


def test_bind_de_novo_para_o_anterior():
    hk = PynputHotkeys(global_hotkeys_cls=_GlobalHotKeys, log=_Log())
    b = [HotkeyBinding("hist_hoje", "o que eu disse hoje", "<ctrl>+<shift>+h", lambda: None)]
    hk.bind(b)
    primeiro = hk._hotkeys_listener
    hk.bind(b)
    assert primeiro.eventos == ["start", "stop"]
    assert hk._hotkeys_listener is not primeiro


def test_bind_com_falha_loga_warn():
    erro = RuntimeError("sem X")

    def quebra(_handlers):
        raise erro

    log = _Log()
    PynputHotkeys(global_hotkeys_cls=quebra, log=log).bind(
        [HotkeyBinding("hist_hoje", "x", "<ctrl>+<shift>+h", lambda: None)])
    assert log.linhas == [("warn", "HOTKEYS: Falha ao registrar atalhos: sem X", erro)]


def test_stop_para_os_dois():
    hk = PynputHotkeys(keyboard_mod=types.SimpleNamespace(Listener=_Listener),
                       global_hotkeys_cls=_GlobalHotKeys, log=_Log())
    hk.listen_keys(lambda k: None, lambda k: None)
    hk.bind([HotkeyBinding("hist_hoje", "x", "<ctrl>+<shift>+h", lambda: None)])
    listener, globais = hk._listener, hk._hotkeys_listener
    hk.stop()
    assert listener.eventos[-1] == "stop" and globais.eventos[-1] == "stop"


def test_sonda_com_e_sem_pynput(monkeypatch):
    falso = types.ModuleType("pynput")
    falso_teclado = types.ModuleType("pynput.keyboard")
    falso_teclado.GlobalHotKeys = _GlobalHotKeys
    falso.keyboard = falso_teclado
    monkeypatch.setitem(sys.modules, "pynput", falso)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", falso_teclado)
    assert PynputHotkeys.probe(None).ok

    monkeypatch.setitem(sys.modules, "pynput", None)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", None)
    p = PynputHotkeys.probe(None)
    assert p.ok is False and "pynput indisponível" in p.reason


def test_cadeias_win32_e_x11():
    pynput = ("jarvis.platform.common.pynput_hotkeys:PynputHotkeys",)
    assert registry._chain_for(Cap.HOTKEYS, "win32")[0] == pynput[0]
    assert registry._chain_for(Cap.HOTKEYS, "linux-x11")[0] == pynput[0]
