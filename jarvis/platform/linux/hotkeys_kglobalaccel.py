"""Atalhos globais pelo KGlobalAccel do KDE (F2-01), em X11 e Wayland, sem diálogo.

Interface ``org.kde.KGlobalAccel`` em ``org.kde.kglobalaccel`` ``/kglobalaccel``. No
Plasma 6 o serviço vem do próprio KWin: a sonda é o nome ter dono no D-Bus de
sessão (nunca procurar ou executar processo).

- ``actionId = ["jarvis", id, "J.A.R.V.I.S.", descrição]``; ``doRegister(actionId)``;
- ``setShortcut(actionId, [qt_key], IsDefault)`` grava o atalho padrão e
  ``setShortcut(actionId, [qt_key], SetPresent)`` ativa com autoloading, então um
  atalho salvo pelo usuário prevalece (``SetShortcutFlag`` de kglobalaccel_p.h).
  Lista vazia na segunda chamada = conflito: avisa uma vez e devolve o texto
  ``SEM_ATALHO``;
- sinais ``globalShortcutPressed``/``globalShortcutReleased`` ``(s componente, s ação,
  x ts)`` de ``org.kde.kglobalaccel.Component`` viram ``on_press``/``on_release``;
- ``stop()`` = ``unRegister`` de cada ação.
``setShortcut`` é obsoleto no KF6 (``setShortcutKeys`` com ``a(ai)``): dívida anotada.
"""
from __future__ import annotations

import threading
from typing import Dict, List, Sequence

from ..common.base import BackendBase, Probe
from . import dbus as _dbus

BUS_NAME = "org.kde.kglobalaccel"
OBJECT_PATH = "/kglobalaccel"
INTERFACE = "org.kde.KGlobalAccel"
IFACE_COMPONENT = "org.kde.kglobalaccel.Component"
COMPONENTE = "jarvis"
NOME_COMPONENTE = "J.A.R.V.I.S."

# KGlobalAccelPrivate::SetShortcutFlag (kglobalaccel_p.h)
SET_PRESENT = 2
NO_AUTOLOADING = 4
IS_DEFAULT = 8

SEM_ATALHO = "(sem atalho — configure em Configurações do sistema › Atalhos)"

_QT_MODIFICADORES = {
    "shift": 0x02000000,
    "ctrl": 0x04000000, "control": 0x04000000,
    "alt": 0x08000000,
    "cmd": 0x10000000, "super": 0x10000000, "meta": 0x10000000,
}
_QT_TECLAS = {
    "space": 0x20, "esc": 0x01000000, "tab": 0x01000001, "backspace": 0x01000003,
    "enter": 0x01000004, "return": 0x01000004, "insert": 0x01000006, "delete": 0x01000007,
    "home": 0x01000010, "end": 0x01000011, "left": 0x01000012, "up": 0x01000013,
    "right": 0x01000014, "down": 0x01000015, "page_up": 0x01000016, "page_down": 0x01000017,
}
_QT_NOMES = {0x20: "Space", 0x01000000: "Esc", 0x01000001: "Tab", 0x01000004: "Return"}
_QT_MASCARA_MODIFICADORES = 0xFE000000


def convert_trigger_to_qt_key(trigger: str) -> int:
    """Gatilho pynput ("<cmd>+<shift>+g") → código Qt (modificadores | tecla)."""
    codigo = 0
    tecla = None
    for bruto in trigger.split("+"):
        parte = bruto.strip()
        nome = (parte[1:-1] if parte.startswith("<") and parte.endswith(">") else parte).lower()
        if nome in _QT_MODIFICADORES:
            codigo |= _QT_MODIFICADORES[nome]
        elif len(nome) == 1:
            tecla = ord(nome.upper())
        elif nome in _QT_TECLAS:
            tecla = _QT_TECLAS[nome]
        elif nome.startswith("f") and nome[1:].isdigit() and 1 <= int(nome[1:]) <= 35:
            tecla = 0x01000030 + int(nome[1:]) - 1  # Qt::Key_F1
        else:
            raise ValueError(f"tecla não suportada no atalho {trigger!r}: {nome!r}")
    if tecla is None:
        raise ValueError(f"atalho sem tecla: {trigger!r}")
    return codigo | tecla


def describe_qt_key(codigo: int) -> str:
    """Código Qt → texto para o usuário ("Meta+Shift+G")."""
    partes = [nome for bit, nome in ((0x10000000, "Meta"), (0x04000000, "Ctrl"),
                                     (0x08000000, "Alt"), (0x02000000, "Shift")) if codigo & bit]
    tecla = codigo & ~_QT_MASCARA_MODIFICADORES
    if tecla in _QT_NOMES:
        partes.append(_QT_NOMES[tecla])
    elif 0x20 < tecla < 0x7F:
        partes.append(chr(tecla))
    elif 0x01000030 <= tecla < 0x01000030 + 35:
        partes.append(f"F{tecla - 0x01000030 + 1}")
    else:
        partes.append(hex(tecla))
    return "+".join(partes)


