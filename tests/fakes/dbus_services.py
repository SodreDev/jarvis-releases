"""Serviço D-Bus falso via python-dbusmock, para rodar SEMPRE em cima de
`private_session_bus` (`tests/conftest.py`) — nunca no D-Bus do host.
Usado pelos testes K de F2-01 (portal/KGlobalAccel), F2-02 (tray
watcher), F2-03 (volume, se algum dia via D-Bus), F2-04 (Klipper),
F2-05 (Notifications) e F2-07 (ScreenSaver/Mutter/logind).
"""
from __future__ import annotations

import subprocess
from contextlib import contextmanager

import dbus
from dbusmock import DBusTestCase


@contextmanager
def fake_dbus_service(bus_name: str, obj_path: str, interface: str):
    """Sobe um serviço mock em `bus_name`/`obj_path` (dbusmock,
    `system_bus=False` — sempre a sessão privada da fixture
    `private_session_bus`). Devolve `(mock_iface, real_iface)`:
    `mock_iface.AddMethod(interface, nome, in_sig, out_sig, code)` define
    o comportamento; `mock_iface.EmitSignal(...)` dispara sinais;
    `real_iface` é o proxy pela interface real, para o código sob teste
    (ou o próprio teste) chamar como se fosse o serviço de verdade.
    """
    proc: subprocess.Popen = DBusTestCase.spawn_server(bus_name, obj_path, interface, system_bus=False)
    try:
        bus = dbus.SessionBus()
        obj = bus.get_object(bus_name, obj_path)
        mock_iface = dbus.Interface(obj, "org.freedesktop.DBus.Mock")
        real_iface = dbus.Interface(obj, interface)
        yield mock_iface, real_iface
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