class KGlobalAccelHotkeys(BackendBase):
    name = "kglobalaccel"

    def __init__(self, ctx=None):
        self.ctx = ctx
        self._lock = threading.Lock()
        self._acoes: Dict[str, List[str]] = {}
        self._handlers: Dict[str, tuple] = {}
        self._conflitos_avisados = set()
        self._fila = None
        self._despachante = None
        self._parar = threading.Event()

    @classmethod
    def probe(cls, ctx) -> Probe:
        if _dbus.name_has_owner(BUS_NAME):
            return Probe(True)
        return Probe(False, f"{BUS_NAME} sem dono no D-Bus de sessão")

    def listen_keys(self, on_press, on_release) -> bool:
        return False

    def bind_action(self, action_id: str, description: str, trigger: str) -> str:
        """Registra uma ação e seu atalho; devolve a descrição do atalho ativo."""
        acao = [COMPONENTE, action_id, NOME_COMPONENTE, description]
        qt_key = convert_trigger_to_qt_key(trigger)
        _dbus.call(BUS_NAME, OBJECT_PATH, INTERFACE, "doRegister", "as", (acao,))
        _dbus.call(BUS_NAME, OBJECT_PATH, INTERFACE, "setShortcut", "asaiu", (acao, [qt_key], IS_DEFAULT))
        (ativos,) = _dbus.call(BUS_NAME, OBJECT_PATH, INTERFACE, "setShortcut", "asaiu",
                               (acao, [qt_key], SET_PRESENT))
        self._acoes[action_id] = acao
        if not ativos or not any(ativos):
            if action_id not in self._conflitos_avisados:
                self._conflitos_avisados.add(action_id)
                print(f"[HOTKEYS] KGlobalAccel: {trigger!r} em conflito para {action_id!r}; "
                      "configure em Configurações do sistema › Atalhos.")
            return SEM_ATALHO
        return describe_qt_key(int(ativos[0]))

    def bind(self, bindings: Sequence) -> Dict[str, str]:
        efetivos = {}
        for b in bindings:
            self._handlers[b.id] = (b.on_press, b.on_release)
            efetivos[b.id] = self.bind_action(b.id, b.description, b.trigger)
        self._assinar()
        return efetivos

    def invoke_shortcut(self, action_id: str) -> None:
        """Dispara a ação como se o atalho fosse pressionado (smoke/testes)."""
        (caminho,) = _dbus.call(BUS_NAME, OBJECT_PATH, INTERFACE, "getComponent", "s", (COMPONENTE,))
        _dbus.call(BUS_NAME, str(caminho), IFACE_COMPONENT, "invokeShortcut", "s", (action_id,))

    # ── sinais ─────────────────────────────────────────────────────────────────
    def _assinar(self) -> None:
        with self._lock:
            if self._fila is not None:
                return
            self._parar.clear()
            self._fila = _dbus.subscribe(_dbus.match_rule(interface=IFACE_COMPONENT), bufsize=256)
            self._despachante = threading.Thread(
                target=self._despachar, args=(self._fila,), daemon=True, name="KGlobalAccelHotkeys"
            )
            self._despachante.start()

    def _despachar(self, fila) -> None:
        from jeepney.low_level import HeaderFields

        while not self._parar.is_set():
            msg = fila.get(timeout=0.25)
            if msg is None:
                continue
            membro = msg.header.fields.get(HeaderFields.member)
            if membro not in ("globalShortcutPressed", "globalShortcutReleased"):
                continue
            try:
                componente, acao = msg.body[0], msg.body[1]
            except (IndexError, TypeError):
                continue
            if componente != COMPONENTE:
                continue
            par = self._handlers.get(acao)
            callback = (par[0] if membro == "globalShortcutPressed" else par[1]) if par else None
            if callback is None:
                continue
            try:
                callback()
            except Exception as e:
                print(f"[HOTKEYS] handler de {acao!r} falhou: {e}")

    def stop(self) -> None:
        self._parar.set()
        with self._lock:
            fila, self._fila = self._fila, None
        if fila is not None:
            fila.close()
        for acao in list(self._acoes.values()):
            try:
                _dbus.call(BUS_NAME, OBJECT_PATH, INTERFACE, "unRegister", "as", (acao,), _dbus.PROBE_TIMEOUT)
            except Exception:
                pass
        self._acoes.clear()
